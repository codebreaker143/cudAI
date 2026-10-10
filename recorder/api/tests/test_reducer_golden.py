"""
Regression guard for action extraction.

The reducer turns raw input into the actions buyers receive. This test runs it
on a deterministic synthetic recording and compares a fingerprint of the
output (after privacy redaction: the typed vendor@acme.com becomes [EMAIL_ADDRESS]). If you change reduction behavior on purpose, inspect the new output and
update EXPECTED.
"""

import hashlib
import json

from core.action_reduction import Reducer
from tests.synthetic import write_synthetic_recording

EXPECTED = {
    "actions": 97,
    "reduced_events_vis.jsonl": "ddc6eb0e05ac6454",
    "reduced_events_complete.jsonl": "32310999a2109027",
}


def fingerprint(path):
    result = {}
    for name in ("reduced_events_vis.jsonl", "reduced_events_complete.jsonl"):
        with open(path / name, "rb") as f:
            result[name] = hashlib.sha256(f.read()).hexdigest()[:16]
    with open(path / "reduced_events_vis.jsonl") as f:
        result["actions"] = sum(1 for _ in f)
    return result


def test_reducer_output_is_unchanged(tmp_path):
    path = tmp_path / "rec"
    write_synthetic_recording(str(path), hours=0.1)
    Reducer(
        str(path),
        {"width": 1512, "height": 982},
        {"generate_window_a11y": False, "generate_element_a11y": True},
    ).reduce_pipeline()

    actual = fingerprint(path)
    assert actual == EXPECTED, json.dumps(actual, indent=1)
