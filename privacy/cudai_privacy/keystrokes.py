"""
Redaction of text typed one key at a time.

Typed values arrive as separate key events, so detection runs over rebuilt
typing runs and matches are mapped back to the individual press/release
events (whose key names are scrubbed too). `find` is the detector: the
Presidio rules by default, or rules plus a name model on the server.
"""

from collections import Counter

from .engine import find_spans


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


def redact_keystrokes(events: list, counts: Counter | None = None, find=find_spans) -> list:
    """Redact sensitive values typed key by key. Modifies and returns `events`."""
    for run in _typing_runs(events):
        typed = "".join(text for _, text in run)
        # char offset -> index into run
        owners = [k for k, (_, text) in enumerate(run) for _ in text]
        for start, end, label in find(typed):
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
