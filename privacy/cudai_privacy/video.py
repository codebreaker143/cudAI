"""
Mask sensitive text in screen video. Shared by the desktop app (before
upload) and the ingest server (second pass), with different OCR engines.

redact_video(src, dst, ocr, ...) works on one video chunk:

1. Analysis pass: frames are decoded at analysis resolution. OpenCV change
   detection on small thumbnails decides when to OCR: the first frame, then
   whenever the picture differs from the last OCR'd frame (at most once per
   `min_ocr_interval` frames). A local change (typing, a popup) is OCR'd as a
   crop; text elsewhere is kept from earlier.
2. Every OCR'd line is checked with the Presidio rules (engine.find_spans);
   sensitive spans become boxes over that part of the line.
3. Masks are conservative in time: boxes found at OCR k cover every frame
   from the first frame that changed after OCR k-1 until OCR k+1.
4. Masking pass (only if anything was found): full-resolution frames get
   solid filled rectangles with OpenCV (not blur, which can be reversed on
   text) and are re-encoded with the caller's encoder settings. Otherwise
   the chunk is left untouched.

It also returns the OCR content layer: per OCR'd frame, every text line (with
sensitive values replaced) and the masked boxes.

`ocr(image_bgr)` returns [((x0, y0, x1, y1), text, score), ...].
"""

import re
import subprocess
import time
from collections import Counter
from dataclasses import dataclass

import cv2
import numpy as np

from .engine import find_spans, replace_spans


@dataclass
class Settings:
    analysis_max_side: int = 1600  # OCR resolution (longest side, pixels)
    thumb_scale: float = 1 / 8  # change detection resolution
    change_threshold: int = 12  # grey-level difference that counts as change
    min_changed_fraction: float = 0.0005  # of the thumbnail; below = no change
    full_ocr_fraction: float = 0.35  # changed area above which the whole frame is OCR'd
    max_regions: int = 4  # more changed regions than this: one bounding region
    min_ocr_interval: int = 15  # frames between OCRs (30 fps: 2 per second)
    region_pad: int = 24  # analysis pixels around a changed region
    box_pad: int = 3  # analysis pixels around masked text


SIZE_RE = re.compile(r"Video: \w+.*?, (\d{2,5})x(\d{2,5})")


def probe_size(ffmpeg: str, path: str) -> tuple:
    stderr = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    match = SIZE_RE.search(stderr)
    if not match:
        raise RuntimeError(f"cannot read video size of {path}")
    return int(match.group(1)), int(match.group(2))


def _frames(ffmpeg: str, path: str, width: int, height: int, pix_fmt: str, scale: tuple | None = None):
    """Decoded frames as numpy arrays (bgr24: HxWx3; yuv420p: flat Y, U, V planes)."""
    out_w, out_h = scale or (width, height)
    args = [ffmpeg, "-v", "error", "-i", path]
    if scale:
        args += ["-vf", f"scale={out_w}:{out_h}:flags=area"]
    args += ["-f", "rawvideo", "-pix_fmt", pix_fmt, "pipe:1"]
    if pix_fmt == "bgr24":
        shape, size = (out_h, out_w, 3), out_w * out_h * 3
    else:
        size = out_w * out_h + 2 * (out_w // 2) * (out_h // 2)
        shape = (size,)
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(shape)
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"decoding {path} failed: {err[-300:]}")


def _intersects(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def group_rows(found: list) -> list:
    """
    Join OCR boxes on the same row into lines ("4111" "1111" ... -> one card
    number), so values split into words are still detected. Returns dicts
    with box, text, score and words [(box, text, start offset in text)].
    """
    rows = []
    for box, text, score in sorted(found, key=lambda f: (f[0][1], f[0][0])):
        if not text.strip():
            continue
        height = box[3] - box[1]
        for row in rows:
            rb = row["box"]
            overlap = min(rb[3], box[3]) - max(rb[1], box[1])
            gap = box[0] - row["words"][-1][0][2]
            if overlap > 0.5 * min(height, rb[3] - rb[1]) and -height < gap < 1.5 * height:
                row["words"].append((box, text))
                row["box"] = (min(rb[0], box[0]), min(rb[1], box[1]), max(rb[2], box[2]), max(rb[3], box[3]))
                row["scores"].append(score)
                break
        else:
            rows.append({"box": tuple(box), "words": [(box, text)], "scores": [score]})
    lines = []
    for row in rows:
        words, offset, text = [], 0, ""
        for box, word in sorted(row["words"], key=lambda w: w[0][0]):
            if text:
                text += " "
                offset += 1
            words.append((tuple(int(v) for v in box), word, offset))
            text += word
            offset += len(word)
        lines.append({"box": tuple(int(v) for v in row["box"]), "text": text,
                      "score": float(min(row["scores"])), "words": words})
    return lines


def span_boxes(line: dict, spans: list, pad: int) -> list:
    """Boxes covering each character span, using the words it touches."""
    boxes = []
    for start, end, entity in spans:
        parts = []
        for (x0, y0, x1, y1), word, offset in line["words"]:
            w_start, w_end = offset, offset + len(word)
            if w_end <= start or end <= w_start:
                continue
            char_w = (x1 - x0) / max(len(word), 1)
            # Partly covered word: the covered characters, plus one each side.
            bx0 = x0 + char_w * max(0, start - w_start - 1)
            bx1 = x1 - char_w * max(0, w_end - end - 1)
            parts.append((bx0, y0, bx1, y1))
        if parts:
            boxes.append(((min(p[0] for p in parts) - pad, min(p[1] for p in parts) - pad,
                           max(p[2] for p in parts) + pad, max(p[3] for p in parts) + pad), entity))
    return boxes


def _changed_regions(thumb, last_thumb, settings: Settings, scale: float, size: tuple):
    """None (no change), "full", or a list of analysis-pixel rectangles."""
    changed = cv2.absdiff(thumb, last_thumb) > settings.change_threshold
    fraction = float(changed.mean())
    if fraction < settings.min_changed_fraction:
        return None
    if fraction > settings.full_ocr_fraction:
        return "full"
    mask = cv2.dilate(changed.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects = [cv2.boundingRect(c) for c in contours]
    if len(rects) > settings.max_regions:
        xs = [r[0] for r in rects] + [r[0] + r[2] for r in rects]
        ys = [r[1] for r in rects] + [r[1] + r[3] for r in rects]
        rects = [(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))]
    width, height = size
    pad = settings.region_pad
    regions = []
    for x, y, w, h in rects:
        regions.append((
            max(0, int(x / scale) - pad), max(0, int(y / scale) - pad),
            min(width, int((x + w) / scale) + pad), min(height, int((y + h) / scale) + pad),
        ))
    return regions


def redact_video(
    src: str,
    dst: str,
    ocr,
    ffmpeg: str,
    encoder_args: list,
    fps: int = 30,
    settings: Settings | None = None,
    on_timing=None,
    find=find_spans,
) -> dict:
    """
    Mask sensitive text in `src`. Writes `dst` only if something was masked.
    Returns {"masked", "frames", "ocr_frames", "entities", "layer": [...]}.
    `on_timing(stage, seconds, **extra)` receives per-step durations; `find`
    is the text detector (Presidio rules by default).
    """
    settings = settings or Settings()
    timing = Counter()
    width, height = probe_size(ffmpeg, src)
    factor = max(1.0, max(width, height) / settings.analysis_max_side)
    aw, ah = int(width / factor) // 2 * 2, int(height / factor) // 2 * 2
    sx, sy = width / aw, height / ah

    lines = []  # current text on screen: dicts with box, text, spans
    events = []  # OCR results: frame, lines (copy), pii boxes, region
    last_thumb, last_ocr_frame, last_frame, first_change = None, None, None, None
    frame_count, ocr_regions = 0, 0
    pass_start = time.perf_counter()

    def run_ocr(frame, n, region, since):
        nonlocal lines, ocr_regions
        t = time.perf_counter()
        if region == "full":
            found = ocr(frame)
            lines = []
            crops = [((0, 0, aw, ah), found)]
        else:
            crops = []
            for rx0, ry0, rx1, ry1 in region:
                found = ocr(np.ascontiguousarray(frame[ry0:ry1, rx0:rx1]))
                crops.append(((rx0, ry0, rx1, ry1), [
                    ((b[0] + rx0, b[1] + ry0, b[2] + rx0, b[3] + ry0), text, score)
                    for b, text, score in found
                ]))
            lines = [ln for ln in lines if not any(_intersects(ln["box"], c[0]) for c in crops)]
        timing["ocr"] += time.perf_counter() - t
        ocr_regions += len(crops)
        t = time.perf_counter()
        for _, found in crops:
            for line in group_rows(found):
                line["spans"] = find(line["text"])
                lines.append(line)
        timing["presidio"] += time.perf_counter() - t
        pii = [b for ln in lines if ln["spans"] for b in span_boxes(ln, ln["spans"], settings.box_pad)]
        events.append({"frame": n, "since": since, "region": region, "lines": list(lines), "pii": pii})

    for n, frame in enumerate(_frames(ffmpeg, src, width, height, "bgr24", (aw, ah))):
        frame_count, last_frame = n + 1, frame
        t = time.perf_counter()
        thumb = cv2.cvtColor(
            cv2.resize(frame, None, fx=settings.thumb_scale, fy=settings.thumb_scale, interpolation=cv2.INTER_AREA),
            cv2.COLOR_BGR2GRAY,
        )
        if last_thumb is None:
            region = "full"
        else:
            region = _changed_regions(thumb, last_thumb, settings, settings.thumb_scale, (aw, ah))
        timing["change_detection"] += time.perf_counter() - t
        if region is not None and first_change is None:
            first_change = n
        if region is not None and (last_ocr_frame is None or n - last_ocr_frame >= settings.min_ocr_interval):
            run_ocr(frame, n, region, first_change)
            last_thumb, last_ocr_frame, first_change = thumb, n, None
    # The end of the chunk differs from the last OCR'd frame: OCR it too.
    if last_frame is not None and last_ocr_frame != frame_count - 1:
        thumb = cv2.cvtColor(cv2.resize(last_frame, None, fx=settings.thumb_scale, fy=settings.thumb_scale,
                                        interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        region = _changed_regions(thumb, last_thumb, settings, settings.thumb_scale, (aw, ah))
        if region is not None:
            run_ocr(last_frame, frame_count - 1, region, first_change if first_change is not None else frame_count - 1)
    timing["decode"] = (time.perf_counter() - pass_start) - sum(timing.values())

    # Frame ranges each OCR's boxes cover (from the previous OCR to the next).
    ranges = []
    for i, event in enumerate(events):
        if event["pii"]:
            start = event["since"] if i > 0 else 0
            end = events[i + 1]["frame"] if i + 1 < len(events) else frame_count
            boxes = [(int(b[0] * sx), int(b[1] * sy), int(np.ceil(b[2] * sx)), int(np.ceil(b[3] * sy)))
                     for b, _ in event["pii"]]
            ranges.append((start, end, boxes))

    entities = Counter(e for event in events for _, e in event["pii"])
    masked = bool(ranges)
    if masked:
        t = time.perf_counter()
        _mask_and_encode(src, dst, ffmpeg, encoder_args, fps, width, height, ranges, timing)
        timing["encode"] = time.perf_counter() - t - timing["mask"]

    layer = [
        {
            "frame": e["frame"],
            "t_chunk": round(e["frame"] / fps, 3),
            "region": e["region"] if e["region"] == "full" else [
                [int(v * s) for v, s in zip(r, (sx, sy, sx, sy))] for r in e["region"]
            ],
            "lines": [
                {"bbox": [int(ln["box"][0] * sx), int(ln["box"][1] * sy), int(ln["box"][2] * sx), int(ln["box"][3] * sy)],
                 "text": replace_spans(ln["text"], ln["spans"]), "score": round(ln["score"], 3)}
                for ln in e["lines"]
            ],
            "masks": [
                {"bbox": [int(b[0] * sx), int(b[1] * sy), int(np.ceil(b[2] * sx)), int(np.ceil(b[3] * sy))], "entity": ent}
                for b, ent in e["pii"]
            ],
        }
        for e in events
    ]
    if on_timing:
        for stage in ("decode", "change_detection", "ocr", "presidio", "mask", "encode"):
            if stage in timing:
                on_timing(stage, timing[stage],
                          **({"ocr_frames": len(events), "ocr_regions": ocr_regions} if stage == "ocr" else {}))
    return {
        "masked": masked,
        "frames": frame_count,
        "ocr_frames": len(events),
        "entities": dict(entities),
        "layer": layer,
        "size": [width, height],
    }


def _mask_and_encode(src, dst, ffmpeg, encoder_args, fps, width, height, ranges, timing):
    encoder = subprocess.Popen(
        [ffmpeg, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "yuv420p", "-s", f"{width}x{height}",
         "-r", str(fps), "-i", "pipe:0", *encoder_args, "-fps_mode", "cfr", "-r", str(fps),
         "-movflags", "+faststart", dst],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        for n, frame in enumerate(_frames(ffmpeg, src, width, height, "yuv420p")):
            boxes = [b for start, end, bs in ranges if start <= n < end for b in bs]
            if boxes:
                t = time.perf_counter()
                frame = frame.copy()
                luma, chroma = width * height, (width // 2) * (height // 2)
                y = frame[:luma].reshape(height, width)
                u = frame[luma:luma + chroma].reshape(height // 2, width // 2)
                v = frame[luma + chroma:].reshape(height // 2, width // 2)
                for x0, y0, x1, y1 in boxes:
                    cv2.rectangle(y, (x0, y0), (x1, y1), 16, thickness=-1)
                    cv2.rectangle(u, (x0 // 2, y0 // 2), (x1 // 2, y1 // 2), 128, thickness=-1)
                    cv2.rectangle(v, (x0 // 2, y0 // 2), (x1 // 2, y1 // 2), 128, thickness=-1)
                timing["mask"] += time.perf_counter() - t
            encoder.stdin.write(frame.tobytes())
    finally:
        encoder.stdin.close()
        err = encoder.stderr.read().decode(errors="replace")
        if encoder.wait() != 0:
            raise RuntimeError(f"encoding {dst} failed: {err[-300:]}")
