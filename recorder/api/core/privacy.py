"""
Remove personal and sensitive data from recorded text.

Recordings are sold as AI training data, so they must only contain data that
is valuable and legal to share. Values matching the categories below are
replaced with typed placeholders such as "[EMAIL]", which keeps the training
signal ("an email address was entered here") without the personal data.

Categories (placeholder):
  credentials/secrets  [SECRET]   tokens, API keys, private keys, password=...
  contact details      [EMAIL] [PHONE]
  financial/gov IDs    [CARD] (Luhn) [IBAN] (mod-97) [AADHAAR] (Verhoeff)
                       [PAN] [SSN] [PASSPORT] [BANK_ACCOUNT] (keyword-gated)
  network/device IDs   [IP] [MAC]

Record identifiers (PO numbers, UUIDs), amounts, dates and app routes are
kept. Known trade-off: bare 10-digit numbers starting 6-9 are treated as
Indian mobile numbers.

The video is NOT redacted by this module.
"""

import json
import os
import re
from collections import Counter

from .logger import logger

PRIVACY_VERSION = 1


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


# Detectors (label, pattern, validator, group) in priority order -------------
# `group` is the regex group to replace (0 = whole match).

_IPV4_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_HEX4 = r"[0-9A-Fa-f]{1,4}"

DETECTORS = [
    ("SECRET", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), None, 0),
    ("SECRET", re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), None, 0),
    ("SECRET", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), None, 0),
    ("SECRET", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), None, 0),
    ("SECRET", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"), None, 0),
    ("SECRET", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), None, 0),
    ("SECRET", re.compile(
        r"(?i)\b(?:password|passwd|pwd|passcode|secret|token|api[_-]?key|apikey|"
        r"access[_-]?key|auth[_-]?token|session[_-]?id)\s*[:=]\s*"
        r"(?!\[[A-Z_]+\])([^\s&;#,\"']+)"), None, 1),
    # The top-level domain stops where letter case flips ("acme.comQuarterly"),
    # so text typed right after an email is not swallowed.
    ("EMAIL", re.compile(
        r"[A-Za-z0-9._%+-]+(?:@|%40)[A-Za-z0-9.-]+\.(?:[a-z]{2,24}(?![a-z])|[A-Z]{2,24}(?![A-Za-z]))"), None, 0),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"), _iban_ok, 0),
    # Not inside a longer token: digits within a UUID or hex id can pass the
    # checksums by chance ("4662-8535-25394450" in a UUID is Luhn-valid).
    ("CARD", re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])"), _luhn_ok, 0),
    ("AADHAAR", re.compile(r"(?<![\w-])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![\w-])"), _verhoeff_ok, 0),
    ("SSN", re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)"), None, 0),
    ("PAN", re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b"), None, 0),
    ("PASSPORT", re.compile(
        r"(?i)passport(?:\s*(?:no\.?|number|#))?[\s.:#-]{0,5}([A-Z0-9]{6,9})\b"), _has_letter_and_digit, 1),
    ("PASSPORT", re.compile(
        r"(?i)passport(?:\s*(?:no\.?|number|#))?[\s.:#-]{0,5}(\d{8,9})\b"), None, 1),
    ("BANK_ACCOUNT", re.compile(
        r"(?i)\b(?:account|acct|a/c)(?:\s*(?:no\.?|number|#))?[\s.:#-]{0,5}(\d[\d -]{7,20}\d)\b"), None, 1),
    ("PHONE", re.compile(r"(?<![\w+])\+\d{1,3}[\s.-]?\(?\d{1,4}\)?(?:[\s.-]?\d{2,5}){2,4}(?!\d)"), _phone_ok, 0),
    ("PHONE", re.compile(r"(?<![\w+])(?:(?:\+?91|0)[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)"), None, 0),
    ("PHONE", re.compile(r"(?<!\d)(?:\(\d{3}\)\s?|\d{3}[-.\s])\d{3}[-.\s]\d{4}(?!\d)"), None, 0),
    ("MAC", re.compile(r"(?<![\w:-])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![\w:-])"), None, 0),
    ("IP", re.compile(rf"(?<![\w:])(?:{_HEX4}:){{7}}{_HEX4}(?![\w:])"), None, 0),
    ("IP", re.compile(rf"(?<![\w:])(?:{_HEX4}:){{1,7}}:(?:{_HEX4}:){{0,6}}{_HEX4}(?![\w:])"), None, 0),
    ("IP", re.compile(rf"(?<![\d.])(?:{_IPV4_OCTET}\.){{3}}{_IPV4_OCTET}(?![\d.])"), None, 0),
    ("SECRET", re.compile(r"(?<![A-Za-z0-9_+/=%-])[A-Za-z0-9_+/=%-]{48,}(?![A-Za-z0-9_+/=%-])"),
     _has_letter_and_digit, 0),
]


def find_spans(text: str) -> list:
    """Non-overlapping (start, end, label) spans of sensitive data."""
    if not text:
        return []
    spans = []
    for label, pattern, validator, group in DETECTORS:
        for match in pattern.finditer(text):
            start, end = match.span(group)
            value = match.group(group)
            if not value or (validator and not validator(value)):
                continue
            if any(start < s_end and s_start < end for s_start, s_end, _ in spans):
                continue
            spans.append((start, end, label))
    return sorted(spans)


def redact_text(text, counts: Counter | None = None):
    """Replace sensitive values in `text` with typed placeholders."""
    if not isinstance(text, str):
        return text
    spans = find_spans(text)
    if not spans:
        return text
    for start, end, label in reversed(spans):
        text = text[:start] + f"[{label}]" + text[end:]
        if counts is not None:
            counts[label] += 1
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


# Keystrokes ------------------------------------------------------------------
# Typed text arrives one key at a time, so detection runs over rebuilt typing
# runs and matches are mapped back to the individual key events.

RUN_BREAK_KEYS = {"enter", "return", "tab", "esc", "escape", "up", "down"}
RUN_GAP_SECONDS = 5.0
REDACTED_KEY = "redacted"


def _typing_runs(events: list) -> list:
    """Lists of (event index, typed text) for consecutive typing."""
    runs, current, last_t = [], [], None
    for i, e in enumerate(events):
        action = e.get("action")
        t = e.get("time_stamp", 0)
        if _breaks_run(e, last_t) and current:
            runs.append(current)
            current = []
        if action == "press":
            if e.get("name") == "backspace" and current:
                current.pop()
            elif e.get("text"):
                current.append((i, e["text"]))
            last_t = t
    if current:
        runs.append(current)
    return runs


def _breaks_run(e: dict, last_t) -> bool:
    action = e.get("action")
    return (
        action == "click"
        or action in ("pause", "resume")
        or (action == "press" and e.get("name") in RUN_BREAK_KEYS)
        or (last_t is not None and e.get("time_stamp", 0) - last_t > RUN_GAP_SECONDS)
    )


def open_run_start(events: list, now: float) -> int:
    """
    Index of the first event of a typing run that may still continue at
    `now` (len(events) if there is none). Live upload holds events from there
    on back, so a value typed across an upload boundary is still detected.
    """
    start, last_t = None, None
    for i, e in enumerate(events):
        if _breaks_run(e, last_t):
            start = None
        if e.get("action") == "press":
            if start is None and e.get("text"):
                start = i
            last_t = e.get("time_stamp", 0)
    if start is not None and now - last_t <= RUN_GAP_SECONDS:
        return start
    return len(events)


def _scrub_key(event: dict, text) -> None:
    event["name"] = REDACTED_KEY
    event["char"] = None
    event["vk"] = None
    event["pynput_key"] = None
    if event.get("action") == "press":
        event["text"] = text


def _scrub_press_and_release(events: list, press_index: int, text) -> None:
    original = events[press_index].get("name")
    _scrub_key(events[press_index], text)
    # The matching release names the same physical key.
    for j in range(press_index + 1, len(events)):
        e = events[j]
        if e.get("action") == "release" and e.get("name") == original:
            _scrub_key(e, None)
            return


def redact_keystrokes(events: list, counts: Counter | None = None) -> list:
    """Redact sensitive values typed key by key. Modifies and returns `events`."""
    for run in _typing_runs(events):
        typed = "".join(text for _, text in run)
        # char offset -> index into run
        owners = [k for k, (_, text) in enumerate(run) for _ in text]
        for start, end, label in find_spans(typed):
            keys = sorted({owners[c] for c in range(start, end)})
            first_t = events[run[keys[0]][0]].get("time_stamp", 0)
            last_t = events[run[keys[-1]][0]].get("time_stamp", 0)
            for n, k in enumerate(keys):
                _scrub_press_and_release(events, run[k][0], f"[{label}]" if n == 0 else "")
            # Keys typed then deleted within the span's time range.
            for i, e in enumerate(events):
                if (
                    e.get("action") == "press"
                    and e.get("name") not in (REDACTED_KEY, "backspace")
                    and e.get("text")
                    and first_t <= e.get("time_stamp", 0) <= last_t
                ):
                    _scrub_press_and_release(events, i, "")
            if counts is not None:
                counts[label] += 1
    return events


# Recording files ---------------------------------------------------------------

TREE_FILES = ("element.jsonl", "a11y.jsonl", "html.jsonl", "html_element.jsonl")


def _read_jsonl(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_jsonl(path: str, rows: list) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _write_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, path)


def redact_recording_inputs(recording_path: str) -> Counter:
    """
    Redact raw recording files in place (before actions, timeline and the
    manifest are derived from them) and record the counts in metadata.json.
    """
    from .url_privacy import sanitize_url

    counts = Counter()

    def path(name: str) -> str:
        return os.path.join(recording_path, name)

    if os.path.exists(path("events.jsonl")):
        _write_jsonl(path("events.jsonl"), redact_keystrokes(_read_jsonl(path("events.jsonl")), counts))

    if os.path.exists(path("top_window.jsonl")):
        windows = _read_jsonl(path("top_window.jsonl"))
        for w in windows:
            if w.get("url"):
                w["url"] = sanitize_url(w["url"])
        _write_jsonl(path("top_window.jsonl"), [redact_tree(w, counts) for w in windows])

    for name in TREE_FILES:
        if os.path.exists(path(name)):
            _write_jsonl(path(name), [redact_tree(row, counts) for row in _read_jsonl(path(name))])

    if os.path.exists(path("task_name.json")):
        with open(path("task_name.json"), "r", encoding="utf-8") as f:
            task = json.load(f)
        _write_json(path("task_name.json"), redact_tree(task, counts))

    _record_privacy(recording_path, counts)
    return counts


def redact_recording_outputs(recording_path: str) -> Counter:
    """Redact derived files (actions, event buffer) — used for older recordings."""
    counts = Counter()
    for name in ("reduced_events_complete.jsonl", "reduced_events_vis.jsonl", "event_buffer.jsonl"):
        file_path = os.path.join(recording_path, name)
        if os.path.exists(file_path):
            _write_jsonl(file_path, [redact_tree(row, counts) for row in _read_jsonl(file_path)])
    _record_privacy(recording_path, counts)
    return counts


def _record_privacy(recording_path: str, counts: Counter) -> None:
    metadata_path = os.path.join(recording_path, "metadata.json")
    if not os.path.exists(metadata_path):
        return
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    privacy = metadata.get("privacy") or {}
    totals = Counter(privacy.get("redactions") or {})
    totals.update(counts)
    metadata["privacy"] = {
        "version": PRIVACY_VERSION,
        "redactions": dict(totals),
        "video_redacted": False,
    }
    _write_json(metadata_path, metadata)
    if counts:
        logger.info(f"privacy: redacted {dict(counts)} in {os.path.basename(recording_path)}")


def privacy_version(recording_path: str) -> int:
    try:
        with open(os.path.join(recording_path, "metadata.json"), "r", encoding="utf-8") as f:
            return int((json.load(f).get("privacy") or {}).get("version", 0))
    except Exception:
        return 0
