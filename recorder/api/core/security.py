"""
Per-launch API token.

The backend listens on 127.0.0.1, but any web page open in the user's browser
can still send requests to localhost. The desktop app therefore generates a
random token at startup and passes it to the backend (CUDAI_API_TOKEN) and to
its own UI; every API request and socket connection must present it, either as
the X-Cudai-Token header or a `token` query parameter (used by <video> tags).

When CUDAI_API_TOKEN is unset (tests, running the backend by hand) the guard
is disabled.
"""

import hmac
import os

from flask import jsonify, request

TOKEN_HEADER = "X-Cudai-Token"


def _expected_token() -> str | None:
    return os.environ.get("CUDAI_API_TOKEN") or None


def _valid(candidate: str | None) -> bool:
    expected = _expected_token()
    return expected is None or (
        candidate is not None and hmac.compare_digest(candidate, expected)
    )


def install_api_token_guard(app, socketio) -> None:
    @app.before_request
    def require_token():
        if request.method == "OPTIONS" or not request.path.startswith("/api/"):
            return None
        token = request.headers.get(TOKEN_HEADER) or request.args.get("token")
        if not _valid(token):
            return jsonify({"status": "failed", "message": "Unauthorized"}), 401
        return None

    @socketio.on("connect")
    def require_socket_token(auth=None):
        token = (auth or {}).get("token") or request.args.get("token")
        if not _valid(token):
            return False  # rejects the connection
        return None
