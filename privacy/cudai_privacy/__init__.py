"""
cudAI redaction rules, built on Microsoft Presidio.

One implementation for the desktop app (text and on-device video
redaction) and the ingest server (second pass), so both apply exactly the
same rules and placeholders.
"""

from .engine import (
    ENTITIES,
    PRIVACY_VERSION,
    find_spans,
    get_analyzer,
    redact_text,
    redact_tree,
)

__all__ = ["ENTITIES", "PRIVACY_VERSION", "find_spans", "get_analyzer", "redact_text", "redact_tree"]
