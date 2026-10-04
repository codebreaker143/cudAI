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
