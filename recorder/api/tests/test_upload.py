"""Live and final upload against the reference ingest server (local storage)."""

import json
import os
import sys
import threading
import time
import uuid

import pytest
from werkzeug.serving import make_server

from core import upload
from core.consent import CLOUD_UPLOAD_CONSENT_VERSION
from core.redaction import REDACTION_VERSION, RedactionManager, meta_path
from core.upload import UploadError, UploadManager, load_state

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "server")))
from cudai_ingest.app import create_app  # noqa: E402

KEY = "test-access-key"


@pytest.fixture
def server(tmp_path):
    app = create_app({"api_keys": [KEY, "other-contributor-key"], "storage": "local", "storage_dir": str(tmp_path / "server"),
                      "signing_key": b"k" * 32, "public_url": None})
    httpd = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{httpd.server_port}"
    yield {"url": url, "storage": app.extensions["cudai_storage"]}
    httpd.shutdown()


@pytest.fixture
def configured(server, monkeypatch):
    monkeypatch.setenv("CUDAI_UPLOAD_URL", server["url"])
    monkeypatch.setenv("CUDAI_UPLOAD_KEY", KEY)
    return server


def write_jsonl(path, rows, mode="w"):
    with open(path, mode, encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def make_recording(root, consent_version=CLOUD_UPLOAD_CONSENT_VERSION, chunks=2):
    rec = root / "recordings" / str(uuid.uuid4())
    chunk_dir = rec / "chunks" / "display_0" / "segment_000"
    chunk_dir.mkdir(parents=True)
    parts = []
    for i in range(chunks):
        (chunk_dir / f"chunk_{i:05d}.mp4").write_bytes(os.urandom(2000))
        parts.append(f"chunks/display_0/segment_000/chunk_{i:05d}.mp4")
    video = {"file": "video.mp4", "parts": parts}
    (rec / "metadata.json").write_text(json.dumps({
        "consent": {"accepted": True, "version": consent_version},
        "start_time": "2026-10-10T10:00:00+05:30",
        "video": video,
        "displays": [{"index": 0, "video": video}],
    }))
    (rec / "events.jsonl").write_text("")
    return rec


class FakeCapture:
    def __init__(self, rec, parts):
        self.rec, self.parts = rec, parts

    def ready_chunks(self):
        return [{"path": p, "file": str(self.rec / p)} for p in self.parts]


def mark_redacted(rec, part, masked_bytes=None):
    """What the redaction worker leaves behind for a chunk."""
    meta = {"version": REDACTION_VERSION, "file": part, "ocr": f"ocr/{part}.jsonl", "masked": False}
    if masked_bytes is not None:
        (rec / "redacted" / part).parent.mkdir(parents=True, exist_ok=True)
        (rec / "redacted" / part).write_bytes(masked_bytes)
        meta.update(file=f"redacted/{part}", masked=True)
    (rec / "ocr" / part).parent.mkdir(parents=True, exist_ok=True)
    (rec / "ocr" / f"{part}.jsonl").write_text('{"frame": 0, "lines": []}\n')
    path = meta_path(str(rec), part)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(meta, f)


def redact_all(rec):
    for part in json.loads((rec / "metadata.json").read_text())["video"]["parts"]:
        mark_redacted(rec, part)


def finish(rec):
    for name in ("reduced_events_vis.jsonl", "reduced_events_complete.jsonl", "timeline.jsonl"):
        (rec / name).write_text('{"a": 1}\n')
    (rec / "manifest.json").write_text("{}")
    (rec / "task_name.json").write_text('{"task_name": "Create PO", "description": ""}')


def remote(server, rec, path):
    return server["storage"].path(f"recordings/{rec.name}/{path}")


def keys(text, t0, start=0):
    rows = []
    for i, ch in enumerate(text):
        t = t0 + i * 0.1
        rows.append({"time_stamp": t, "action": "press", "name": ch, "char": ch, "text": ch, "event_idx": start + 2 * i})
        rows.append({"time_stamp": t + 0.05, "action": "release", "name": ch, "char": ch, "text": None})
    return rows


def test_live_chunks_and_redacted_events_then_complete(tmp_path, configured):
    rec = make_recording(tmp_path)
    parts = json.loads((rec / "metadata.json").read_text())["video"]["parts"]
    manager = UploadManager(recordings_dir=str(rec.parent))
    manager.LIVE_LOG_INTERVAL = 0
    manager.set_live(str(rec), FakeCapture(rec, parts[:1]))
    mark_redacted(rec, parts[0])

    # The contributor is typing an email address right now: held back.
    now = time.perf_counter()
    write_jsonl(rec / "events.jsonl", keys("mail jane@ac", now - 1.5))
    manager.tick()
    assert os.path.exists(remote(configured, rec, parts[0]))
    assert not os.path.exists(remote(configured, rec, parts[1]))  # not closed yet
    assert load_state(str(rec))["live"].get("events.jsonl", {}).get("offset", 0) == 0
    assert not os.path.exists(remote(configured, rec, "live/events/000001.jsonl"))

    # They finish typing and click: the whole run is redacted and uploaded.
    write_jsonl(rec / "events.jsonl", keys("me.com", now - 0.3), mode="a")
    write_jsonl(rec / "events.jsonl", [{"time_stamp": now, "action": "click", "x": 1, "y": 1,
                                        "button": "left", "pressed": True}], mode="a")
    manager.tick()
    delta = open(remote(configured, rec, "live/events/000001.jsonl")).read()
    assert "[EMAIL_ADDRESS]" in delta
    for leaked in ('"jane"', '"j"', "acme"):
        assert leaked not in delta
    texts = "".join(json.loads(l).get("text") or "" for l in delta.splitlines())
    assert texts == "mail [EMAIL_ADDRESS]"

    # Recording stopped and processed: remaining chunk, final files, complete.
    manager.clear_live()
    mark_redacted(rec, parts[1])
    finish(rec)
    manager.recording_processed(str(rec))
    manager.tick()
    record = configured["storage"].read_json(f"recordings/{rec.name}/_recording.json")
    assert record["status"] == "complete"
    assert record["consent_version"] == CLOUD_UPLOAD_CONSENT_VERSION
    assert os.path.exists(remote(configured, rec, parts[1]))
    assert os.path.exists(remote(configured, rec, "manifest.json"))
    assert os.path.exists(remote(configured, rec, f"ocr/{parts[0]}.jsonl"))
    assert not (rec / "chunks").exists()  # local chunks removed after upload
    assert not (rec / "redacted").exists()
    assert upload.recording_upload_status(str(rec))["state"] == "uploaded"


def test_resumes_after_network_failure(tmp_path, server, monkeypatch):
    rec = make_recording(tmp_path)
    finish(rec)
    redact_all(rec)
    monkeypatch.setenv("CUDAI_UPLOAD_KEY", KEY)
    monkeypatch.setenv("CUDAI_UPLOAD_URL", "http://127.0.0.1:9")  # nothing listens
    manager = UploadManager(recordings_dir=str(rec.parent))
    with pytest.raises(UploadError) as error:
        manager.tick()
    assert error.value.retryable
    assert upload.recording_upload_status(str(rec))["state"] == "waiting"

    monkeypatch.setenv("CUDAI_UPLOAD_URL", server["url"])
    manager = UploadManager(recordings_dir=str(rec.parent))  # e.g. after a restart
    manager.tick()
    assert upload.recording_upload_status(str(rec))["state"] == "uploaded"


def test_edits_after_upload_are_sent_again(tmp_path, configured):
    rec = make_recording(tmp_path)
    finish(rec)
    redact_all(rec)
    manager = UploadManager(recordings_dir=str(rec.parent))
    manager.tick()
    (rec / "task_name.json").write_text('{"task_name": "Approve invoice", "description": ""}')
    manager.mark_dirty(str(rec))
    assert upload.recording_upload_status(str(rec))["state"] == "uploading"
    manager.tick()
    assert "Approve invoice" in open(remote(configured, rec, "task_name.json")).read()
    assert upload.recording_upload_status(str(rec))["state"] == "uploaded"


def test_recordings_under_local_only_terms_are_never_uploaded(tmp_path, configured):
    rec = make_recording(tmp_path, consent_version="2026-10-10")
    finish(rec)
    manager = UploadManager(recordings_dir=str(rec.parent))
    manager.tick()
    assert configured["storage"].read_json(f"recordings/{rec.name}/_recording.json") is None
    assert not (rec / "chunks").exists()
    assert upload.recording_upload_status(str(rec))["state"] == "local_only"


def test_not_configured_keeps_everything_local(tmp_path, monkeypatch):
    monkeypatch.delenv("CUDAI_UPLOAD_URL", raising=False)
    monkeypatch.delenv("CUDAI_UPLOAD_KEY", raising=False)
    rec = make_recording(tmp_path)
    finish(rec)
    redact_all(rec)
    manager = UploadManager(recordings_dir=str(rec.parent))
    manager.tick()
    assert manager.status["state"] == "not_configured"
    assert (rec / "chunks").exists()  # kept until upload is configured


def test_wrong_access_key_is_rejected(tmp_path, server, monkeypatch):
    monkeypatch.setenv("CUDAI_UPLOAD_URL", server["url"])
    monkeypatch.setenv("CUDAI_UPLOAD_KEY", "wrong")
    rec = make_recording(tmp_path)
    finish(rec)
    redact_all(rec)
    manager = UploadManager(recordings_dir=str(rec.parent))
    manager.tick()
    status = upload.recording_upload_status(str(rec))
    assert status["state"] == "error" and "401" in status["error"]


def test_server_rejects_bad_paths_and_tampered_content(server):
    import urllib.error
    import urllib.request

    client = upload.UploadClient(server["url"], KEY)
    rid = str(uuid.uuid4())
    client.open_recording(rid, {})
    for bad in ("../etc/passwd", "_recording.json", "/abs"):
        with pytest.raises(UploadError, match="400"):
            client.put_file(rid, bad, b"x", "0" * 64, 1)
    # Declared sha256 does not match the bytes sent.
    ticket = client._api("POST", f"/v1/recordings/{rid}/files", {"path": "a.json", "size": 2, "sha256": "0" * 64})
    request = urllib.request.Request(ticket["url"], data=b"{}", method="PUT")
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)
    assert error.value.code == 400
    # Another contributor's key cannot add to or take over this recording.
    other = upload.UploadClient(server["url"], "other-contributor-key")
    with pytest.raises(UploadError, match="403"):
        other.put_file(rid, "a.json", b"{}", "0" * 64, 2)
    with pytest.raises(UploadError, match="403"):
        other.open_recording(rid, {})


def test_config_requires_https_except_localhost():
    assert upload.validate_server_url("https://ingest.cudai.ai/") == "https://ingest.cudai.ai"
    assert upload.validate_server_url("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    with pytest.raises(ValueError):
        upload.validate_server_url("http://ingest.cudai.ai")


def test_unredacted_chunks_are_never_uploaded(tmp_path, configured):
    rec = make_recording(tmp_path)
    parts = json.loads((rec / "metadata.json").read_text())["video"]["parts"]
    manager = UploadManager(recordings_dir=str(rec.parent))
    manager.set_live(str(rec), FakeCapture(rec, parts))
    manager.tick()
    assert not any(os.path.exists(remote(configured, rec, p)) for p in parts)

    # Finished but still waiting for redaction: not completed, not an error.
    manager.clear_live()
    finish(rec)
    manager.recording_processed(str(rec))
    manager.tick()
    assert upload.recording_upload_status(str(rec))["state"] in ("waiting", "uploading")

    # The masked copy is what reaches the server, under the chunk's path.
    mark_redacted(rec, parts[0], masked_bytes=b"masked video")
    mark_redacted(rec, parts[1])
    manager.tick()
    assert open(remote(configured, rec, parts[0]), "rb").read() == b"masked video"
    assert upload.recording_upload_status(str(rec))["state"] == "uploaded"


def test_chunk_that_cannot_be_redacted_is_not_uploaded(tmp_path, configured):
    rec = make_recording(tmp_path)
    parts = json.loads((rec / "metadata.json").read_text())["video"]["parts"]
    finish(rec)
    mark_redacted(rec, parts[0])
    path = meta_path(str(rec), parts[1])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"version": REDACTION_VERSION, "error": "OCR failed"}, f)
    UploadManager(recordings_dir=str(rec.parent)).tick()
    assert not os.path.exists(remote(configured, rec, parts[1]))
    status = upload.recording_upload_status(str(rec))
    assert status["state"] == "error" and "could not be redacted" in status["error"]


class FakeWorker:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def run(self, recording, part):
        self.calls.append(part)
        if self.fail:
            return {"ok": False, "error": "boom"}
        mark_redacted(__import__("pathlib").Path(recording), part)
        return {"ok": True, "meta": {}}

    def stop(self):
        pass


def test_redaction_manager_does_live_chunks_first_and_logs_timing(tmp_path, configured):
    old = make_recording(tmp_path)  # finished, waiting for redaction
    finish(old)
    live = make_recording(tmp_path)
    live_parts = json.loads((live / "metadata.json").read_text())["video"]["parts"]
    uploads = UploadManager(recordings_dir=str(live.parent))
    uploads.set_live(str(live), FakeCapture(live, live_parts[:1]))
    worker = FakeWorker()
    manager = RedactionManager(uploads, recordings_dir=str(live.parent), worker=worker)
    assert manager.step()
    assert worker.calls == [live_parts[0]]
    while manager.step():
        pass
    assert len(worker.calls) == 3  # then both chunks of the finished recording
    from core import timing
    assert timing.summary(str(live))["stages"]["redaction_queue_wait"]["count"] == 1


def test_redaction_gives_up_after_retries_without_uploading(tmp_path, configured):
    rec = make_recording(tmp_path, chunks=1)
    finish(rec)
    manager = RedactionManager(UploadManager(recordings_dir=str(rec.parent)),
                               recordings_dir=str(rec.parent), worker=FakeWorker(fail=True))
    for _ in range(3):
        assert manager.step()
    assert not manager.step()  # marked failed, nothing pending
    part = "chunks/display_0/segment_000/chunk_00000.mp4"
    assert json.load(open(meta_path(str(rec), part)))["error"] == "boom"
