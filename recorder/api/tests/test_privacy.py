from collections import Counter

import pytest

from core.privacy import find_spans, redact_keystrokes, redact_text, redact_tree

REDACT = [
    # credentials & secrets
    ("password: hunter2!", "password: [SECRET]"),
    ("api_key=sk_live_51Hx9aBc", "api_key=[SECRET]"),
    ("Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9P", "Bearer [SECRET]"),
    ("aws AKIAIOSFODNN7EXAMPLE", "aws [SECRET]"),
    ("maps AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY", "maps [SECRET]"),
    ("gh ghp_1234567890abcdefghijklmnopqrstuvwxyzAB", "gh [SECRET]"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----", "[SECRET]"),
    # contact details
    ("Mail jane.doe@acme.co.in today", "Mail [EMAIL_ADDRESS] today"),
    ("call +91 98765 43210", "call [PHONE_NUMBER]"),
    ("mobile 9876543210", "mobile [PHONE_NUMBER]"),
    ("US office (415) 555-0132", "US office [PHONE_NUMBER]"),
    ("+44 20 7946 0958", "[PHONE_NUMBER]"),
    # financial & government ids
    ("card 4111 1111 1111 1111 exp", "card [CREDIT_CARD] exp"),
    ("IBAN GB82 WEST 1234 5698 7654 32", "IBAN [IBAN_CODE]"),
    ("Aadhaar 2341 2341 2346", "Aadhaar [IN_AADHAAR]"),
    ("PAN ABCPE1234F", "PAN [IN_PAN]"),
    ("SSN 123-45-6789", "SSN [US_SSN]"),
    ("Passport No: K1234567", "Passport No: [PASSPORT]"),
    ("Account number: 123456789012", "Account number: [BANK_ACCOUNT]"),
    # network & device ids
    ("server 192.168.1.20 down", "server [IP_ADDRESS] down"),
    ("v6 2001:db8:85a3::8a2e:370:7334", "v6 [IP_ADDRESS]"),
    ("mac 3C:22:FB:1A:2B:3C", "mac [MAC_ADDRESS]"),
]


@pytest.mark.parametrize("text, expected", REDACT)
def test_sensitive_values_are_replaced(text, expected):
    assert redact_text(text) == expected


KEEP = [
    "PO 4500012345 created for vendor 100045",  # SAP document numbers
    "Invoice 5105600012 posted",
    "chatgpt.com/c/6ac7351a-6660-83ec-88f7-74040310d5a2",  # UUID
    "recording 76dfd702-37f1-4662-8535-25394450bc12",  # UUID with Luhn-valid digits
    "Total 1,200.50 INR on 2026-10-09 at 14:30:05",
    "Card ID 4111 1111 1111 1112",  # 16 digits, fails Luhn
    "Order 2341 2341 2345",  # 12 digits, fails Verhoeff
    "Chrome 128.0.6613.120",  # version, not an IP
    "#PurchaseOrder-manage&/C_PurchaseOrderTP('4500012345')",
    "Cost center 1000 / G/L 400000 / company code 1710",
    "Please approve the purchase order for Acme Corp",
]


@pytest.mark.parametrize("text", KEEP)
def test_business_data_is_kept(text):
    assert redact_text(text) == text


def test_counts_and_trees():
    counts = Counter()
    tree = {"AXTitle": "Reply to jane@acme.com", "children": [{"AXValue": "9876543210"}], "size": 3}
    assert redact_tree(tree, counts) == {
        "AXTitle": "Reply to [EMAIL_ADDRESS]", "children": [{"AXValue": "[PHONE_NUMBER]"}], "size": 3,
    }
    assert counts == Counter({"EMAIL_ADDRESS": 1, "PHONE_NUMBER": 1})


def _typing(text, t0=100.0, name_of=lambda c: c.lower()):
    events, t = [], t0
    for ch in text:
        events.append({"time_stamp": t, "action": "press", "name": name_of(ch), "char": ch, "text": ch, "modifiers": []})
        events.append({"time_stamp": t + 0.05, "action": "release", "name": name_of(ch), "char": ch, "text": None, "modifiers": []})
        t += 0.1
    return events


def test_typed_email_is_redacted_key_by_key():
    events = _typing("hi jane@acme.com ok")
    counts = Counter()
    redact_keystrokes(events, counts)
    typed = "".join(e["text"] for e in events if e["action"] == "press" and e["text"] is not None)
    assert typed == "hi [EMAIL_ADDRESS] ok"
    assert counts == Counter({"EMAIL_ADDRESS": 1})
    leaked = {e.get("char") for e in events} | {e.get("name") for e in events}
    assert not {"j", "@"} & leaked  # neither chars nor physical key names remain
    # Every redacted press still has a matching (redacted) release.
    presses = sum(1 for e in events if e["action"] == "press" and e["name"] == "redacted")
    releases = sum(1 for e in events if e["action"] == "release" and e["name"] == "redacted")
    assert presses == releases == len("jane@acme.com")


def test_deleted_characters_inside_a_span_do_not_leak():
    events = _typing("jane@acmx")
    events.append({"time_stamp": 101.0, "action": "press", "name": "backspace", "char": None, "text": None, "modifiers": []})
    events.append({"time_stamp": 101.05, "action": "release", "name": "backspace", "char": None, "text": None, "modifiers": []})
    events += _typing("e.com", t0=101.1)
    redact_keystrokes(events)
    assert "x" not in {e.get("char") for e in events}
    assert "x" not in {e.get("name") for e in events}


def test_find_spans_does_not_overlap():
    spans = find_spans("jane@acme.com 192.168.1.1")
    assert [label for *_, label in spans] == ["EMAIL_ADDRESS", "IP_ADDRESS"]


def test_processed_recording_contains_no_pii(tmp_path):
    """Plant PII in every input, run real processing, scan every output."""
    import json
    import os

    from core.action_reduction import Reducer
    from core.export import write_export

    rec = tmp_path / "rec"
    rec.mkdir()
    events = _typing("jane.doe@acme.com", t0=100.0) + _typing("4111 1111 1111 1111", t0=103.0)
    events.insert(0, {"time_stamp": 99.0, "action": "click", "x": 10, "y": 10, "button": "left", "pressed": True})
    events.insert(1, {"time_stamp": 99.1, "action": "click", "x": 10, "y": 10, "button": "left", "pressed": False})
    for i, e in enumerate(events):
        e["event_idx"] = i
    (rec / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    (rec / "top_window.jsonl").write_text(json.dumps({
        "time_stamp": 98.0, "app_name": "Mail", "bundle_id": "com.apple.mail", "pid": 1,
        "window_title": "Inbox – jane.doe@acme.com", "url": "https://mail.acme.com/?session=abc123&q=hello",
        "is_recorder": False,
    }) + "\n")
    (rec / "element.jsonl").write_text(json.dumps({
        "time_stamp": 99.0, "a11y_tree": {"AXRole": "AXTextField", "AXValue": "+91 98765 43210"},
    }) + "\n")
    (rec / "task_name.json").write_text(json.dumps({"task_name": "Email jane.doe@acme.com", "description": ""}))
    (rec / "metadata.json").write_text(json.dumps({
        "video_start_timestamp": 98.0, "screen_width": 1512, "screen_height": 982,
        "clock": {"perf_counter": 98.0, "unix_time": 1_790_000_000.0},
    }))

    Reducer(str(rec), {"width": 1512, "height": 982},
            {"generate_window_a11y": False, "generate_element_a11y": True}).reduce_pipeline()
    write_export(str(rec))

    def strings(obj):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            for k, v in obj.items():
                yield from strings(k)
                yield from strings(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from strings(v)

    # Scan every string value (numbers such as float timestamps are not text).
    leaks = []
    for name in sorted(os.listdir(rec)):
        raw = (rec / name).read_text()
        docs = [json.loads(line) for line in raw.splitlines() if line.strip()] if name.endswith(".jsonl") else [json.loads(raw)]
        for value in strings(docs):
            for needle in ("jane.doe", "4111", "98765", "abc123"):
                if needle in value:
                    leaks.append((name, needle, value[:60]))
            for start, end, label in find_spans(value):
                leaks.append((name, label, value[start:end]))
    assert leaks == [], leaks

    metadata = json.loads((rec / "metadata.json").read_text())
    assert metadata["privacy"]["version"] >= 1
    assert metadata["privacy"]["redactions"]["EMAIL_ADDRESS"] >= 2
    assert metadata["privacy"]["video_redacted"] is False
    descriptions = [json.loads(line)["description"] for line in (rec / "reduced_events_vis.jsonl").read_text().splitlines()]
    assert any("[EMAIL_ADDRESS]" in d for d in descriptions) and any("[CREDIT_CARD]" in d for d in descriptions)


def test_presidio_phone_recognizer_adds_national_formats():
    # Not matched by the cudAI rules; found by Presidio's libphonenumber.
    assert redact_text("London desk 020 7946 0958") == "London desk [PHONE_NUMBER]"


def test_version_1_placeholders_are_renamed():
    assert redact_text("sent to [EMAIL] from [IP]") == "sent to [EMAIL_ADDRESS] from [IP_ADDRESS]"
    assert redact_text("[EMAIL_ADDRESS] stays") == "[EMAIL_ADDRESS] stays"
