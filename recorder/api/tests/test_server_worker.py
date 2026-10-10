"""
Server second pass (names, device-miss check, clean/ copy, retention, QA).

GLiNER and GPU PaddleOCR are replaced by a stub name detector and the app's
CPU OCR, so the pipeline itself runs here.
"""

import json
import os
import re
import sys

import pytest

pytest.importorskip("rapidocr")
cv2 = pytest.importorskip("cv2")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "server")))
from cudai_ingest import qa, worker  # noqa: E402
from cudai_ingest.storage import LocalStorage  # noqa: E402
from core.utils import get_ffmpeg_path, h264_encoder_args  # noqa: E402
from tests.test_video_redaction import frames_of, make_chunk  # noqa: E402

pytestmark = pytest.mark.skipif(not os.path.exists(get_ffmpeg_path()), reason="bundled ffmpeg not present")

RID = "2f1d3c4b-5a69-4788-9abc-def012345678"
PART = "chunks/display_0/segment_000/chunk_00000.mp4"


class StubNames:
    name = "stub"

    def __call__(self, text):
        return [(m.start(), m.end(), "PERSON") for m in re.finditer(r"Ravi Kumar", text)]


@pytest.fixture(scope="module")
def ocr():
    from core.redaction import RapidOcr

    return RapidOcr()


def keys(text, t0):
    rows = []
    for i, ch in enumerate(text):
        rows.append({"time_stamp": t0 + i * 0.1, "action": "press", "name": ch, "char": ch, "text": ch})
        rows.append({"time_stamp": t0 + i * 0.1 + 0.05, "action": "release", "name": ch, "char": ch, "text": None})
    return rows


def upload_raw(storage, tmp_path, events):
    chunk = tmp_path / "chunk.mp4"
    make_chunk(chunk, lambda n: [("Approver Ravi Kumar", 150), ("Invoice 5105600012", 250)])
    storage.upload_file(f"recordings/{RID}/{PART}", str(chunk))
    video = {"file": "video.mp4", "fps": 30, "parts": [PART]}
    storage.write_json(f"recordings/{RID}/metadata.json", {"video": video, "displays": [{"index": 0, "video": video}]})
    storage.write_json(f"recordings/{RID}/task_name.json", {"task_name": "Approve invoice for Ravi Kumar"})
    storage.put(f"recordings/{RID}/events.jsonl",
                "".join(json.dumps(e) + "\n" for e in events).encode())
    storage.write_json(f"recordings/{RID}/_recording.json", {"status": "complete"})


def test_names_removed_into_clean_copy_and_raw_deleted(tmp_path, ocr):
    storage = LocalStorage(str(tmp_path / "store"), b"k" * 32)
    upload_raw(storage, tmp_path, keys("Ravi Kumar", 100.0))
    assert worker.pending(storage) == [RID]

    result = worker.process_recording(storage, RID, ocr, StubNames(), get_ffmpeg_path(),
                                      encoder_args=h264_encoder_args())
    assert result["names_masked_in_video"] >= 1
    assert result["device_misses"] == {}
    assert worker.pending(storage) == []

    # Video: the name is covered, the invoice number is not.
    texts = [t for _, t, _ in ocr(frames_of(storage.path(f"clean/{RID}/{PART}"))[45])]
    assert not any("Ravi" in t for t in texts), texts
    assert any("5105600012" in t for t in texts), texts
    # Text: task name and keystrokes.
    assert storage.read_json(f"clean/{RID}/task_name.json")["task_name"] == "Approve invoice for [PERSON]"
    events = open(storage.path(f"clean/{RID}/events.jsonl")).read()
    assert "[PERSON]" in events and '"R"' not in events
    layer = open(storage.path(f"clean/{RID}/ocr/{PART}.jsonl")).read()
    assert "Ravi" not in layer and "[PERSON]" in layer
    timings = storage.read_json(f"clean/{RID}/_timings.json")
    assert {"download", "ocr", "presidio", "mask", "encode", "upload", "text"} <= set(timings)

    # Raw upload kept until the retention period has passed.
    assert worker.apply_retention(storage, hours=72) == []
    assert storage.sha256(f"recordings/{RID}/{PART}")
    assert worker.apply_retention(storage, hours=0) == [RID]
    assert storage.sha256(f"recordings/{RID}/{PART}") is None
    assert storage.read_json(f"clean/{RID}/_clean.json")["raw_deleted_at"]


def test_values_the_device_missed_are_counted_and_removed(tmp_path, ocr):
    storage = LocalStorage(str(tmp_path / "store"), b"k" * 32)
    upload_raw(storage, tmp_path, keys("ravi@acme.com", 100.0))
    result = worker.process_recording(storage, RID, ocr, StubNames(), get_ffmpeg_path(),
                                      encoder_args=h264_encoder_args())
    assert result["device_misses"] == {"EMAIL_ADDRESS": 1}
    assert "[EMAIL_ADDRESS]" in open(storage.path(f"clean/{RID}/events.jsonl")).read()


def test_qa_sample_and_report(tmp_path, ocr):
    storage = LocalStorage(str(tmp_path / "store"), b"k" * 32)
    upload_raw(storage, tmp_path, [])
    worker.process_recording(storage, RID, ocr, StubNames(), get_ffmpeg_path(), encoder_args=h264_encoder_args())
    csv_path = qa.sample(storage, 3, str(tmp_path / "review"), seed=1)
    lines = open(csv_path).read().splitlines()
    assert len(lines) == 4 and all(os.path.exists(tmp_path / "review" / ln.split(",")[3]) for ln in lines[1:])
    # A reviewer marks one of three frames as still showing a name.
    filled = [lines[0]] + [ln.replace(",,", ",1,", 1) if i == 0 else ln.replace(",,", ",0,", 1)
                           for i, ln in enumerate(lines[1:])]
    open(csv_path, "w").write("\n".join(filled) + "\n")
    assert qa.report(csv_path) == {"reviewed_frames": 3, "frames_with_names": 1, "miss_rate": 0.3333}
