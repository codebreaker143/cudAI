"""
Redact secrets and personal data from page URLs while keeping their structure.

Query strings and fragments are valuable training data: they hold app state
(SAP Fiori routes like #PurchaseOrder-manage&/C_PurchaseOrderTP('45..'),
search terms, filters, tabs, record ids). They can also carry credentials and
personal data, so every parameter name and the URL's shape are kept, but:

- values of credential-like parameters become [SECRET]
- personal and sensitive values anywhere in the URL are replaced using the
  shared Presidio rules (cudai_privacy) ([EMAIL_ADDRESS], [PHONE_NUMBER], [CREDIT_CARD], ...)
- user:password@ credentials in the host part are dropped
"""

import re
from urllib.parse import unquote, urlsplit, urlunsplit

from .privacy import redact_text

# Parameter names whose values are secrets (case-insensitive, whole name).
# Descriptive metadata such as token_type or token_type_hint is not secret.
_SECRET_KEY = re.compile(
    r"""^(?!.*[-_](type|hint)$)(
        .*(token|secret|passw|pwd|sessid|session|apikey|api[-_]key|signature|
           credential|cookie|saml|jwt|bearer|private).*
        | auth | authorization | auth[-_].* | .*[-_]auth
        | sid | key | sig | code | otp | nonce | ticket | pin
        | x-amz-(credential|signature|security-token)
        | x-goog-(credential|signature)
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

# key=value pairs inside a query string or fragment.
_PAIR = re.compile(r"(?P<key>[^=&;#?/]+)=(?P<value>[^&;#]*)")


def _redact_component(text: str) -> str:
    # Detect on the decoded form too (e.g. jane%40acme.com, +91%2098765...).
    redacted = redact_text(text)
    decoded = unquote(text)
    if decoded != text and redact_text(decoded) != decoded:
        return redact_text(decoded)
    return redacted


def _redact_pairs(text: str) -> str:
    def replace(match):
        key, value = match.group("key"), match.group("value")
        if value and _SECRET_KEY.match(key):
            return f"{key}=[SECRET]"
        return match.group(0)

    return _redact_component(_PAIR.sub(replace, text))


def sanitize_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = parts.netloc.rsplit("@", 1)[-1]  # drop user:password@
    return urlunsplit(
        (
            parts.scheme,
            host,
            _redact_component(parts.path),
            _redact_pairs(parts.query),
            _redact_pairs(parts.fragment),
        )
    )
