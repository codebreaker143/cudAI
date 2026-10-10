"""
End-to-end recording with real screen capture (macOS).

Records your screen for a few seconds, so it only runs when enabled:

    CUDAI_E2E=1 python -m pytest tests/test_e2e_recording.py -s

Needs Screen Recording, Input Monitoring and Accessibility for the terminal.
"""

import json
import os
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CUDAI_E2E") != "1", reason="set CUDAI_E2E=1 to record the screen"
)


def reply(client, event, timeout=180):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for message in client.get_received():
            if message["name"] == event:
                return message["args"][0]
        time.sleep(0.1)
    raise TimeoutError(event)


def test_record_pause_resume_stop_and_process():
    from backend import CudaiBackend
    from core.permissions import missing_permissions
    from core.utils import RECORDING_DIR

    assert not missing_permissions(), f"grant permissions first: {missing_permissions()}"

    backend = CudaiBackend()
    http = backend.app.test_client()
    sio = backend.socketio.test_client(backend.app)

    sio.emit("start_record", {})
    assert reply(sio, "start_record")["status"] == "failed"  # no consent yet

    version = http.get("/api/consent").get_json()["current_version"]
    assert http.post("/api/consent", json={"accepted": True, "version": version}).status_code == 200

    for event, wait in (("start_record", 3), ("pause_record", 2), ("resume_record", 2), ("stop_record", 0)):
        sio.emit(event, {})
        assert reply(sio, event)["status"] == "succeed", event
        time.sleep(wait)
    assert reply(sio, "reduced")["status"] == "succeed"

    (name,) = os.listdir(RECORDING_DIR)
    folder = os.path.join(RECORDING_DIR, name)
    for required in ("video.mp4", "metadata.json", "manifest.json", "timeline.jsonl", "reduced_events_vis.jsonl"):
        assert os.path.exists(os.path.join(folder, required)), required
    assert not os.path.exists(os.path.join(folder, "segments"))

    metadata = json.load(open(os.path.join(folder, "metadata.json")))
    video = metadata["video"]
    assert len(video["segments"]) == 2 and len(video["paused_gaps"]) == 1
    assert len(metadata["pauses"]) == 1
    assert metadata["consent"]["version"] == version
    # Timeline stays linear across the pause.
    second = video["segments"][1]
    assert second["video_offset"] == pytest.approx(
        second["start_timestamp"] - video["video_start_timestamp"], abs=1 / 30 + 1e-6
    )

    review = http.get(f"/api/recording/{name}/review").get_json()
    assert review["status"] == "succeed"
    video_response = http.get(review["video_url"], headers={"Range": "bytes=0-99"})
    assert video_response.status_code == 206

    # Raw files are locked after processing; unlock so the temp dir can be removed.
    os.system(f"chflags -R nouchg '{folder}'")


def test_multi_display_capture():
    """
    Every connected display is recorded as its own video. Needs a second
    (non-mirrored) display; macOS cannot capture one screen twice, so this
    cannot be simulated on a single display.
    """
    from backend import CudaiBackend
    from core.displays import list_displays
    from core.utils import RECORDING_DIR

    displays = list_displays()
    if len(displays) < 2:
        pytest.skip("connect a second (non-mirrored) display to run this test")

    before = set(os.listdir(RECORDING_DIR)) if os.path.isdir(RECORDING_DIR) else set()
    backend = CudaiBackend()
    http = backend.app.test_client()
    version = http.get("/api/consent").get_json()["current_version"]
    http.post("/api/consent", json={"accepted": True, "version": version})
    sio = backend.socketio.test_client(backend.app)
    for event, wait in (("start_record", 2), ("pause_record", 1), ("resume_record", 2), ("stop_record", 0)):
        sio.emit(event, {})
        assert reply(sio, event)["status"] == "succeed", event
        time.sleep(wait)
    assert reply(sio, "reduced")["status"] == "succeed"

    (name,) = set(os.listdir(RECORDING_DIR)) - before
    folder = os.path.join(RECORDING_DIR, name)
    metadata = json.load(open(os.path.join(folder, "metadata.json")))
    videos = [d["video"] for d in metadata["displays"]]
    assert videos[0]["file"] == "video.mp4"
    assert all(v is not None for v in videos), "a display produced no video"
    for v in videos:
        assert os.path.exists(os.path.join(folder, v["file"]))
        assert len(v["segments"]) == 2 and len(v["paused_gaps"]) == 1
    # All displays start together (within half a second).
    starts = [v["video_start_timestamp"] for v in videos]
    assert max(starts) - min(starts) < 0.5

    review = http.get(f"/api/recording/{name}/review").get_json()
    assert [d["index"] for d in review["displays"]] == [d["index"] for d in displays]
    second_video = http.get(review["displays"][1]["video_url"], headers={"Range": "bytes=0-99"})
    assert second_video.status_code == 206
    os.system(f"chflags -R nouchg '{folder}'")


def _frames(path):
    import re

    from core.utils import run_ffmpeg

    log = run_ffmpeg(["-i", path, "-map", "0:v", "-c", "copy", "-f", "null", "-"]).stderr
    return int(re.findall(r"frame=\s*(\d+)", log)[-1])


def test_live_upload_and_server_rebuild(tmp_path, monkeypatch):
    """
    Records ~17 s with a pause while uploading to a local ingest server, then
    rebuilds the video on the server side from the uploaded chunks.
    """
    import sys
    import threading

    from werkzeug.serving import make_server

    from backend import CudaiBackend
    from core.utils import RECORDING_DIR, get_ffmpeg_path

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "server"))
    from cudai_ingest.app import create_app
    from cudai_ingest.assemble import assemble

    server_app = create_app({"api_keys": ["e2e-key"], "storage": "local",
                             "storage_dir": str(tmp_path / "server"), "signing_key": b"s" * 32})
    storage = server_app.extensions["cudai_storage"]
    httpd = make_server("127.0.0.1", 0, server_app, threaded=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("CUDAI_UPLOAD_URL", f"http://127.0.0.1:{httpd.server_port}")
    monkeypatch.setenv("CUDAI_UPLOAD_KEY", "e2e-key")

    before = set(os.listdir(RECORDING_DIR)) if os.path.isdir(RECORDING_DIR) else set()
    backend = CudaiBackend()
    http = backend.app.test_client()
    version = http.get("/api/consent").get_json()["current_version"]
    http.post("/api/consent", json={"accepted": True, "version": version})
    sio = backend.socketio.test_client(backend.app)

    sio.emit("start_record", {})
    assert reply(sio, "start_record")["status"] == "succeed"
    (name,) = set(os.listdir(RECORDING_DIR)) - before
    folder = os.path.join(RECORDING_DIR, name)
    first_chunk = f"recordings/{name}/chunks/display_0/segment_000/chunk_00000.mp4"

    # The first 10-second chunk reaches the server while still recording.
    deadline = time.time() + 20
    while storage.sha256(first_chunk) is None and time.time() < deadline:
        time.sleep(0.5)
    assert storage.sha256(first_chunk), "first chunk was not uploaded during recording"
    assert _frames(storage.path(first_chunk)) == 300

    for event, wait in (("pause_record", 2), ("resume_record", 3), ("stop_record", 0)):
        sio.emit(event, {})
        assert reply(sio, event)["status"] == "succeed", event
        time.sleep(wait)
    assert reply(sio, "reduced")["status"] == "succeed"

    deadline = time.time() + 60
    record = None
    while time.time() < deadline:
        record = storage.read_json(f"recordings/{name}/_recording.json") or {}
        if record.get("status") == "complete":
            break
        time.sleep(0.5)
    assert record.get("status") == "complete", record
    assert not os.path.exists(os.path.join(folder, "chunks"))
    assert storage.sha256(f"recordings/{name}/live/events/000001.jsonl")

    (rebuilt,) = assemble(storage, name, str(tmp_path / "rebuilt"), ffmpeg=get_ffmpeg_path())
    local = os.path.join(folder, "video.mp4")
    assert _frames(rebuilt) == _frames(local)
    metadata = json.load(open(os.path.join(folder, "metadata.json")))
    assert _frames(rebuilt) == round(metadata["video"]["duration"] * 30)
    os.system(f"chflags -R nouchg '{folder}'")
