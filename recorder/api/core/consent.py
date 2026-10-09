"""
Contributor consent.

Accepting the current terms is mandatory before cudAI can be used, and an
acceptance is permanent: it cannot be withdrawn from the app. Bump
CONSENT_VERSION whenever the terms text in
src/components/prerequisite/Terms.tsx changes materially; everyone is then
asked to accept the new version before continuing.
"""

import json
import os
import uuid
from datetime import datetime, timezone

from .utils import get_app_data_dir

CONSENT_VERSION = "2026-10-09"


def _consent_path() -> str:
    return str(get_app_data_dir() / "consent.json")


def _contributor_path() -> str:
    return str(get_app_data_dir() / "contributor.json")


def get_contributor_id() -> str:
    """Stable, anonymous per-install contributor id."""
    path = _contributor_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)["contributor_id"]
    contributor_id = str(uuid.uuid4())
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"contributor_id": contributor_id}, f)
    return contributor_id


def get_consent() -> dict | None:
    path = _consent_path()
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def has_current_consent() -> bool:
    consent = get_consent()
    return bool(
        consent
        and consent.get("accepted")
        and consent.get("version") == CONSENT_VERSION
    )


def record_consent() -> dict:
    """Record acceptance of the current terms. Idempotent; never revoked."""
    if has_current_consent():
        return get_consent()
    consent = {
        "version": CONSENT_VERSION,
        "accepted": True,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "contributor_id": get_contributor_id(),
    }
    with open(_consent_path(), "w", encoding="utf-8") as f:
        json.dump(consent, f, indent=2)
    return consent
