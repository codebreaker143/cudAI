"""On-device video redaction with real OCR (PaddleOCR models on ONNX Runtime)."""

import json
import os
import subprocess

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("rapidocr")

from cudai_privacy import find_spans  # noqa: E402
from cudai_privacy.video import redact_video  # noqa: E402
from core.utils import get_ffmpeg_path, h264_encoder_args  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(get_ffmpeg_path()), reason="bundled ffmpeg not present")

W, H, FPS, FRAMES = 1280, 800, 30, 90


@pytest.fixture(scope="module")
def ocr():
    from core.redaction import RapidOcr

    return RapidOcr()


def make_chunk(path, lines_at):
    """lines_at(n) -> [(text, y)] drawn on frame n; encoded like a capture chunk."""
    proc = subprocess.Popen(
        [get_ffmpeg_path(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "pipe:0", *h264_encoder_args(), "-fps_mode", "cfr", "-r", str(FPS), str(path)],
        stdin=subprocess.PIPE,
    )
    for n in range(FRAMES):
        frame = np.full((H, W, 3), 255, np.uint8)
        for text, y in lines_at(n):
            cv2.putText(frame, text, (60, y), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (20, 20, 20), 2, cv2.LINE_AA)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    assert proc.wait() == 0


def frames_of(path):
    cap = cv2.VideoCapture(str(path))
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    return frames


BUSINESS = [("Purchase Order 4500012345", 120), ("Vendor Acme Supplies Total 1,200.50", 200)]
SENSITIVE = [("Contact jane.doe@acme.com", 320), ("Card 4111 1111 1111 1111", 420)]


def test_sensitive_text_is_masked_from_the_frame_it_appears(tmp_path, ocr):
    src, dst = tmp_path / "chunk.mp4", tmp_path / "redacted.mp4"
    make_chunk(src, lambda n: BUSINESS + (SENSITIVE if n >= 40 else []))
    timings = {}
    result = redact_video(str(src), str(dst), ocr, get_ffmpeg_path(), h264_encoder_args(), fps=FPS,
                          on_timing=lambda stage, seconds, **_: timings.__setitem__(stage, seconds))

    assert result["masked"]
    assert set(result["entities"]) == {"EMAIL_ADDRESS", "CREDIT_CARD"}
    out = frames_of(dst)
    assert len(out) == FRAMES
    # No sensitive text left anywhere it was shown; business data intact.
    for n in (40, 41, 60, FRAMES - 1):
        texts = [t for _, t, _ in ocr(out[n])]
        assert not [s for t in texts for s in find_spans(t)], (n, texts)
        assert any("4500012345" in t for t in texts), (n, texts)
    # Before it appeared nothing is masked (re-encoding alone shifts the mean by ~2;
    # a mask over the two lines lowers it by more than 10).
    assert out[10].mean() == pytest.approx(frames_of(src)[10].mean(), abs=4)

    # Content layer: text kept, sensitive values replaced, masks listed.
    layer_text = json.dumps(result["layer"])
    assert "jane.doe" not in layer_text and "4111" not in layer_text
    assert "[EMAIL_ADDRESS]" in layer_text and "4500012345" in layer_text
    assert {"decode", "change_detection", "ocr", "presidio", "mask", "encode"} <= set(timings)


def test_chunk_without_sensitive_text_is_not_reencoded(tmp_path, ocr):
    src, dst = tmp_path / "chunk.mp4", tmp_path / "redacted.mp4"
    make_chunk(src, lambda n: BUSINESS)
    result = redact_video(str(src), str(dst), ocr, get_ffmpeg_path(), h264_encoder_args(), fps=FPS)
    assert not result["masked"] and not dst.exists()
    assert result["ocr_frames"] == 1  # static screen: OCR'd once
    assert any("4500012345" in ln["text"] for ln in result["layer"][0]["lines"])


def test_masked_chunk_still_joins_with_unmasked_chunks(tmp_path, ocr):
    a, b, masked = tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "a_redacted.mp4"
    make_chunk(a, lambda n: SENSITIVE)
    make_chunk(b, lambda n: BUSINESS)
    assert redact_video(str(a), str(masked), ocr, get_ffmpeg_path(), h264_encoder_args(), fps=FPS)["masked"]
    (tmp_path / "list.txt").write_text(f"file '{masked}'\nfile '{b}'\n")
    joined = tmp_path / "joined.mp4"
    subprocess.run([get_ffmpeg_path(), "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(tmp_path / "list.txt"), "-c", "copy", str(joined)], check=True)
    assert len(frames_of(joined)) == 2 * FRAMES
