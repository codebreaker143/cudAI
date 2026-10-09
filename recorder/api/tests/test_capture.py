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
