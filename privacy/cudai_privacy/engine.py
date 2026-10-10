"""
Detect and replace personal and sensitive data in text, with Presidio.

Values are replaced with Presidio entity names in brackets ("[EMAIL_ADDRESS]"),
which keeps the training signal ("an email address was entered here")
without the personal data.

Entities:
  credentials/secrets  SECRET        tokens, API keys, private keys, password=...
  contact details      EMAIL_ADDRESS PHONE_NUMBER
  financial/gov IDs    CREDIT_CARD (Luhn) IBAN_CODE (mod-97) IN_AADHAAR
                       (Verhoeff) IN_PAN US_SSN PASSPORT BANK_ACCOUNT
                       (passport/account numbers only next to the keyword)
  network/device IDs   IP_ADDRESS MAC_ADDRESS

Deliberately not detected, because they are valuable training data or
cause false positives in business apps: person names, places, dates,
amounts, URLs, record ids (PO numbers, UUIDs). Person names are removed by
the ingest server's second pass (GLiNER). Presidio runs with a blank spaCy
tokenizer, so no language model is downloaded or bundled.

Known trade-off: bare 10-digit numbers starting 6-9 are treated as Indian
mobile numbers.
"""

import re
import threading
from collections import Counter
from functools import lru_cache

PRIVACY_VERSION = 2


# Validators ------------------------------------------------------------------

def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _luhn_ok(text: str) -> bool:
    digits = _digits(text)
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _verhoeff_ok(text: str) -> bool:
    digits = _digits(text)
    if len(digits) != 12:
        return False
    check = 0
    for i, d in enumerate(reversed(digits)):
        check = _VERHOEFF_D[check][_VERHOEFF_P[i % 8][int(d)]]
    return check == 0


def _iban_ok(text: str) -> bool:
    iban = re.sub(r"\s", "", text).upper()
    if not 15 <= len(iban) <= 34:
        return False
    rearranged = iban[4:] + iban[:4]
    number = "".join(str(int(c, 36)) for c in rearranged)
    return int(number) % 97 == 1


def _phone_ok(text: str) -> bool:
    return 8 <= len(_digits(text)) <= 15


def _has_letter_and_digit(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text) and re.search(r"\d", text))


# Rules (entity, pattern, validator, group), highest priority first ----------
# `group` is the regex group to replace (0 = whole match). A span already
# taken by a higher-priority rule is not redacted again.

_IPV4_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_HEX4 = r"[0-9A-Fa-f]{1,4}"

RULES = [
    ("SECRET", r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----", None, 0),
    ("SECRET", r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}", None, 0),
    ("SECRET", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", None, 0),
    ("SECRET", r"\bAIza[0-9A-Za-z_-]{35}\b", None, 0),
    ("SECRET", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", None, 0),
    ("SECRET", r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b", None, 0),
    ("SECRET",
     r"(?i)\b(?:password|passwd|pwd|passcode|secret|token|api[_-]?key|apikey|"
     r"access[_-]?key|auth[_-]?token|session[_-]?id)\s*[:=]\s*"
     r"(?!\[[A-Z_]+\])([^\s&;#,\"']+)", None, 1),
    # The top-level domain stops where letter case flips ("acme.comQuarterly"),
    # so text typed right after an email is not swallowed.
    ("EMAIL_ADDRESS",
     r"[A-Za-z0-9._%+-]+(?:@|%40)[A-Za-z0-9.-]+\.(?:[a-z]{2,24}(?![a-z])|[A-Z]{2,24}(?![A-Za-z]))", None, 0),
    ("IBAN_CODE", r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b", _iban_ok, 0),
    # Not inside a longer token: digits within a UUID or hex id can pass the
    # checksums by chance ("4662-8535-25394450" in a UUID is Luhn-valid).
    ("CREDIT_CARD", r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])", _luhn_ok, 0),
    ("IN_AADHAAR", r"(?<![\w-])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![\w-])", _verhoeff_ok, 0),
    ("US_SSN", r"(?<!\d)(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)", None, 0),
    ("IN_PAN", r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b", None, 0),
    ("PASSPORT", r"(?i)passport(?:\s*(?:no\.?|number|#))?[\s.:#-]{0,5}([A-Z0-9]{6,9})\b", _has_letter_and_digit, 1),
    ("PASSPORT", r"(?i)passport(?:\s*(?:no\.?|number|#))?[\s.:#-]{0,5}(\d{8,9})\b", None, 1),
    ("BANK_ACCOUNT",
     r"(?i)\b(?:account|acct|a/c)(?:\s*(?:no\.?|number|#))?[\s.:#-]{0,5}(\d[\d -]{7,20}\d)\b", None, 1),
    ("PHONE_NUMBER", r"(?<![\w+])\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,5}){2,4}(?!\d)", _phone_ok, 0),
    ("PHONE_NUMBER", r"(?<![\w+])(?:(?:\+?91|0)[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)", None, 0),
    ("PHONE_NUMBER", r"(?<!\d)(?:\(\d{3}\)\s?|\d{3}[-.\s])\d{3}[-.\s]\d{4}(?!\d)", None, 0),
    ("MAC_ADDRESS", r"(?<![\w:-])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![\w:-])", None, 0),
    ("IP_ADDRESS", rf"(?<![\w:])(?:{_HEX4}:){{7}}{_HEX4}(?![\w:])", None, 0),
    ("IP_ADDRESS", rf"(?<![\w:])(?:{_HEX4}:){{1,7}}:(?:{_HEX4}:){{0,6}}{_HEX4}(?![\w:])", None, 0),
    ("IP_ADDRESS", rf"(?<![\d.])(?:{_IPV4_OCTET}\.){{3}}{_IPV4_OCTET}(?![\d.])", None, 0),
    ("SECRET", r"(?<![A-Za-z0-9_+/=%-])[A-Za-z0-9_+/=%-]{48,}(?![A-Za-z0-9_+/=%-])", _has_letter_and_digit, 0),
]

ENTITIES = sorted({entity for entity, *_ in RULES})

# Presidio's phone recognizer (libphonenumber) adds international formats the
# rules above miss. Lowest priority; only numbers valid for these regions and
# written like phone numbers (see _spans).
PHONE_REGIONS = ("IN", "US", "GB", "CA", "AU", "SG", "AE", "DE", "FR")

# Placeholders written by privacy version 1.
_LEGACY = {
    "EMAIL": "EMAIL_ADDRESS", "PHONE": "PHONE_NUMBER", "CARD": "CREDIT_CARD",
    "IBAN": "IBAN_CODE", "AADHAAR": "IN_AADHAAR", "PAN": "IN_PAN", "SSN": "US_SSN",
    "IP": "IP_ADDRESS", "MAC": "MAC_ADDRESS",
}
_LEGACY_RE = re.compile(r"\[(" + "|".join(_LEGACY) + r")\]")

# Text that cannot contain any entity is skipped without calling Presidio
# (most UI labels): every rule needs a digit, "@", "%40", ":", "=", a key
# prefix, a hex MAC with dashes or 48+ characters.
_MAYBE_SENSITIVE = re.compile(r"[0-9@:=]|%40|eyJ|BEGIN|(?:[0-9A-Fa-f]{2}-){5}")


# Presidio setup ----------------------------------------------------------------

def _rule_recognizer(index: int, entity: str, pattern: str, validator, group: int):
    from presidio_analyzer import EntityRecognizer, RecognizerResult

    compiled = re.compile(pattern)

    class RuleRecognizer(EntityRecognizer):
        def load(self):
            pass

        def analyze(self, text, entities, nlp_artifacts=None):
            results = []
            for match in compiled.finditer(text):
                start, end = match.span(group)
                value = match.group(group)
                if value and (validator is None or validator(value)):
                    result = RecognizerResult(entity, start, end, 1.0)
                    result.recognition_metadata = {"priority": index}
                    results.append(result)
            return results

    return RuleRecognizer(supported_entities=[entity], name=f"cudai_{index:02d}_{entity.lower()}")


def _build_analyzer():
    import spacy
    from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
    from presidio_analyzer.nlp_engine import SpacyNlpEngine
    from presidio_analyzer.predefined_recognizers import PhoneRecognizer

    class BlankSpacyEngine(SpacyNlpEngine):
        """Tokenizer only: no NER model to download or bundle."""

        def load(self):
            self.nlp = {"en": spacy.blank("en")}

    nlp_engine = BlankSpacyEngine(models=[{"lang_code": "en", "model_name": "blank"}])
    nlp_engine.load()
    registry = RecognizerRegistry(supported_languages=["en"])
    for index, (entity, pattern, validator, group) in enumerate(RULES):
        registry.add_recognizer(_rule_recognizer(index, entity, pattern, validator, group))
    registry.add_recognizer(PhoneRecognizer(supported_regions=PHONE_REGIONS, leniency=2))
    return AnalyzerEngine(registry=registry, nlp_engine=nlp_engine, supported_languages=["en"])


_analyzer = None
_analyzer_lock = threading.Lock()


def get_analyzer():
    """The shared Presidio AnalyzerEngine (built on first use)."""
    global _analyzer
    with _analyzer_lock:
        if _analyzer is None:
            _analyzer = _build_analyzer()
    return _analyzer


# Public API --------------------------------------------------------------------

@lru_cache(maxsize=65536)
def _spans(text: str) -> tuple:
    if not _MAYBE_SENSITIVE.search(text) and len(text) < 48:
        return ()
    results = get_analyzer().analyze(text, language="en", score_threshold=0.4)
    # Rules in priority order, then Presidio's own recognizers; a span that
    # overlaps an earlier one is dropped.
    results.sort(key=lambda r: ((r.recognition_metadata or {}).get("priority", len(RULES)), r.start))
    spans = []
    for r in results:
        if any(r.start < end and start < r.end for start, end, _ in spans):
            continue
        if "priority" not in (r.recognition_metadata or {}) and text[r.start:r.end].isdigit():
            # libphonenumber accepts bare digit runs such as SAP document
            # numbers ("5105600012"); keep its matches only when written
            # like a phone number (+, spaces, dashes, brackets).
            continue
        spans.append((r.start, r.end, r.entity_type))
    return tuple(sorted(spans))


def find_spans(text: str) -> list:
    """Non-overlapping (start, end, entity) spans of sensitive data."""
    if not text:
        return []
    return list(_spans(text))


def redact_text(text, counts: Counter | None = None):
    """Replace sensitive values in `text` with [ENTITY] placeholders."""
    if not isinstance(text, str):
        return text
    text = _LEGACY_RE.sub(lambda m: f"[{_LEGACY[m.group(1)]}]", text)
    spans = find_spans(text)
    for start, end, entity in reversed(spans):
        text = text[:start] + f"[{entity}]" + text[end:]
        if counts is not None:
            counts[entity] += 1
    return text


def redact_tree(obj, counts: Counter | None = None):
    """redact_text on every string inside nested dicts/lists (keys kept)."""
    if isinstance(obj, str):
        return redact_text(obj, counts)
    if isinstance(obj, list):
        return [redact_tree(v, counts) for v in obj]
    if isinstance(obj, dict):
        return {k: redact_tree(v, counts) for k, v in obj.items()}
    return obj
