"""
Clean raw events before reduction.

- Drop pause/resume markers (the recorder already discards input while paused).
- Drop the recorder's own global shortcuts (start/stop/pause, a11y snapshot).
  They are consumed by the cudAI app and never reach the recorded application.
- Drop input that went to the cudAI app itself (e.g. clicking "Stop").
"""

from bisect import bisect_right
from typing import Dict, List

KEY_ACTIONS = ("press", "release")
MODIFIERS = {"shift", "ctrl", "alt", "cmd"}
MODIFIER_ALIASES = {
    "shift_l": "shift", "shift_r": "shift",
    "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd_l": "cmd", "cmd_r": "cmd",
}

# (modifier chord, keys) registered as global shortcuts in src/index.ts.
# CommandOrControl maps to cmd on macOS and ctrl elsewhere.
APP_HOTKEYS = [
    ({"cmd", "alt"}, {"r", "t", "p"}),
    ({"ctrl", "alt"}, {"r", "t", "p"}),
    ({"cmd", "shift"}, {"t"}),
    ({"ctrl", "shift"}, {"t"}),
]

# A click that focuses the recorder is logged before the window poll notices
# the switch; treat clicks this close to a switch to the recorder as its own.
RECORDER_FOCUS_LAG = 0.5


def _modifier(name: str) -> str | None:
    name = MODIFIER_ALIASES.get(name, name)
    return name if name in MODIFIERS else None


def _is_app_hotkey(event: Dict) -> bool:
    if event["action"] != "press" or "modifiers" not in event:
        return False
    held = set(event["modifiers"])
    return any(held == chord and event["name"] in keys for chord, keys in APP_HOTKEYS)


def strip_app_hotkeys(events: List[Dict]) -> List[Dict]:
    drop = set()
    for i, event in enumerate(events):
        if not _is_app_hotkey(event):
            continue
        drop.add(i)
        chord = set(event["modifiers"])
        key = event["name"]

        # Modifier presses that started this chord.
        j = i - 1
        while j >= 0:
            prev = events[j]
            if prev["action"] in KEY_ACTIONS:
                mod = _modifier(prev["name"])
                if mod not in chord:
                    break
                drop.add(j)
            j -= 1

        # Releases of the key and the chord's modifiers.
        pending = {key} | chord
        j = i + 1
        while j < len(events) and pending:
            nxt = events[j]
            if nxt["action"] in KEY_ACTIONS:
                name = _modifier(nxt["name"]) or nxt["name"]
                if nxt["action"] == "release" and name in pending:
                    drop.add(j)
                    pending.discard(name)
                elif name not in pending:
                    break
                else:
                    drop.add(j)  # key repeat while held
            j += 1

    return [e for i, e in enumerate(events) if i not in drop]


def drop_recorder_app_events(events: List[Dict], top_windows: List[Dict]) -> List[Dict]:
    windows = sorted(
        (w for w in top_windows if "is_recorder" in w), key=lambda w: w["time_stamp"]
    )
    if not windows:
        return events
    times = [w["time_stamp"] for w in windows]

    def active_is_recorder(t: float) -> bool:
        idx = bisect_right(times, t) - 1
        return idx >= 0 and windows[idx]["is_recorder"]

    def switches_to_recorder_soon(t: float) -> bool:
        idx = bisect_right(times, t)
        return (
            idx < len(windows)
            and windows[idx]["is_recorder"]
            and windows[idx]["time_stamp"] - t <= RECORDER_FOCUS_LAG
        )

    kept = []
    for event in events:
        t = event["time_stamp"]
        if active_is_recorder(t):
            continue
        if event["action"] == "click" and switches_to_recorder_soon(t):
            continue
        kept.append(event)
    return kept


def preprocess_events(events: List[Dict], top_windows: List[Dict]) -> List[Dict]:
    events = [e for e in events if e["action"] not in ("pause", "resume")]
    events = strip_app_hotkeys(events)
    events = drop_recorder_app_events(events, top_windows)
    return events
