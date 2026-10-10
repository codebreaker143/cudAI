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
from cudai_privacy.keystrokes import open_run_start, redact_keystrokes

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
