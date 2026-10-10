"""
Upload recordings to cudAI's cloud while they are being made.

- Video: each display's 10-second chunks (core.xrec_capture) as soon as they
  are closed, then the pause-gap clips. The server rebuilds video.mp4 by
  joining video.parts (see server/assemble.py); video.mp4 itself is never
  uploaded.
- Events: every 10 s, the new lines of the raw logs, redacted (core.privacy),
  as live/<log>/<seq>.jsonl. A typing run that may still continue is held
  back to the next upload, so values typed across a boundary are detected.
- Once processed: the final (redacted) recording files, then "complete".
  Local chunks are then removed; video.mp4 stays on this computer.

Only recordings made under terms that include cloud upload are uploaded.
Progress is kept in <recording>/upload_state.json, so uploads resume after
network loss or a restart. The protocol is described in server/README.md.
"""

import hashlib
import json
import os
import shutil
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .consent import CLOUD_UPLOAD_CONSENT_VERSION, get_contributor_id
from .constants import RECORDER_VERSION, SCHEMA_VERSION
from .logger import logger
from .privacy import open_run_start, redact_keystrokes, redact_tree
from .utils import RECORDING_DIR, get_app_data_dir

LIVE_LOGS = ("events.jsonl", "top_window.jsonl", "element.jsonl")
PACKAGE_FILES = (
    "metadata.json",
    "manifest.json",
    "timeline.jsonl",
    "events.jsonl",
    "top_window.jsonl",
    "element.jsonl",
    "a11y.jsonl",
    "reduced_events_complete.jsonl",
    "reduced_events_vis.jsonl",
    "task_name.json",
)
STATE_FILE = "upload_state.json"


# Configuration -----------------------------------------------------------------

def _config_path() -> str:
    return str(get_app_data_dir() / "upload.json")


def load_config() -> dict:
    """Server URL and access key; CUDAI_UPLOAD_URL / CUDAI_UPLOAD_KEY override."""
    config = {}
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        pass
    url = os.environ.get("CUDAI_UPLOAD_URL") or config.get("server_url") or ""
    key = os.environ.get("CUDAI_UPLOAD_KEY") or config.get("access_key") or ""
    return {"server_url": url.strip().rstrip("/"), "access_key": key.strip()}


def is_configured(config: dict) -> bool:
    return bool(config["server_url"] and config["access_key"])


def validate_server_url(url: str) -> str:
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        raise ValueError("The server address must start with https://")
    if not parts.hostname:
        raise ValueError("The server address is not valid")
    return url


def save_config(server_url: str, access_key: str) -> dict:
    config = {
        "server_url": validate_server_url(server_url) if server_url.strip() else "",
        "access_key": access_key.strip(),
    }
    path = _config_path()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return config


# HTTP client --------------------------------------------------------------------

class UploadError(Exception):
    def __init__(self, message: str, retryable: bool = True, missing: list | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.missing = missing or []


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # the packaged app has no system CA bundle path

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class UploadClient:
    def __init__(self, server_url: str, access_key: str, timeout: float = 60):
        self.server_url = server_url
        self.access_key = access_key
        self.timeout = timeout
        self._ssl = _ssl_context()

    def _open(self, request: urllib.request.Request):
        try:
            return urllib.request.urlopen(request, timeout=self.timeout, context=self._ssl)
        except urllib.error.HTTPError as e:
            body = e.read()[:500].decode("utf-8", "replace")
            missing = []
            if e.code == 409:
                try:
                    missing = json.loads(body).get("missing") or []
                except ValueError:
                    pass
            retryable = e.code >= 500 or e.code in (408, 409, 429)
            raise UploadError(f"HTTP {e.code}: {body}", retryable, missing) from None
        except (urllib.error.URLError, OSError) as e:
            raise UploadError(f"Network error: {getattr(e, 'reason', e)}") from None

    def _api(self, method: str, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(
            self.server_url + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={
                "Authorization": f"Bearer {self.access_key}",
                "Content-Type": "application/json",
                "User-Agent": f"cudAI/{RECORDER_VERSION}",
            },
        )
        with self._open(request) as response:
            return json.loads(response.read() or b"{}")

    def open_recording(self, recording_id: str, info: dict) -> None:
        self._api("PUT", f"/v1/recordings/{recording_id}", info)

    def put_file(self, recording_id: str, path: str, data, sha256: str, size: int) -> bool:
        """Upload bytes or a local file. False if the server already has it."""
        ticket = self._api(
            "POST",
            f"/v1/recordings/{recording_id}/files",
            {"path": path, "size": size, "sha256": sha256},
        )
        if ticket.get("exists"):
            return False
        body = data if isinstance(data, bytes) else open(data, "rb")
        try:
            request = urllib.request.Request(
                ticket["url"],
                data=body,
                method=ticket.get("method", "PUT"),
                headers={**(ticket.get("headers") or {}), "Content-Length": str(size)},
            )
            with self._open(request) as response:
                response.read()
        finally:
            if not isinstance(data, bytes):
                body.close()
        return True

    def complete(self, recording_id: str, files: list) -> dict:
        return self._api("POST", f"/v1/recordings/{recording_id}/complete", {"files": files})


# Per-recording state ------------------------------------------------------------

def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_state(recording_path: str) -> dict:
    state = _read_json(os.path.join(recording_path, STATE_FILE))
    state.setdefault("files", {})
    state.setdefault("live", {})
    return state


def save_state(recording_path: str, state: dict) -> None:
    path = os.path.join(recording_path, STATE_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, path)


def is_eligible(recording_path: str) -> bool:
    """Made under terms that include cloud upload."""
    consent = _read_json(os.path.join(recording_path, "metadata.json")).get("consent") or {}
    return bool(consent.get("accepted")) and (consent.get("version") or "") >= CLOUD_UPLOAD_CONSENT_VERSION


def is_processed(recording_path: str) -> bool:
    return all(
        os.path.exists(os.path.join(recording_path, name))
        for name in ("reduced_events_vis.jsonl", "manifest.json", "timeline.jsonl")
    )


def recording_upload_status(recording_path: str) -> dict:
    """For the recordings list: local_only, waiting, uploading or uploaded."""
    if not is_eligible(recording_path):
        return {"state": "local_only"}
    state = load_state(recording_path)
    uploaded = sum(f["size"] for f in state["files"].values())
    if state.get("complete") and not state.get("dirty"):
        return {"state": "uploaded", "bytes": uploaded, "completed_at": state.get("completed_at")}
    if state.get("error"):
        return {"state": "error", "bytes": uploaded, "error": state["error"]}
    return {"state": "uploading" if state["files"] else "waiting", "bytes": uploaded}


def _video_parts(metadata: dict) -> list:
    videos = [d.get("video") for d in metadata.get("displays") or []] or [metadata.get("video")]
    parts = []
    for video in videos:
        for part in (video or {}).get("parts") or []:
            if part not in parts:
                parts.append(part)
    return parts


# Upload manager -----------------------------------------------------------------

class UploadManager(threading.Thread):
    """Background uploader: the live recording first, then finished ones."""

    TICK_SECONDS = 2.0
    LIVE_LOG_INTERVAL = 10.0
    MAX_BACKOFF = 60.0

    def __init__(self, socketio=None, recordings_dir: str = RECORDING_DIR):
        super().__init__(daemon=True, name="cudai-upload")
        self.socketio = socketio
        self.recordings_dir = recordings_dir
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._live = None  # (recording_path, capture)
        self._busy = set()  # recordings being recorded or processed
        self._done = set()  # nothing left to do this session
        self._last_live_logs = 0.0
        self._failures = 0
        self._stopped = False
        self.status = {
            "state": "idle",
            "last_upload_at": None,
            "last_error": None,
        }

    # Called by RecordingService -------------------------------------------

    def set_live(self, recording_path: str, capture) -> None:
        with self._lock:
            self._live = (recording_path, capture)
            self._busy.add(recording_path)
            self._last_live_logs = time.monotonic()
        self._wake.set()

    def clear_live(self) -> None:
        with self._lock:
            self._live = None

    def mark_busy(self, recording_path: str) -> None:
        with self._lock:
            self._busy.add(recording_path)

    def recording_processed(self, recording_path: str) -> None:
        with self._lock:
            self._busy.discard(recording_path)
            self._done.discard(recording_path)
        self._wake.set()

    def mark_dirty(self, recording_path: str) -> None:
        """Recording files changed after upload (task name, annotations)."""
        state = load_state(recording_path)
        if state.get("complete"):
            state["dirty"] = True
            save_state(recording_path, state)
        with self._lock:
            self._done.discard(recording_path)
        self._wake.set()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stopped = True
        self._wake.set()

    def get_status(self) -> dict:
        config = load_config()
        return {
            **self.status,
            "configured": is_configured(config),
            "server_url": config["server_url"],
            "access_key_set": bool(config["access_key"]),
        }

    # Loop -------------------------------------------------------------------

    def run(self) -> None:
        while not self._stopped:
            delay = self.TICK_SECONDS
            try:
                self.tick()
                self._failures = 0
            except UploadError as e:
                self._failures += 1
                delay = min(self.MAX_BACKOFF, self.TICK_SECONDS * 2 ** self._failures)
                self._set_status("offline" if e.retryable else "error", last_error=str(e))
                logger.warning(f"upload: {e} (retrying in {delay:.0f}s)")
            except Exception as e:
                self._failures += 1
                delay = min(self.MAX_BACKOFF, self.TICK_SECONDS * 2 ** self._failures)
                self._set_status("error", last_error=str(e))
                logger.exception("upload: unexpected error")
            self._wake.wait(delay)
            self._wake.clear()

    def tick(self) -> None:
        config = load_config()
        client = UploadClient(**config) if is_configured(config) else None
        with self._lock:
            live = self._live
        if client and live and is_eligible(live[0]):
            self._upload_live(client, *live)
        self._scan(client, live[0] if live else None)
        if client is None:
            self._set_status("not_configured")
        elif self.status["state"] in ("offline", "error", "not_configured", "uploading"):
            self._set_status("idle", last_error=None)

    def _set_status(self, state: str, **fields) -> None:
        changed = state != self.status["state"] or any(
            self.status.get(k) != v for k, v in fields.items()
        )
        self.status.update(state=state, **fields)
        if changed and self.socketio is not None:
            self.socketio.emit("upload_status", self.status)

    def _uploaded(self) -> None:
        self.status["last_upload_at"] = time.time()
        self._set_status("uploading")

    # Live recording ---------------------------------------------------------

    def _upload_live(self, client: UploadClient, path: str, capture) -> None:
        state = load_state(path)
        self._open_recording(client, path, state)
        for chunk in capture.ready_chunks():
            self._put_file(client, path, state, chunk["path"], immutable=True)
        if time.monotonic() - self._last_live_logs >= self.LIVE_LOG_INTERVAL:
            self._upload_live_logs(client, path, state)
            self._last_live_logs = time.monotonic()

    def _upload_live_logs(self, client: UploadClient, path: str, state: dict) -> None:
        for name in LIVE_LOGS:
            file = os.path.join(path, name)
            if not os.path.exists(file):
                continue
            progress = state["live"].setdefault(name, {"offset": 0, "seq": 0})
            with open(file, "rb") as f:
                f.seek(progress["offset"])
                data = f.read()
            # Only whole lines: the recorder may be mid-write.
            lines = data[: data.rfind(b"\n") + 1].splitlines(keepends=True)
            rows = [json.loads(line) if line.strip() else None for line in lines]
            if name == "events.jsonl":
                keep = open_run_start([r or {} for r in rows], time.perf_counter())
                lines, rows = lines[:keep], rows[:keep]
                rows = redact_keystrokes([r for r in rows if r is not None])
            else:
                rows = [redact_tree(r) for r in rows if r is not None]
            if not lines:
                continue
            if rows:
                payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode()
                seq = progress["seq"] + 1
                remote = f"live/{name[: -len('.jsonl')]}/{seq:06d}.jsonl"
                sha = hashlib.sha256(payload).hexdigest()
                client.put_file(os.path.basename(path), remote, payload, sha, len(payload))
                state["files"][remote] = {"sha256": sha, "size": len(payload)}
                progress["seq"] = seq
                self._uploaded()
            progress["offset"] += sum(len(line) for line in lines)
            save_state(path, state)

    # Finished recordings ----------------------------------------------------

    def _scan(self, client: UploadClient | None, live_path: str | None) -> None:
        if not os.path.isdir(self.recordings_dir):
            return
        for name in sorted(os.listdir(self.recordings_dir)):
            path = os.path.join(self.recordings_dir, name)
            with self._lock:
                skip = path in self._done or path in self._busy or path == live_path
            if skip or not os.path.isdir(path) or not is_processed(path):
                continue
            if not is_eligible(path):
                # Recorded under local-only terms: never uploaded.
                shutil.rmtree(os.path.join(path, "chunks"), ignore_errors=True)
                self._done.add(path)
                continue
            if client is None:
                continue
            state = load_state(path)
            if state.get("complete") and not state.get("dirty"):
                self._done.add(path)
                continue
            try:
                self._upload_finished(client, path, state)
            except UploadError as e:
                if e.retryable:
                    raise
                logger.error(f"upload: {name} rejected: {e}")
                state["error"] = str(e)
                save_state(path, state)
            self._done.add(path)

    def _upload_finished(self, client: UploadClient, path: str, state: dict) -> None:
        self._open_recording(client, path, state)
        metadata = _read_json(os.path.join(path, "metadata.json"))
        for part in _video_parts(metadata):
            if os.path.exists(os.path.join(path, part)):
                self._put_file(client, path, state, part, immutable=True)
            elif part not in state["files"]:
                raise UploadError(f"video part {part} is missing", retryable=False)
        for name in PACKAGE_FILES:
            if os.path.exists(os.path.join(path, name)):
                self._put_file(client, path, state, name)

        files = [{"path": p, **info} for p, info in sorted(state["files"].items())]
        try:
            client.complete(os.path.basename(path), files)
        except UploadError as e:
            if e.missing:  # the server lost files we sent: send them again
                for p in e.missing:
                    state["files"].pop(p, None)
                save_state(path, state)
            raise
        state.update(
            complete=True,
            dirty=False,
            error=None,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        save_state(path, state)
        shutil.rmtree(os.path.join(path, "chunks"), ignore_errors=True)
        logger.info(f"upload: {os.path.basename(path)} uploaded ({len(files)} files)")

    # Helpers ----------------------------------------------------------------

    def _open_recording(self, client: UploadClient, path: str, state: dict) -> None:
        if state.get("opened"):
            return
        metadata = _read_json(os.path.join(path, "metadata.json"))
        client.open_recording(
            os.path.basename(path),
            {
                "contributor_id": get_contributor_id(),
                "consent_version": (metadata.get("consent") or {}).get("version"),
                "recorder_version": RECORDER_VERSION,
                "schema_version": SCHEMA_VERSION,
                "started_at": metadata.get("start_time"),
            },
        )
        state["opened"] = True
        save_state(path, state)

    def _put_file(
        self, client: UploadClient, path: str, state: dict, remote: str, immutable: bool = False
    ) -> None:
        """Upload <path>/<remote> unless already sent (chunks never change)."""
        if immutable and remote in state["files"]:
            return
        file = os.path.join(path, remote)
        size = os.path.getsize(file)
        sha = _sha256_file(file)
        if state["files"].get(remote, {}).get("sha256") == sha:
            return
        client.put_file(os.path.basename(path), remote, file, sha, size)
        state["files"][remote] = {"sha256": sha, "size": size}
        save_state(path, state)
        self._uploaded()
