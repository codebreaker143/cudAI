from platform import system

import pytest
from pynput.keyboard import Key, KeyCode

from core.action_reduction.preprocess import preprocess_events, strip_app_hotkeys
from core.action_reduction.reducer import Reducer
from core.utils import get_key_char, get_key_name

mac_only = pytest.mark.skipif(system() != "Darwin", reason="macOS keycodes")


@mac_only
def test_composed_characters_resolve_to_physical_key():
    # Option+T produces "†", Option+Shift+... can produce "þ".
    assert get_key_name(KeyCode(vk=17, char="†")) == "t"
    assert get_key_name(KeyCode(vk=17, char="T")) == "t"
    assert get_key_name(KeyCode(vk=35, char="þ")) == "p"
    assert get_key_char(KeyCode(vk=17, char="†")) == "†"


def test_control_characters_and_special_keys():
    assert get_key_name(KeyCode(char="\x03")) == "c"
    assert get_key_char(KeyCode(char="\x03")) is None
    assert get_key_name(Key.cmd_r) == "cmd_r"


def key(action, name, t, modifiers=(), text=None):
    return {
        "time_stamp": t,
        "action": action,
        "name": name,
        "char": text,
        "text": text if action == "press" else None,
        "modifiers": sorted(modifiers),
    }


def with_idx(events):
    for i, e in enumerate(events):
        e["event_idx"] = i
    return events


def reduce(events):
    reducer = Reducer(
        recording_path="/nonexistent",
        window_attrs={"width": 1512, "height": 982},
        configs={"generate_window_a11y": False, "generate_element_a11y": False},
    )
    reducer.compress(with_idx(preprocess_events(events, [])))
    reducer.reduce_all()
    reducer.transform()
    return [a.description for a in reducer.reduced_actions]


def test_shortcut_with_modifier_released_first():
    # cmd down, c down, cmd up, c up: used to leave an unmatched "c" press.
    events = [
        key("press", "cmd", 1.0),
        key("press", "c", 1.1, {"cmd"}),
        key("release", "cmd", 1.2),
        key("release", "c", 1.3),
    ]
    assert reduce(events) == ["⌨️ Press: $cmd$ + c"]


def test_option_shortcut_is_not_typed_text():
    events = [
        key("press", "alt", 1.0),
        key("press", "t", 1.1, {"alt"}),  # char "†", text None
        key("release", "t", 1.2, {"alt"}),
        key("release", "alt", 1.3),
    ]
    assert reduce(events) == ["⌨️ Press: $alt$ + t"]


def test_typed_text_uses_produced_characters():
    events = [
        key("press", "h", 1.0, text="h"),
        key("release", "h", 1.05),
        key("press", "i", 1.1, text="i"),
        key("release", "i", 1.15),
        key("press", "2", 1.2, {"shift"}, text="@"),
        key("release", "2", 1.25, {"shift"}),
    ]
    descriptions = reduce(events)
    assert descriptions == ["⌨️ Type: hi@"]


def test_stop_hotkey_is_stripped_from_end():
    events = [
        key("press", "a", 1.0, text="a"),
        key("release", "a", 1.1),
        key("press", "cmd", 2.0),
        key("press", "alt", 2.05, {"cmd"}),
        key("press", "t", 2.1, {"alt", "cmd"}),
        # Recording stops before the releases arrive.
    ]
    stripped = strip_app_hotkeys(events)
    assert [e["name"] for e in stripped] == ["a", "a"]
    assert reduce(events) == ["⌨️ Type: a"]


def test_pause_hotkey_releases_are_stripped():
    events = [
        key("press", "ctrl", 1.0),
        key("press", "alt", 1.05, {"ctrl"}),
        key("press", "p", 1.1, {"alt", "ctrl"}),
        {"time_stamp": 1.12, "action": "pause"},
        {"time_stamp": 5.0, "action": "resume"},
        key("release", "p", 5.1, {"alt", "ctrl"}),
        key("release", "alt", 5.2, {"ctrl"}),
        key("release", "ctrl", 5.3),
        key("press", "b", 6.0, text="b"),
        key("release", "b", 6.1),
    ]
    assert reduce(events) == ["⌨️ Type: b"]
