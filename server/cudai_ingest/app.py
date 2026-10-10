"""
cudAI ingest server (reference implementation).

Receives recordings from the cudAI desktop app while they are being made.
The app asks for an upload link per file and sends the bytes there, straight
to the bucket when S3 storage is used. See ../README.md for the protocol.

Configuration (environment):
  CUDAI_API_KEYS        comma-separated access keys handed to contributors' apps
  CUDAI_STORAGE         "local" (default) or "s3"
  CUDAI_STORAGE_DIR     local storage directory (default ./data)
  CUDAI_SIGNING_KEY     secret for local upload links (default: random per start)
  CUDAI_PUBLIC_URL      this server's public address, for local upload links
                        (default: the address the request came in on)
  CUDAI_S3_BUCKET       s3: bucket name
  CUDAI_S3_ENDPOINT     s3: endpoint for R2 / GCS / MinIO (empty for AWS)
  CUDAI_S3_REGION       s3: region; credentials come from the usual AWS_* env
  CUDAI_UPLOAD_LINK_TTL seconds an upload link stays valid (default 900)
  CUDAI_MAX_FILE_BYTES  largest accepted file (default 1 GiB)
"""

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timezone

from flask import Flask, abort, jsonify, request

from .storage import LocalStorage, storage_from_config

RECORDING_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Relative paths inside a recording; "_" names are reserved for the server.
FILE_PATH = re.compile(r"^(?!.*\.\.)(?!_)[A-Za-z0-9][A-Za-z0-9_./-]{0,255}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RECORDING_FIELDS = (
    "contributor_id",
    "consent_version",
    "recorder_version",
    "schema_version",
    "started_at",
)


def config_from_env() -> dict:
    return {
        "api_keys": [k.strip() for k in os.environ.get("CUDAI_API_KEYS", "").split(",") if k.strip()],
        "storage": os.environ.get("CUDAI_STORAGE", "local"),
        "storage_dir": os.environ.get("CUDAI_STORAGE_DIR", "data"),
        "signing_key": (os.environ.get("CUDAI_SIGNING_KEY") or secrets.token_hex(32)).encode(),
        "public_url": os.environ.get("CUDAI_PUBLIC_URL"),
        "s3_bucket": os.environ.get("CUDAI_S3_BUCKET"),
        "s3_endpoint": os.environ.get("CUDAI_S3_ENDPOINT"),
        "s3_region": os.environ.get("CUDAI_S3_REGION"),
        "link_ttl": int(os.environ.get("CUDAI_UPLOAD_LINK_TTL", "900")),
        "max_file_bytes": int(os.environ.get("CUDAI_MAX_FILE_BYTES", str(1 << 30))),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_app(config: dict | None = None) -> Flask:
    config = {**config_from_env(), **(config or {})}
    storage = config.get("storage_backend") or storage_from_config(config)
    api_keys = config["api_keys"]
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = config["max_file_bytes"] + 1
    app.extensions["cudai_storage"] = storage

    def access_key_id() -> str:
        """Authenticate the request; returns a short id of the access key."""
        auth = request.headers.get("Authorization", "")
        token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
        if not token or not any(hmac.compare_digest(token, key) for key in api_keys):
            abort(401)
        return hashlib.sha256(token.encode()).hexdigest()[:16]

    def recording_key(recording_id: str, path: str = "_recording.json") -> str:
        if not RECORDING_ID.match(recording_id):
            abort(400, "invalid recording id")
        return f"recordings/{recording_id}/{path}"

    def own_recording(recording_id: str, key_id: str) -> dict:
        record = storage.read_json(recording_key(recording_id))
        if record is None:
            abort(404, "unknown recording")
        if record.get("key_id") != key_id:
            abort(403)
        return record

    @app.get("/healthz")
    def health():
        return {"ok": True}

    @app.put("/v1/recordings/<recording_id>")
    def open_recording(recording_id):
        key_id = access_key_id()
        body = request.get_json(silent=True) or {}
        key = recording_key(recording_id)
        record = storage.read_json(key) or {
            "recording_id": recording_id,
            "key_id": key_id,
            "created_at": _now(),
            "status": "receiving",
        }
        if record.get("key_id") != key_id:
            abort(403)
        record.update({field: body.get(field) for field in RECORDING_FIELDS if field in body})
        record["updated_at"] = _now()
        storage.write_json(key, record)
        return jsonify(record)

    @app.post("/v1/recordings/<recording_id>/files")
    def request_upload(recording_id):
        key_id = access_key_id()
        own_recording(recording_id, key_id)
        body = request.get_json(silent=True) or {}
        path, sha256, size = body.get("path"), body.get("sha256"), body.get("size")
        if not isinstance(path, str) or not FILE_PATH.match(path):
            abort(400, "invalid path")
        if not isinstance(sha256, str) or not SHA256.match(sha256):
            abort(400, "invalid sha256")
        if not isinstance(size, int) or not 0 <= size <= config["max_file_bytes"]:
            abort(400, "invalid size")
        key = recording_key(recording_id, path)
        if storage.sha256(key) == sha256:
            return {"exists": True}
        base_url = config.get("public_url") or request.host_url
        return storage.upload_ticket(key, sha256, size, config["link_ttl"], base_url)

    @app.put("/v1/blob")
    def put_blob():
        """Upload target for LocalStorage links (S3 links go to the bucket)."""
        if not isinstance(storage, LocalStorage):
            abort(404)
        args = request.args
        try:
            key, sha256 = args["key"], args["sha256"]
            size, expires = int(args["size"]), int(args["expires"])
            signature = args["signature"]
        except (KeyError, ValueError):
            abort(400)
        if not storage.check_ticket(key, sha256, size, expires, signature):
            abort(403, "invalid or expired upload link")
        data = request.get_data(cache=False)
        if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
            abort(400, "content does not match the declared size and sha256")
        storage.put(key, data)
        return {"ok": True}

    @app.post("/v1/recordings/<recording_id>/complete")
    def complete(recording_id):
        key_id = access_key_id()
        record = own_recording(recording_id, key_id)
        files = (request.get_json(silent=True) or {}).get("files")
        if not isinstance(files, list) or not files:
            abort(400, "files required")
        for f in files:
            if not isinstance(f, dict) or not FILE_PATH.match(str(f.get("path", ""))):
                abort(400, "invalid file entry")
        missing = [
            f["path"]
            for f in files
            if storage.sha256(recording_key(recording_id, f["path"])) != f.get("sha256")
        ]
        if missing:
            return jsonify(error="files missing or different", missing=missing), 409
        storage.write_json(recording_key(recording_id, "_files.json"), files)
        record.update(
            status="complete",
            completed_at=_now(),
            file_count=len(files),
            bytes=sum(int(f.get("size") or 0) for f in files),
        )
        storage.write_json(recording_key(recording_id), record)
        return jsonify(record)

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="cudAI ingest server (development)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if not config_from_env()["api_keys"]:
        print("warning: CUDAI_API_KEYS is empty; every request will be rejected")
    create_app().run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
