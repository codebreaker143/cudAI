import pytest

from services.config_service import ConfigService

TOKEN = "test-token-123"


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setenv("CUDAI_API_TOKEN", TOKEN)
    from backend import CudaiBackend

    return CudaiBackend()


def test_server_listens_on_localhost_only():
    assert ConfigService().server.host == "127.0.0.1"


def test_api_requires_token(backend):
    http = backend.app.test_client()
    assert http.get("/api/recordings").status_code == 401
    assert http.get("/api/recordings", headers={"X-Cudai-Token": "wrong"}).status_code == 401
    assert http.get("/api/recordings", headers={"X-Cudai-Token": TOKEN}).status_code == 200
    # <video> elements pass the token as a query parameter.
    assert http.get(f"/api/recordings?token={TOKEN}").status_code == 200


def test_socket_requires_token(backend):
    rejected = backend.socketio.test_client(backend.app, auth={"token": "wrong"})
    assert not rejected.is_connected()
    accepted = backend.socketio.test_client(backend.app, auth={"token": TOKEN})
    assert accepted.is_connected()


def test_guard_disabled_without_configured_token(monkeypatch):
    monkeypatch.delenv("CUDAI_API_TOKEN", raising=False)
    from backend import CudaiBackend

    http = CudaiBackend().app.test_client()
    assert http.get("/api/recordings").status_code == 200
