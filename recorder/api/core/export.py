"""
Standardized, consumer-facing view of a recording (schema cudai.recording.v1).

Writes two files next to the raw data:

- manifest.json   what the recording is and how to read it
- timeline.jsonl  cleaned input events and active-window changes in time order,
                  each stamped with video time, frame index and wall-clock time

Raw files (events.jsonl, top_window.jsonl, ...) are left untouched.
"""

import json
import os
from urllib.parse import urlsplit
from collections import Counter

from .action_reduction.preprocess import preprocess_events
from .constants import SCHEMA_VERSION
from .displays import display_at
from .logger import logger
from .utils import probe_video, read_encrypted_json, read_encrypted_jsonl, write_jsonl

TIME_BASE = (
    "All time_stamp / *_timestamp fields are seconds of a monotonic clock "
    "(Python time.perf_counter). video_time = t - video.video_start_timestamp; "
    "frame = floor(video_time * video.fps); "
    "unix_time = anchor.unix_time + (t - anchor.perf_counter), using the last "
    "of [clock] + clock_anchors with anchor.perf_counter <= t (the monotonic "
    "clock stops while the computer sleeps; see system_sleeps). "
    "Input coordinates are global logical points (origin: top-left of the "
    "main display). Each pointer event's `display` is the index into "
    "`displays`; subtract that display's bounds.x/y and multiply by its "
    "scale_factor for pixels in its video (video.mp4 for display 0, "
    "video_display_N.mp4 otherwise)."
)

KEYBOARD_FIELDS = ("name", "char", "text", "modifiers", "vk")


def _read_jsonl(path: str) -> list:
    return read_encrypted_jsonl(path) if os.path.exists(path) else []


def clock_anchors(metadata: dict) -> list:
    anchors = [metadata["clock"]] if metadata.get("clock") else []
    anchors += metadata.get("clock_anchors") or []
    return sorted(anchors, key=lambda a: a["perf_counter"])


def to_unix(t: float, anchors: list) -> float | None:
    """Wall-clock time of a perf_counter timestamp, robust to system sleep."""
    if not anchors:
        return None
    anchor = anchors[0]
    for candidate in anchors:
        if candidate["perf_counter"] <= t:
            anchor = candidate
        else:
            break
    return anchor["unix_time"] + (t - anchor["perf_counter"])


def _timeline_entry(event: dict, video_start: float, fps: int, anchors: list, displays: list = ()) -> dict:
    t = event["time_stamp"]
    t_video = t - video_start
    unix = to_unix(t, anchors)
    entry = {
        "t": t,
        "t_video": round(t_video, 4),
        "frame": int(t_video * fps) if t_video >= 0 else None,
        "t_unix": round(unix, 4) if unix is not None else None,
        "type": event["action"],
    }
    if event["action"] in ("move", "click", "scroll"):
        entry["x"], entry["y"] = event["x"], event["y"]
        if displays:
            entry["display"] = display_at(displays, event["x"], event["y"])
    if event["action"] == "click":
        entry["button"], entry["pressed"] = event["button"], event["pressed"]
    if event["action"] == "scroll":
        entry["dx"], entry["dy"] = event["dx"], event["dy"]
    if event["action"] in ("press", "release"):
        for field in KEYBOARD_FIELDS:
            if field in event:
                entry[field] = event[field]
    return entry


def build_timeline(recording_path: str, metadata: dict) -> list:
    events = _read_jsonl(os.path.join(recording_path, "events.jsonl"))
    windows = _read_jsonl(os.path.join(recording_path, "top_window.jsonl"))
    video_start = metadata["video_start_timestamp"]
    fps = (metadata.get("video") or {}).get("fps", 30)
    anchors = clock_anchors(metadata)
    displays = metadata.get("displays") or []

    timeline = [
        _timeline_entry(e, video_start, fps, anchors, displays)
        for e in preprocess_events(events, windows)
    ]
    for window in windows:
        entry = _timeline_entry(
            {"time_stamp": window["time_stamp"], "action": "window"},
            video_start, fps, anchors,
        )
        for field in ("app_name", "bundle_id", "pid", "window_title",
                      "window_bounds", "url", "is_recorder"):
            if field in window:
                entry[field] = window[field]
        entry.setdefault("app_name", window.get("top_window_name"))
        timeline.append(entry)

    # Nothing before the first video frame can be aligned to the video.
    timeline = [e for e in timeline if e["t_video"] >= 0]
    timeline.sort(key=lambda e: e["t"])
    return timeline


def _legacy_video_info(recording_path: str, metadata: dict) -> dict:
    """Recordings made before cudai.recording.v1 have no video block."""
    info = {"file": "video.mp4", "video_start_timestamp": metadata["video_start_timestamp"]}
    video_path = os.path.join(recording_path, "video.mp4")
    if os.path.exists(video_path):
        info.update(probe_video(video_path))
    return info


def write_export(recording_path: str) -> dict | None:
    metadata_path = os.path.join(recording_path, "metadata.json")
    if not os.path.exists(metadata_path):
        return None
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    if "video_start_timestamp" not in metadata:
        return None

    try:
        timeline = build_timeline(recording_path, metadata)
        write_jsonl(os.path.join(recording_path, "timeline.jsonl"), timeline)

        task_path = os.path.join(recording_path, "task_name.json")
        task = read_encrypted_json(task_path) if os.path.exists(task_path) else {}
        actions = _read_jsonl(os.path.join(recording_path, "reduced_events_complete.jsonl"))

        counts = Counter(e["type"] for e in timeline)
        apps, sites = [], []
        for e in timeline:
            if e["type"] == "window" and not e.get("is_recorder"):
                if e.get("app_name") and e["app_name"] not in apps:
                    apps.append(e["app_name"])
                host = urlsplit(e["url"]).netloc if e.get("url") else None
                if host and host not in sites:
                    sites.append(host)

        manifest = {
            "schema_version": metadata.get("schema_version", SCHEMA_VERSION),
            "recording_id": metadata.get("recording_id", os.path.basename(recording_path)),
            "parent_recording_id": metadata.get("parent_recording_id"),
            "task": {
                "name": task.get("task_name"),
                "description": task.get("description"),
            },
            "recorder": metadata.get("recorder"),
            "contributor_id": metadata.get("contributor_id"),
            "consent": metadata.get("consent"),
            "privacy": metadata.get("privacy"),
            "start_time": metadata.get("start_time"),
            "stop_time": metadata.get("stop_time"),
            "environment": {
                "os": metadata.get("os") or {
                    "name": metadata.get("system"),
                    "version": metadata.get("release"),
                    "architecture": metadata.get("machine"),
                },
                "model": metadata.get("model"),
                "locale": metadata.get("locale"),
                "keyboard_layout": metadata.get("keyboard_layout"),
                "timezone": metadata.get("timezone"),
                "utc_offset_seconds": metadata.get("utc_offset_seconds"),
                "natural_scrolling": metadata.get("natural_scrolling"),
                "monitors": metadata.get("monitors"),
            },
            "display": metadata.get("display") or {
                "logical_width": metadata.get("screen_width"),
                "logical_height": metadata.get("screen_height"),
                "scale_factor": None,
            },
            "video": metadata.get("video") or _legacy_video_info(recording_path, metadata),
            "displays": metadata.get("displays") or [],
            "clock": metadata.get("clock"),
            "clock_anchors": metadata.get("clock_anchors", []),
            "system_sleeps": metadata.get("system_sleeps", []),
            "pauses": metadata.get("pauses", []),
            "time_base": TIME_BASE,
            "files": {
                "video": "video.mp4",
                "timeline": "timeline.jsonl",
                "raw_events": "events.jsonl",
                "active_windows": "top_window.jsonl",
                "clicked_elements": "element.jsonl",
                "actions": "reduced_events_complete.jsonl",
                "actions_annotated": "reduced_events_vis.jsonl",
            },
            "stats": {
                "event_counts": dict(counts),
                "action_count": len(actions),
                "apps": apps,
                "sites": sites,
            },
        }
        with open(os.path.join(recording_path, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        return manifest
    except Exception:
        logger.exception(f"export: failed for {recording_path}")
        return None
