"""
How long every step of the pipeline takes, per recording.

From capture, through each on-device tool (decode, change detection, OCR,
Presidio, masking, encode), to the upload, every step appends one line to
<recording>/pipeline_timings.jsonl:

    {"stage": "ocr", "chunk": "chunks/display_0/segment_000/chunk_00003.mp4",
     "start_unix": ..., "end_unix": ..., "seconds": 1.82, ...extra}

Writes are single O_APPEND writes, so the backend and the redaction worker
process can both log to the same file. summary() gives per-stage statistics
and how far behind live each chunk reached the cloud ("lag").
"""

import json
import math
import os
import threading
import time
from contextlib import contextmanager

TIMINGS_FILE = "pipeline_timings.jsonl"
_lock = threading.Lock()


def perf_to_unix(perf: float) -> float:
    """Wall-clock time of a time.perf_counter() reading (same boot session)."""
    return time.time() - (time.perf_counter() - perf)


def record(recording_path: str, stage: str, start_unix: float, end_unix: float,
           chunk: str | None = None, **extra) -> None:
    row = {
        "stage": stage,
        "chunk": chunk,
        "start_unix": round(start_unix, 4),
        "end_unix": round(end_unix, 4),
        "seconds": round(end_unix - start_unix, 4),
        **extra,
    }
    data = (json.dumps(row) + "\n").encode()
    try:
        with _lock:
            fd = os.open(os.path.join(recording_path, TIMINGS_FILE),
                         os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
    except OSError:
        pass  # timing must never break recording


@contextmanager
def stage(recording_path: str, name: str, chunk: str | None = None, **extra):
    """Time a block; fields added to the yielded dict are logged with it."""
    info = dict(extra)
    start = time.time()
    try:
        yield info
    finally:
        record(recording_path, name, start, time.time(), chunk, **info)


def load(recording_path: str) -> list:
    path = os.path.join(recording_path, TIMINGS_FILE)
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return rows


def _stats(values: list) -> dict:
    values = sorted(values)
    if not values:
        return {"count": 0}

    def pct(p):
        return values[min(len(values) - 1, max(0, math.ceil(p * len(values)) - 1))]

    return {
        "count": len(values),
        "total": round(sum(values), 3),
        "p50": round(pct(0.5), 3),
        "p95": round(pct(0.95), 3),
        "max": round(values[-1], 3),
    }


def summary(recording_path: str) -> dict:
    """Per-stage seconds (count, total, p50, p95, max) and per-chunk lag."""
    rows = load(recording_path)
    by_stage = {}
    for row in rows:
        by_stage.setdefault(row["stage"], []).append(row["seconds"])
    lags = [row["lag_seconds"] for row in rows if row["stage"] == "chunk_uploaded" and "lag_seconds" in row]
    return {
        "stages": {name: _stats(values) for name, values in sorted(by_stage.items())},
        "chunk_lag": _stats(lags),
    }
