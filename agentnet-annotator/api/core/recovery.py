"""
Recover recordings that were interrupted (app crash, force quit, power loss).

An interrupted recording has video segments in `segments/` but no final
`video.mp4`. On startup we stop any capture process left behind, rebuild the
video from the segments (pauses are known from the pause/resume events),
complete metadata.json and hand the recording to the reducer.
"""

import json
import os
import signal
import subprocess
import time
from datetime import datetime

from .logger import logger
from .utils import RECORDING_DIR, get_ffmpeg_path, read_encrypted_jsonl
from .xrec_capture import XrecCapture


def stop_orphaned_captures() -> None:
    """SIGINT any FFmpeg screen capture started by a previous cudAI backend."""
    try:
        output = subprocess.run(
            ["pgrep", "-f", f"{get_ffmpeg_path()} .*avfoundation"],
            stdout=subprocess.PIPE,
            text=True,
        ).stdout
    except Exception:
        return
    pids = [int(p) for p in output.split() if p.isdigit() and int(p) != os.getpid()]
    for pid in pids:
        logger.warning(f"recovery: stopping orphaned screen capture (pid {pid})")
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            pass
    deadline = time.time() + 10
    while pids and time.time() < deadline:
        pids = [p for p in pids if _alive(p)]
        time.sleep(0.2)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def find_interrupted_recordings() -> list:
    if not os.path.isdir(RECORDING_DIR):
        return []
    found = []
    for name in os.listdir(RECORDING_DIR):
        path = os.path.join(RECORDING_DIR, name)
        if (
            os.path.isdir(os.path.join(path, "segments"))
            and not os.path.exists(os.path.join(path, "video.mp4"))
        ):
            found.append(path)
    return found


def _to_iso(metadata: dict, t: float) -> str | None:
    clock = metadata.get("clock")
    if not clock:
        return None
    unix = clock["unix_time"] + (t - clock["perf_counter"])
    return datetime.fromtimestamp(unix).astimezone().isoformat()


def recover_recording(recording_path: str) -> bool:
    """Finalize an interrupted recording. Returns True if it has usable video."""
    from .metadata import MetadataManager

    recording_id = os.path.basename(recording_path)
    events_path = os.path.join(recording_path, "events.jsonl")
    events = read_encrypted_jsonl(events_path) if os.path.exists(events_path) else []

    # Segment i ends at the i-th pause; the last one at the last event.
    pauses, open_pause = [], None
    for e in events:
        if e["action"] == "pause":
            open_pause = {"start_timestamp": e["time_stamp"], "end_timestamp": None}
            pauses.append(open_pause)
        elif e["action"] == "resume" and open_pause:
            open_pause["end_timestamp"] = e["time_stamp"]
            open_pause = None
    last_event = events[-1]["time_stamp"] if events else None
    stop_requests = [p["start_timestamp"] for p in pauses] + [last_event]

    capture = XrecCapture(recording_path)
    capture.load_segments_from_disk(stop_requests)
    if not capture.segments:
        logger.warning(f"recovery: no usable video in {recording_id}")
        return False

    metadata_path = os.path.join(recording_path, "metadata.json")
    manager = MetadataManager(recording_path=recording_path, recording_id=recording_id)
    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            manager.metadata.update(json.load(f))

    manager.metadata["pauses"] = pauses
    manager.metadata["recovered"] = True
    end = last_event or capture.segments[-1]["start_timestamp"]
    manager.metadata["stop_time"] = _to_iso(manager.metadata, end)
    manager.set_video(capture.finalize())
    manager.save_metadata()
    logger.info(f"recovery: recovered interrupted recording {recording_id}")
    return True
