import os

import cv2
import pytest

from core.utils import get_ffmpeg_path, h264_encoder_args, run_ffmpeg
from core.xrec_capture import XrecCapture

pytestmark = pytest.mark.skipif(
    not os.path.exists(get_ffmpeg_path()), reason="bundled ffmpeg not present"
)

FPS = 30


def make_clip(path, frames):
    result = run_ffmpeg(
        ["-y", "-f", "lavfi", "-i", f"testsrc=s=320x200:r={FPS}",
         "-frames:v", str(frames), *h264_encoder_args(),
         "-fps_mode", "cfr", "-r", str(FPS), path]
    )
    assert result.returncode == 0, result.stderr


def segment(tmp_path, index, start, frames, stop_requested_at=None):
    path = str(tmp_path / "segments" / f"segment_{index:03d}.mp4")
    make_clip(path, frames)
    return {
        "index": index,
        "file": path,
        "start_timestamp": start,
        "frames": frames,
        "duration": frames / FPS,
        "width": 320,
        "height": 200,
        "stop_requested_at": stop_requested_at,
    }


def frame_at(path, t):
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    cap.release()
    assert ok
    return frame


def test_pause_gap_is_black_and_timeline_is_linear(tmp_path):
    (tmp_path / "segments").mkdir()
    capture = XrecCapture(str(tmp_path), fps=FPS)
    capture.segments = [
        segment(tmp_path, 0, 100.0, 60),
        segment(tmp_path, 1, 103.5, 60),
    ]
    info = capture.finalize()

    video = str(tmp_path / "video.mp4")
    cap = cv2.VideoCapture(video)
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 60 + 45 + 60
    cap.release()

    # Second segment starts exactly at its clock offset.
    assert info["segments"][1]["video_offset"] == pytest.approx(3.5)
    assert frame_at(video, 2.7).mean() == 0  # paused gap
    assert frame_at(video, 4.0).mean() > 50  # resumed content
    assert not (tmp_path / "segments").exists()


def test_frames_after_pause_request_are_trimmed(tmp_path):
    (tmp_path / "segments").mkdir()
    capture = XrecCapture(str(tmp_path), fps=FPS)
    # FFmpeg kept capturing 0.5s (15 frames) after the user paused at 101.5.
    capture.segments = [
        segment(tmp_path, 0, 100.0, 60, stop_requested_at=101.5),
        segment(tmp_path, 1, 104.0, 30),
    ]
    info = capture.finalize()

    assert info["segments"][0]["frames"] == 45
    assert info["paused_gaps"][0]["start_timestamp"] == pytest.approx(101.5)
    assert info["segments"][1]["video_offset"] == pytest.approx(4.0)
    assert frame_at(str(tmp_path / "video.mp4"), 1.7).mean() == 0


def test_interrupted_recording_is_recovered(tmp_path, monkeypatch):
    import json

    import core.recovery as recovery

    rec = tmp_path / "rec-1"
    (rec / "segments").mkdir(parents=True)
    # Segment 0: 100.0 -> paused at 101.5 (60 frames captured, 45 wanted).
    # Segment 1: 104.0 -> app crashed; last input event at 104.8.
    for index, (start, frames) in enumerate([(100.0, 60), (104.0, 60)]):
        make_clip(str(rec / "segments" / f"segment_{index:03d}.mp4"), frames)
        (rec / "segments" / f"segment_{index:03d}.log").write_text(
            f"Input #0, avfoundation\n  Duration: N/A, start: {start:.6f}\n"
            f"Output #0, mp4\n  Stream #0:0: Video: h264, yuv420p, 320x200\nframe=   {frames}\n"
        )
    events = [
        {"time_stamp": 100.5, "action": "click", "x": 1, "y": 1, "button": "left", "pressed": True},
        {"time_stamp": 101.5, "action": "pause"},
        {"time_stamp": 104.1, "action": "resume"},
        {"time_stamp": 104.8, "action": "click", "x": 1, "y": 1, "button": "left", "pressed": False},
    ]
    (rec / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    monkeypatch.setattr(recovery, "RECORDING_DIR", str(tmp_path))

    assert recovery.find_interrupted_recordings() == [str(rec)]
    assert recovery.recover_recording(str(rec))

    metadata = json.loads((rec / "metadata.json").read_text())
    video = metadata["video"]
    assert metadata["recovered"] is True
    assert [s["frames"] for s in video["segments"]] == [45, 24]
    assert video["segments"][1]["video_offset"] == pytest.approx(4.0)
    assert metadata["pauses"] == [{"start_timestamp": 101.5, "end_timestamp": 104.1}]
    assert (rec / "video.mp4").exists()
    assert recovery.find_interrupted_recordings() == []


def test_interrupted_two_display_recording_is_recovered(tmp_path, monkeypatch):
    import json

    import core.recovery as recovery
    from core.displays import segments_dir_name

    rec = tmp_path / "rec-2"
    for display in (0, 1):
        seg = rec / segments_dir_name(display)
        seg.mkdir(parents=True)
        make_clip(str(seg / "segment_000.mp4"), 60)
        (seg / "segment_000.log").write_text(
            f"Input #0, avfoundation\n  Duration: N/A, start: {100.0 + display * 0.02:.6f}\n"
            "Output #0, mp4\n  Stream #0:0: Video: h264, yuv420p, 320x200\nframe=   60\n"
        )
    (rec / "events.jsonl").write_text(json.dumps(
        {"time_stamp": 101.5, "action": "click", "x": 1, "y": 1, "button": "left", "pressed": True}
    ) + "\n")
    displays = [
        {"index": 0, "bounds": {"x": 0, "y": 0, "width": 320, "height": 200}, "video": None},
        {"index": 1, "bounds": {"x": 320, "y": 0, "width": 320, "height": 200}, "video": None},
    ]
    (rec / "metadata.json").write_text(json.dumps({"displays": displays, "pauses": []}))
    monkeypatch.setattr(recovery, "RECORDING_DIR", str(tmp_path))

    assert recovery.recover_recording(str(rec))

    metadata = json.loads((rec / "metadata.json").read_text())
    assert (rec / "video.mp4").exists() and (rec / "video_display_1.mp4").exists()
    assert [d["video"]["file"] for d in metadata["displays"]] == ["video.mp4", "video_display_1.mp4"]
    # Both trimmed to the last input event (101.5 s).
    assert [d["video"]["segments"][0]["frames"] for d in metadata["displays"]] == [45, 44]


def chunked_segment(chunk_dir, chunk_frames, partial_line=False):
    """A segment as FFmpeg's segment muxer leaves it: chunks + chunks.csv."""
    chunk_dir.mkdir(parents=True)
    lines, start = [], 0
    for i, frames in enumerate(chunk_frames):
        make_clip(str(chunk_dir / f"chunk_{i:05d}.mp4"), frames)
        lines.append(f"chunk_{i:05d}.mp4,{start / FPS:.6f},{(start + frames) / FPS:.6f}\n")
        start += frames
    (chunk_dir / "chunks.csv").write_text(
        "".join(lines) + (f"chunk_{len(chunk_frames):05d}.mp4,{start / FPS:.6f},1" if partial_line else "")
    )


def video_frames(path):
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return n


def test_chunks_after_pause_request_are_held_back_and_trimmed(tmp_path):
    capture = XrecCapture(str(tmp_path), fps=FPS)
    chunk_dir = tmp_path / "chunks" / "display_0" / "segment_000"
    chunked_segment(chunk_dir, [30, 30, 30])  # 3 x 1 s
    seg = {
        "index": 0, "chunk_dir": str(chunk_dir), "start_timestamp": 100.0,
        "width": 320, "height": 200,
    }
    capture.segments = [seg]
    assert [c["frames"] for c in capture.ready_chunks()] == [30, 30, 30]

    # Paused at 101.5 s: while FFmpeg shuts down, only chunks that end before
    # the request may be uploaded.
    seg["stop_requested_at"] = 101.5
    ready = capture.ready_chunks()
    assert [c["path"] for c in ready] == ["chunks/display_0/segment_000/chunk_00000.mp4"]

    capture._seal(seg)
    assert [(c["start_frame"], c["frames"]) for c in capture.ready_chunks()] == [(0, 30), (30, 15)]
    assert video_frames(chunk_dir / "chunk_00001.mp4") == 15
    assert not (chunk_dir / "chunk_00002.mp4").exists()

    info = capture.finalize()
    assert info["duration"] == pytest.approx(1.5)
    assert video_frames(tmp_path / "video.mp4") == 45
    assert info["segments"][0]["chunks"] == [
        {"path": "chunks/display_0/segment_000/chunk_00000.mp4", "start_frame": 0, "frames": 30},
        {"path": "chunks/display_0/segment_000/chunk_00001.mp4", "start_frame": 30, "frames": 15},
    ]
    assert (chunk_dir / "chunk_00000.mp4").exists()  # kept for upload
    assert info["parts"] == [c["path"] for c in info["segments"][0]["chunks"]]


def test_chunked_pause_gap_is_kept_with_chunks(tmp_path):
    capture = XrecCapture(str(tmp_path), fps=FPS)
    segs = []
    for index, start in enumerate([100.0, 103.0]):  # 1 s recorded, 2 s paused
        chunk_dir = tmp_path / "chunks" / "display_0" / f"segment_{index:03d}"
        chunked_segment(chunk_dir, [30])
        segs.append({"index": index, "chunk_dir": str(chunk_dir), "start_timestamp": start,
                     "stop_requested_at": start + 1.0, "width": 320, "height": 200})
    capture.segments = segs
    info = capture.finalize()
    assert info["parts"] == [
        "chunks/display_0/segment_000/chunk_00000.mp4",
        "chunks/display_0/gap_001.mp4",
        "chunks/display_0/segment_001/chunk_00000.mp4",
    ]
    assert (tmp_path / "chunks" / "display_0" / "gap_001.mp4").exists()
    assert video_frames(tmp_path / "video.mp4") == 120


def test_crashed_chunked_recording_keeps_closed_chunks(tmp_path, monkeypatch):
    import json

    import core.recovery as recovery

    rec = tmp_path / "rec-3"
    (rec / "segments").mkdir(parents=True)
    (rec / "segments" / "segment_000.log").write_text(
        "Input #0, avfoundation\n  Duration: N/A, start: 100.000000\n"
        "Output #0, segment\n  Stream #0:0: Video: h264, yuv420p, 320x200\nframe=   60\n"
    )
    chunk_dir = rec / "chunks" / "display_0" / "segment_000"
    chunked_segment(chunk_dir, [30, 30], partial_line=True)
    # Power loss: the chunk being written has no index (moov) and is unlisted.
    (chunk_dir / "chunk_00002.mp4").write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 500)
    (rec / "events.jsonl").write_text(json.dumps(
        {"time_stamp": 103.0, "action": "click", "x": 1, "y": 1, "button": "left", "pressed": True}
    ) + "\n")
    monkeypatch.setattr(recovery, "RECORDING_DIR", str(tmp_path))

    assert recovery.find_interrupted_recordings() == [str(rec)]
    assert recovery.recover_recording(str(rec))
    video = json.loads((rec / "metadata.json").read_text())["video"]
    assert video["segments"][0]["frames"] == 60
    assert len(video["segments"][0]["chunks"]) == 2
    assert video_frames(rec / "video.mp4") == 60


FAKE_FFMPEG = """#!/bin/sh
# Fake FFmpeg: "-i hang:none" ignores SIGINT and never starts; any other
# device reports a start time and runs until killed or sent "q".
case "$*" in
  *hang:none*) trap '' INT; while true; do sleep 1; done ;;
  *) echo "Input #0, avfoundation, start: 123.000000" >&2
     while read -r line; do [ "$line" = q ] && exit 0; done ;;
esac
"""


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # Reaped zombies are not "alive" for our purposes.
    import subprocess as sp
    state = sp.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def test_failed_start_stops_every_display(tmp_path, monkeypatch):
    import core.xrec_capture as capture_module
    from core.xrec_capture import MultiCapture, XrecCapture

    fake = tmp_path / "ffmpeg"
    fake.write_text(FAKE_FFMPEG)
    fake.chmod(0o755)
    monkeypatch.setattr(capture_module, "get_ffmpeg_path", lambda: str(fake))
    monkeypatch.setattr(XrecCapture, "START_TIMEOUT", 1.0)
    monkeypatch.setattr(capture_module, "find_screen_devices", lambda: {0: "good", 1: "hang"})

    displays = [{"index": 0}, {"index": 1}]
    capture = MultiCapture(str(tmp_path), displays)
    with pytest.raises(RuntimeError):
        capture.start_recording()

    for c in capture.captures:
        assert c.process is None
    # Nothing from the fake FFmpeg may survive, including the one ignoring SIGINT.
    import subprocess as sp
    leftovers = sp.run(["pgrep", "-f", str(fake)], capture_output=True, text=True).stdout.split()
    assert [p for p in leftovers if _alive(int(p))] == []
