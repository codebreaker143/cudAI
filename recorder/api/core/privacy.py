"""
Remove personal and sensitive data from recorded text.

Recordings are sold as AI training data, so they must only contain data that
is valuable and legal to share. Detection uses the shared Presidio-based
rules in the cudai_privacy package (privacy/), the same rules the ingest
server applies; values are replaced with placeholders such as
"[EMAIL_ADDRESS]". This module applies them to recordings: keystrokes
(typed one key at a time), window titles, URLs, element trees, task names.
"""

import json
import os
from collections import Counter

from cudai_privacy import PRIVACY_VERSION, find_spans, redact_text, redact_tree

from .logger import logger

__all__ = [
    "PRIVACY_VERSION",
    "find_spans",
    "open_run_start",
    "privacy_version",
    "redact_keystrokes",
    "redact_recording_inputs",
    "redact_recording_outputs",
    "redact_text",
    "redact_tree",
]


# Keystrokes ------------------------------------------------------------------
# Typed text arrives one key at a time, so detection runs over rebuilt typing
# runs and matches are mapped back to the individual key events.

RUN_BREAK_KEYS = {"enter", "return", "tab", "esc", "escape", "up", "down"}
RUN_GAP_SECONDS = 5.0
REDACTED_KEY = "redacted"


def _typing_runs(events: list) -> list:
    """Lists of (event index, typed text) for consecutive typing."""
    runs, current, last_t = [], [], None
    for i, e in enumerate(events):
        action = e.get("action")
        t = e.get("time_stamp", 0)
        if _breaks_run(e, last_t) and current:
            runs.append(current)
            current = []
        if action == "press":
            if e.get("name") == "backspace" and current:
                current.pop()
            elif e.get("text"):
                current.append((i, e["text"]))
            last_t = t
    if current:
        runs.append(current)
    return runs


def _breaks_run(e: dict, last_t) -> bool:
    action = e.get("action")
    return (
        action == "click"
        or action in ("pause", "resume")
        or (action == "press" and e.get("name") in RUN_BREAK_KEYS)
        or (last_t is not None and e.get("time_stamp", 0) - last_t > RUN_GAP_SECONDS)
    )


def open_run_start(events: list, now: float) -> int:
    """
    Index of the first event of a typing run that may still continue at
    `now` (len(events) if there is none). Live upload holds events from there
    on back, so a value typed across an upload boundary is still detected.
    """
    start, last_t = None, None
    for i, e in enumerate(events):
        if _breaks_run(e, last_t):
            start = None
        if e.get("action") == "press":
            if start is None and e.get("text"):
                start = i
            last_t = e.get("time_stamp", 0)
    if start is not None and now - last_t <= RUN_GAP_SECONDS:
        return start
    return len(events)


def _scrub_key(event: dict, text) -> None:
    event["name"] = REDACTED_KEY
    event["char"] = None
    event["vk"] = None
    event["pynput_key"] = None
    if event.get("action") == "press":
        event["text"] = text


def _scrub_press_and_release(events: list, press_index: int, text) -> None:
    original = events[press_index].get("name")
    _scrub_key(events[press_index], text)
    # The matching release names the same physical key.
    for j in range(press_index + 1, len(events)):
        e = events[j]
        if e.get("action") == "release" and e.get("name") == original:
            _scrub_key(e, None)
            return


def redact_keystrokes(events: list, counts: Counter | None = None) -> list:
    """Redact sensitive values typed key by key. Modifies and returns `events`."""
    for run in _typing_runs(events):
        typed = "".join(text for _, text in run)
        # char offset -> index into run
        owners = [k for k, (_, text) in enumerate(run) for _ in text]
        for start, end, label in find_spans(typed):
            keys = sorted({owners[c] for c in range(start, end)})
            first_t = events[run[keys[0]][0]].get("time_stamp", 0)
            last_t = events[run[keys[-1]][0]].get("time_stamp", 0)
            for n, k in enumerate(keys):
                _scrub_press_and_release(events, run[k][0], f"[{label}]" if n == 0 else "")
            # Keys typed then deleted within the span's time range.
            for i, e in enumerate(events):
                if (
                    e.get("action") == "press"
                    and e.get("name") not in (REDACTED_KEY, "backspace")
                    and e.get("text")
                    and first_t <= e.get("time_stamp", 0) <= last_t
                ):
                    _scrub_press_and_release(events, i, "")
            if counts is not None:
                counts[label] += 1
    return events


# Recording files ---------------------------------------------------------------

TREE_FILES = ("element.jsonl", "a11y.jsonl", "html.jsonl", "html_element.jsonl")


def _read_jsonl(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_jsonl(path: str, rows: list) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, path)


def redact_recording_inputs(recording_path: str) -> Counter:
    """
    Redact raw recording files in place (before actions, timeline and the
    manifest are derived from them) and record the counts in metadata.json.
    """
    from .url_privacy import sanitize_url

    counts = Counter()

    def path(name: str) -> str:
        return os.path.join(recording_path, name)

    if os.path.exists(path("events.jsonl")):
        _write_jsonl(path("events.jsonl"), redact_keystrokes(_read_jsonl(path("events.jsonl")), counts))

    if os.path.exists(path("top_window.jsonl")):
        windows = _read_jsonl(path("top_window.jsonl"))
        for w in windows:
            if w.get("url"):
                w["url"] = sanitize_url(w["url"])
        _write_jsonl(path("top_window.jsonl"), [redact_tree(w, counts) for w in windows])

    for name in TREE_FILES:
        if os.path.exists(path(name)):
            _write_jsonl(path(name), [redact_tree(row, counts) for row in _read_jsonl(path(name))])

    if os.path.exists(path("task_name.json")):
        with open(path("task_name.json"), "r", encoding="utf-8") as f:
            task = json.load(f)
        _write_json(path("task_name.json"), redact_tree(task, counts))

    _record_privacy(recording_path, counts)
    return counts


def redact_recording_outputs(recording_path: str) -> Counter:
    """Redact derived files (actions, event buffer) — used for older recordings."""
    counts = Counter()
    for name in ("reduced_events_complete.jsonl", "reduced_events_vis.jsonl", "event_buffer.jsonl"):
        file_path = os.path.join(recording_path, name)
        if os.path.exists(file_path):
            _write_jsonl(file_path, [redact_tree(row, counts) for row in _read_jsonl(file_path)])
    _record_privacy(recording_path, counts)
    return counts


def _record_privacy(recording_path: str, counts: Counter) -> None:
    metadata_path = os.path.join(recording_path, "metadata.json")
    if not os.path.exists(metadata_path):
        return
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    privacy = metadata.get("privacy") or {}
    totals = Counter(privacy.get("redactions") or {})
    totals.update(counts)
    metadata["privacy"] = {
        "version": PRIVACY_VERSION,
        "redactions": dict(totals),
        "video_redacted": False,
    }
    _write_json(metadata_path, metadata)
    if counts:
        logger.info(f"privacy: redacted {dict(counts)} in {os.path.basename(recording_path)}")


def privacy_version(recording_path: str) -> int:
    try:
        with open(os.path.join(recording_path, "metadata.json"), "r", encoding="utf-8") as f:
            return int((json.load(f).get("privacy") or {}).get("version", 0))
    except Exception:
        return 0
