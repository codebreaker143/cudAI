"""
Server second pass: remove people's names and check the device's redaction.

Recordings arrive in recordings/<id>/ already redacted on the contributor's
computer (text and video, Presidio rules). That copy still contains names,
so it is treated as sensitive: encrypted at rest, read only by this worker,
and deleted CUDAI_RAW_RETENTION_HOURS (default 72) after the clean copy
exists. Nothing trains on or exports from recordings/; exports read clean/.

For each completed recording:
  - Video: every chunk is OCR'd (PaddleOCR on GPU) and names found by
    GLiNER, plus anything the Presidio rules still find, are masked
    (cudai_privacy.video, same code as the app).
  - Text: every text file (keystrokes run by run, window titles, element
    labels, action descriptions, task name, OCR layer) gets the same
    detector.
  - clean/<id>/: the redacted copy, plus
      _qa.json       names removed, and "device misses": values the device
                     rules should have caught (target: zero)
      _timings.json  seconds per step (download, OCR, names, mask, encode,
                     upload)
      _clean.json    completion time, per-part encoder, raw deletion time

Run: python -m cudai_ingest.worker [--once]
Env (besides the storage settings in app.py):
  CUDAI_NAME_MODEL          GLiNER model (default urchade/gliner_multi_pii-v1)
  CUDAI_NAME_THRESHOLD      default 0.5
  CUDAI_DEVICE              gpu (default) or cpu
  CUDAI_RAW_RETENTION_HOURS default 72
  CUDAI_FFMPEG              ffmpeg binary (default: ffmpeg on PATH)
"""

import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from cudai_privacy import find_spans, redact_tree
from cudai_privacy.keystrokes import redact_keystrokes
from cudai_privacy.video import Settings, redact_video

RAW, CLEAN = "recordings", "clean"
JSONL_FILES = (
    "events.jsonl", "timeline.jsonl", "top_window.jsonl", "element.jsonl",
    "a11y.jsonl", "reduced_events_complete.jsonl", "reduced_events_vis.jsonl",
)
JSON_FILES = ("task_name.json", "metadata.json", "manifest.json")
COPY_FILES = ("redaction_summary.json", "pipeline_timings.jsonl")
SERVER_ENCODER_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                       "-profile:v", "high", "-g", "60", "-pix_fmt", "yuv420p"]
# The GPU makes OCR cheap: look at the screen more often than the device does.
SERVER_SETTINGS = Settings(min_ocr_interval=5, analysis_max_side=2000)


# Detectors ---------------------------------------------------------------------

class NameDetector:
    """Person names with GLiNER (multilingual, handles Indian names)."""

    def __init__(self, model: str | None = None, threshold: float | None = None, device: str | None = None):
        from gliner import GLiNER

        self.model = GLiNER.from_pretrained(model or os.environ.get("CUDAI_NAME_MODEL", "urchade/gliner_multi_pii-v1"))
        if (device or os.environ.get("CUDAI_DEVICE", "gpu")) == "gpu":
            self.model = self.model.to("cuda")
        self.threshold = threshold or float(os.environ.get("CUDAI_NAME_THRESHOLD", "0.5"))
        self.name = f"GLiNER {model or os.environ.get('CUDAI_NAME_MODEL', 'urchade/gliner_multi_pii-v1')}"

    def __call__(self, text: str) -> list:
        return [(e["start"], e["end"], "PERSON")
                for e in self.model.predict_entities(text, ["person"], threshold=self.threshold)]


class PaddleOcr:
    """PaddleOCR (PP-OCRv5 server models) with PaddlePaddle, on GPU."""

    def __init__(self, device: str | None = None):
        from paddleocr import PaddleOCR

        self.engine = PaddleOCR(
            text_detection_model_name="PP-OCRv5_server_det",
            text_recognition_model_name="PP-OCRv5_server_rec",
            use_doc_orientation_classify=False, use_doc_unwarping=False,
            use_textline_orientation=False, device=device or os.environ.get("CUDAI_DEVICE", "gpu"),
        )
        self.name = "PaddleOCR PP-OCRv5 server"

    def __call__(self, image) -> list:
        result = self.engine.predict(image)[0]
        return [((b[0], b[1], b[2], b[3]), t, s)
                for b, t, s in zip(result["rec_boxes"], result["rec_texts"], result["rec_scores"])]


def make_finder(names, misses: Counter, found: Counter):
    """
    Detector for the second pass: the Presidio rules first (anything they
    find is a device miss, since the device ran them already), then names.
    """
    @lru_cache(maxsize=65536)
    def find(text: str) -> tuple:
        spans = list(find_spans(text))
        for _, _, entity in spans:
            misses[entity] += 1
        for start, end, entity in names(text) if text.strip() else []:
            if not any(start < e and s < end for s, e, _ in spans):
                spans.append((start, end, entity))
                found[entity] += 1
        return tuple(sorted(spans))

    return lambda text: list(find(text))


# Text files ------------------------------------------------------------------------

def _redact_rows(name: str, rows: list, find) -> list:
    if name in ("events.jsonl", "timeline.jsonl"):
        # Keystrokes are redacted run by run (timeline rows call it "type").
        renamed = name == "timeline.jsonl"
        if renamed:
            for row in rows:
                row["action"] = row.get("type")
        redact_keystrokes(rows, find=find)
        if renamed:
            for row in rows:
                row.pop("action", None)
    return [redact_tree(row, find=find) for row in rows]


def _redact_file(src: str, dst: str, name: str, find) -> None:
    with open(src, "r", encoding="utf-8") as f:
        if name.endswith(".jsonl"):
            rows = [json.loads(line) for line in f if line.strip()]
            out = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in _redact_rows(name, rows, find))
        else:
            out = json.dumps(redact_tree(json.load(f), find=find), ensure_ascii=False, indent=2)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(out)


# One recording ---------------------------------------------------------------------

def _parts(metadata: dict) -> list:
    videos = [d.get("video") for d in metadata.get("displays") or []] or [metadata.get("video")]
    parts = []
    for video in videos:
        for part in (video or {}).get("parts") or []:
            if part not in parts:
                parts.append(part)
    return parts


def process_recording(storage, recording_id: str, ocr, names, ffmpeg: str = "ffmpeg",
                      encoder_args: list | None = None, settings: Settings | None = None) -> dict:
    """Write clean/<id>/ for one completed recording; returns the QA record."""
    raw, clean = f"{RAW}/{recording_id}/", f"{CLEAN}/{recording_id}/"
    timings, misses, found = Counter(), Counter(), Counter()
    find = make_finder(names, misses, found)
    video_masks = Counter()
    encoders = {}
    with tempfile.TemporaryDirectory() as work:
        def local(name):
            path = os.path.join(work, "in", name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            return path

        metadata = storage.read_json(raw + "metadata.json") or {}
        for part in _parts(metadata):
            t = time.perf_counter()
            src = local(part)
            storage.download(raw + part, src)
            timings["download"] += time.perf_counter() - t
            if "/gap_" in part:
                storage.upload_file(clean + part, src)
                encoders[part] = "device"
                continue
            dst = src[: -len(".mp4")] + ".clean.mp4"
            result = redact_video(
                src, dst, ocr, ffmpeg, encoder_args or SERVER_ENCODER_ARGS, settings=settings or SERVER_SETTINGS,
                on_timing=lambda stage, seconds, **_: timings.__setitem__(stage, timings[stage] + seconds),
                find=find,
            )
            video_masks.update(result["entities"])
            t = time.perf_counter()
            storage.upload_file(clean + part, dst if result["masked"] else src)
            encoders[part] = "server" if result["masked"] else "device"
            layer = local(f"ocr/{part}.jsonl")
            with open(layer, "w", encoding="utf-8") as f:
                f.writelines(json.dumps(row, ensure_ascii=False) + "\n" for row in result["layer"])
            storage.upload_file(clean + f"ocr/{part}.jsonl", layer)
            timings["upload"] += time.perf_counter() - t

        t = time.perf_counter()
        text_found_before = sum(found.values())
        for name in JSONL_FILES + JSON_FILES:
            if storage.sha256(raw + name) is None:
                continue
            src, dst = local(name), local(name + ".clean")
            storage.download(raw + name, src)
            _redact_file(src, dst, name, find)
            storage.upload_file(clean + name, dst)
        for name in COPY_FILES:
            if storage.sha256(raw + name) is not None:
                src = local(name)
                storage.download(raw + name, src)
                storage.upload_file(clean + name, src)
        timings["text"] += time.perf_counter() - t

    qa = {
        "recording_id": recording_id,
        "names_model": getattr(names, "name", type(names).__name__),
        "ocr": getattr(ocr, "name", type(ocr).__name__),
        "names_masked_in_video": video_masks.get("PERSON", 0),
        "names_redacted_in_text": sum(found.values()) - text_found_before,
        "video_masks": dict(video_masks),
        # Distinct values the on-device Presidio rules should already have
        # removed (target: none).
        "device_misses": dict(misses),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    storage.write_json(clean + "_qa.json", qa)
    storage.write_json(clean + "_timings.json", {k: round(v, 3) for k, v in timings.items()})
    storage.write_json(clean + "_clean.json", {
        "completed_at": qa["processed_at"],
        "encoders": encoders,
        "raw_deleted_at": None,
    })
    return qa


def apply_retention(storage, hours: float) -> list:
    """Delete raw uploads whose clean copy is older than `hours`."""
    deleted = []
    now = datetime.now(timezone.utc)
    for recording_id in storage.list_ids(CLEAN):
        info = storage.read_json(f"{CLEAN}/{recording_id}/_clean.json")
        if not info or info.get("raw_deleted_at"):
            continue
        if now - datetime.fromisoformat(info["completed_at"]) < timedelta(hours=hours):
            continue
        storage.delete_prefix(f"{RAW}/{recording_id}")
        info["raw_deleted_at"] = now.isoformat()
        storage.write_json(f"{CLEAN}/{recording_id}/_clean.json", info)
        deleted.append(recording_id)
    return deleted


def pending(storage) -> list:
    done = set(storage.list_ids(CLEAN))
    return [
        rid for rid in storage.list_ids(RAW)
        if rid not in done and (storage.read_json(f"{RAW}/{rid}/_recording.json") or {}).get("status") == "complete"
    ]


def main() -> None:
    from .app import config_from_env
    from .storage import storage_from_config

    storage = storage_from_config(config_from_env())
    ocr, names = PaddleOcr(), NameDetector()
    ffmpeg = os.environ.get("CUDAI_FFMPEG", "ffmpeg")
    hours = float(os.environ.get("CUDAI_RAW_RETENTION_HOURS", "72"))
    while True:
        for recording_id in pending(storage):
            try:
                qa = process_recording(storage, recording_id, ocr, names, ffmpeg)
                print(f"{recording_id}: {qa['names_masked_in_video']} names masked in video, "
                      f"device misses {qa['device_misses']}", flush=True)
            except Exception as e:  # keep going with the others
                print(f"{recording_id}: failed: {e}", file=sys.stderr, flush=True)
        for recording_id in apply_retention(storage, hours):
            print(f"{recording_id}: raw upload deleted", flush=True)
        if "--once" in sys.argv:
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
