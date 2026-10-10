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

`ocr(image_bgr)` returns [((x0, y0, x1, y1), text, score), ...]. An engine
that also has `detect(image) -> [box]` and `recognize([crops]) ->
[(text, score)]` is used incrementally: text boxes are detected in the
changed area, and only boxes that do not match a box already read (same
place, or moved by the measured scroll) are recognised. Recognition is most
of the OCR cost, so typing, scrolling and switching back to a window get
much cheaper.
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
FPS_RE = re.compile(r"Video: .*?, ([\d.]+) fps")


def probe_video(ffmpeg: str, path: str) -> tuple:
    """(width, height, fps) of a video."""
    stderr = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    size, fps = SIZE_RE.search(stderr), FPS_RE.search(stderr)
    if not size:
        raise RuntimeError(f"cannot read video size of {path}")
    return int(size.group(1)), int(size.group(2)), round(float(fps.group(1))) if fps else 30


def probe_size(ffmpeg: str, path: str) -> tuple:
    return probe_video(ffmpeg, path)[:2]


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


class _LineIndex:
    """Text boxes already recognised, findable by position (most recent first)."""

    CELL = 16  # pixels
    LIMIT = 5000

    def __init__(self):
        self.cells = {}  # (x cell, y cell) -> entries
        self.columns = {}  # x cell -> entries, for content that scrolled
        self.count = 0

    def add(self, box, text, score, thumb):
        entry = (box, text, score, thumb)
        kx = int(box[0]) // self.CELL
        self.cells.setdefault((kx, int(box[1]) // self.CELL), []).insert(0, entry)
        self.columns.setdefault(kx, []).insert(0, entry)
        self.count += 1
        if self.count > self.LIMIT:
            self.cells, self.columns, self.count = {}, {}, 0  # start over rather than track ages

    def find(self, box, thumb, shift):
        # Same place (or moved by the measured shift)...
        for dx, dy in {shift, (0, 0)}:
            want = (box[0] - dx, box[1] - dy, box[2] - dx, box[3] - dy)
            kx, ky = int(want[0]) // self.CELL, int(want[1]) // self.CELL
            for cx in (kx - 1, kx, kx + 1):
                for cy in (ky - 1, ky, ky + 1):
                    for entry in self.cells.get((cx, cy), ()):
                        if _iou(want, entry[0]) >= 0.75 and _same_image(thumb, entry[3]):
                            return entry
        # ...or the same line anywhere in its column (scrolled any distance).
        w, h = box[2] - box[0], box[3] - box[1]
        kx = int(box[0]) // self.CELL
        for cx in (kx - 1, kx, kx + 1):
            for entry in self.columns.get(cx, ()):
                eb = entry[0]
                if (abs(eb[0] - box[0]) <= 4 and abs((eb[2] - eb[0]) - w) <= max(4, 0.06 * w)
                        and abs((eb[3] - eb[1]) - h) <= max(3, 0.15 * h) and _same_image(thumb, entry[3])):
                    return entry
        return None


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _box_thumb(gray, box):
    x0, y0, x1, y1 = (int(v) for v in box)
    crop = gray[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)]
    return cv2.resize(crop, (max(4, crop.shape[1] // 2), max(4, crop.shape[0] // 2)), interpolation=cv2.INTER_AREA)


def _same_image(a, b) -> bool:
    """
    Same rendered text? Video compression noise is tolerated, but any cluster
    of strongly changed pixels (one edited character is ~1% of a line) is not,
    so text is never reused for a line whose content changed.
    """
    if a.shape != b.shape:
        a = cv2.resize(a, (b.shape[1], b.shape[0]), interpolation=cv2.INTER_AREA)
    diff = cv2.absdiff(a, b)
    return float(diff.mean()) <= 6.0 and float((diff > 60).mean()) <= 0.003


def _scroll_shift(last_thumb, thumb, region, scale: float) -> tuple:
    """How far the changed content moved (analysis pixels), e.g. a scroll."""
    if region == "full":
        a, b = last_thumb, thumb
    else:
        x0 = int(min(r[0] for r in region) * scale)
        y0 = int(min(r[1] for r in region) * scale)
        x1 = int(max(r[2] for r in region) * scale) + 1
        y1 = int(max(r[3] for r in region) * scale) + 1
        a, b = last_thumb[y0:y1, x0:x1], thumb[y0:y1, x0:x1]
    if a.shape[0] < 8 or a.shape[1] < 8:
        return (0, 0)
    (dx, dy), response = cv2.phaseCorrelate(np.float32(a), np.float32(b))
    if response < 0.2 or (abs(dx) < 0.5 and abs(dy) < 0.5):
        return (0, 0)
    return (round(dx / scale), round(dy / scale))


def _bands(regions: list, width: int) -> list:
    """Full-width horizontal bands covering the regions (overlaps merged)."""
    bands = []
    for _, y0, _, y1 in sorted(regions, key=lambda r: r[1]):
        if bands and y0 <= bands[-1][3]:
            bands[-1] = (0, bands[-1][1], width, max(bands[-1][3], y1))
        else:
            bands.append((0, y0, width, y1))
    return bands


def _covered(box, by) -> bool:
    """Is most (>= 60%) of `box` inside `by`?"""
    ix = max(0.0, min(box[2], by[2]) - max(box[0], by[0]))
    iy = max(0.0, min(box[3], by[3]) - max(box[1], by[1]))
    area = (box[2] - box[0]) * (box[3] - box[1])
    return area > 0 and ix * iy >= 0.6 * area


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
    fps: int | None = None,
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
    width, height, probed_fps = probe_video(ffmpeg, src)
    fps = fps or probed_fps
    factor = max(1.0, max(width, height) / settings.analysis_max_side)
    aw, ah = int(width / factor) // 2 * 2, int(height / factor) // 2 * 2
    sx, sy = width / aw, height / ah

    lines = []  # current text on screen: dicts with box, text, spans
    events = []  # OCR results: frame, lines (copy), pii boxes, region
    seen = _LineIndex()  # boxes already recognised (incremental engines)
    words = []  # OCR boxes on screen now: (box, text, score, thumb)
    incremental = hasattr(ocr, "detect") and hasattr(ocr, "recognize")
    counts = Counter()

    def read_area(frame, gray, rect, shift):
        """OCR boxes inside rect, in frame coordinates."""
        nonlocal words
        x0, y0, x1, y1 = rect
        sub = np.ascontiguousarray(frame[y0:y1, x0:x1])
        if not incremental:
            return [((b[0] + x0, b[1] + y0, b[2] + x0, b[3] + y0), text, score) for b, text, score in ocr(sub)]
        # Text already on screen whose pixels did not change is kept as is.
        inside = [w for w in words if _intersects(w[0], rect)]
        words = [w for w in words if not _intersects(w[0], rect)]
        kept = [w for w in inside if _same_image(_box_thumb(gray, w[0]), w[3])]
        t = time.perf_counter()
        boxes = [(b[0] + x0, b[1] + y0, b[2] + x0, b[3] + y0) for b in ocr.detect(sub)]
        timing["ocr_detect"] += time.perf_counter() - t
        # A detected box mostly covered by kept text is that text, unless it
        # is bigger: then the text grew (typing) and the kept part is stale.
        new_boxes = []
        for b in boxes:
            under = [w for w in kept if _covered(w[0], b) or _covered(b, w[0])]
            if not under:
                new_boxes.append(b)
                continue
            ux0, uy0 = min(w[0][0] for w in under), min(w[0][1] for w in under)
            ux1, uy1 = max(w[0][2] for w in under), max(w[0][3] for w in under)
            if b[0] < ux0 - 3 or b[2] > ux1 + 3 or b[1] < uy0 - 3 or b[3] > uy1 + 3:
                kept = [w for w in kept if w not in under]
                new_boxes.append(b)
        boxes = new_boxes
        found = [(w[0], w[1], w[2]) for w in kept]
        words += kept
        todo = []
        counts["reused"] += len(kept)
        for box in boxes:
            thumb = _box_thumb(gray, box)
            hit = seen.find(box, thumb, shift)
            if hit is not None:
                found.append((box, hit[1], hit[2]))
                words.append((box, hit[1], hit[2], thumb))
                if _iou(box, hit[0]) < 0.95:  # moved (scrolled): remember the new place
                    seen.add(box, hit[1], hit[2], thumb)
            else:
                todo.append((box, thumb))
        counts["reused"] += len(found)
        counts["recognised"] += len(todo)
        if todo:
            t = time.perf_counter()
            crops = [np.ascontiguousarray(frame[int(b[1]):int(b[3]) + 1, int(b[0]):int(b[2]) + 1]) for b, _ in todo]
            for (box, thumb), (text, score) in zip(todo, ocr.recognize(crops)):
                seen.add(box, text, score, thumb)
                if text.strip():
                    found.append((box, text, score))
                    words.append((box, text, score, thumb))
            timing["ocr_recognize"] += time.perf_counter() - t
        return found
    last_thumb, last_ocr_frame, last_frame, first_change = None, None, None, None
    frame_count, ocr_regions = 0, 0
    pass_start = time.perf_counter()

    screen = []  # every OCR box on screen now: (box, text, score)

    def run_ocr(frame, n, region, since, shift=(0, 0)):
        nonlocal lines, ocr_regions, screen
        t = time.perf_counter()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if incremental else None
        # Changed areas are read as full-width bands, so every text line they
        # touch is read whole (a crop around new characters would cut lines).
        rects = [(0, 0, aw, ah)] if region == "full" else _bands(region, aw)
        crops = [(rect, read_area(frame, gray, rect, shift)) for rect in rects]
        screen = [w for w in screen if not any(_intersects(w[0], c[0]) for c in crops)]
        for _, found in crops:
            screen += found
        timing["ocr"] += time.perf_counter() - t
        ocr_regions += len(crops)
        t = time.perf_counter()
        # Lines are rebuilt from all text on screen, so a value whose parts
        # were read in different passes is still checked as one line.
        lines = group_rows(screen)
        for line in lines:
            line["spans"] = find(line["text"])
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
            shift = _scroll_shift(last_thumb, thumb, region, settings.thumb_scale) \
                if incremental and last_thumb is not None else (0, 0)
            run_ocr(frame, n, region, first_change, shift)
            last_thumb, last_ocr_frame, first_change = thumb, n, None
    # The end of the chunk differs from the last OCR'd frame: OCR it too.
    if last_frame is not None and last_ocr_frame != frame_count - 1:
        thumb = cv2.cvtColor(cv2.resize(last_frame, None, fx=settings.thumb_scale, fy=settings.thumb_scale,
                                        interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        region = _changed_regions(thumb, last_thumb, settings, settings.thumb_scale, (aw, ah))
        if region is not None:
            shift = _scroll_shift(last_thumb, thumb, region, settings.thumb_scale) if incremental else (0, 0)
            run_ocr(last_frame, frame_count - 1, region,
                    first_change if first_change is not None else frame_count - 1, shift)
    detail = {k: timing.pop(k) for k in ("ocr_detect", "ocr_recognize") if k in timing}
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
                          **({"ocr_frames": len(events), "ocr_regions": ocr_regions,
                              "lines_recognised": counts["recognised"], "lines_reused": counts["reused"],
                              **{k: round(v, 3) for k, v in detail.items()}}
                             if stage == "ocr" else {}))
    return {
        "masked": masked,
        "frames": frame_count,
        "ocr_frames": len(events),
        "lines_recognised": counts["recognised"],
        "lines_reused": counts["reused"],
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
