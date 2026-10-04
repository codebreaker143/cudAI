SUCCEED = "succeed"
FAILED = "failed"

RECORDER_VERSION = "0.1.0"
# Bump when the on-disk recording format changes.
SCHEMA_VERSION = "cudai.recording.v1"

VK_CODE = {
    8: "Backspace",
    9: "Tab",
    13: "Enter",
    16: "Shift",
    17: "Ctrl",
    18: "Alt",
    19: "Pause",
    20: "Caps Lock",
    27: "Esc",
    32: "Space",
    33: "Page Up",
    34: "Page Down",
    35: "End",
    36: "Home",
    37: "Left",
    38: "Up",
    39: "Right",
    40: "Down",
    44: "Print Screen",
    45: "Insert",
    46: "Delete",
    # Number andealphabat
    48: "0",
    49: "1",
    50: "2",
    51: "3",
    52: "4",
    53: "5",
    54: "6",
    55: "7",
    56: "8",
    57: "9",
    65: "A",
    66: "B",
    67: "C",
    68: "D",
    69: "E",
    70: "F",
    71: "G",
    72: "H",
    73: "I",
    74: "J",
    75: "K",
    76: "L",
    77: "M",
    78: "N",
    79: "O",
    80: "P",
    81: "Q",
    82: "R",
    83: "S",
    84: "T",
    85: "U",
    86: "V",
    87: "W",
    88: "X",
    89: "Y",
    90: "Z",
    # Numpad
    96: "0",
    97: "1",
    98: "2",
    99: "3",
    100: "4",
    101: "5",
    102: "6",
    103: "7",
    104: "8",
    105: "9",
    110: ".",
    12: "$Unknown$",
}

# macOS virtual keycodes (kVK_*, Carbon HIToolbox/Events.h) for printable keys.
# Names are the unmodified key on a US (ANSI) layout; they identify the
# physical key so press/release events match regardless of held modifiers.
MAC_VK_CODE = {
    0: "a", 1: "s", 2: "d", 3: "f", 4: "h", 5: "g", 6: "z", 7: "x",
    8: "c", 9: "v", 10: "§", 11: "b", 12: "q", 13: "w", 14: "e", 15: "r",
    16: "y", 17: "t", 18: "1", 19: "2", 20: "3", 21: "4", 22: "6", 23: "5",
    24: "=", 25: "9", 26: "7", 27: "-", 28: "8", 29: "0", 30: "]", 31: "o",
    32: "u", 33: "[", 34: "i", 35: "p", 37: "l", 38: "j", 39: "'", 40: "k",
    41: ";", 42: "\\", 43: ",", 44: "/", 45: "n", 46: "m", 47: ".", 50: "`",
    65: "numpad_decimal", 67: "numpad_multiply", 69: "numpad_add",
    71: "numpad_clear", 75: "numpad_divide", 76: "numpad_enter",
    78: "numpad_subtract", 81: "numpad_equal",
    82: "num0", 83: "num1", 84: "num2", 85: "num3", 86: "num4",
    87: "num5", 88: "num6", 89: "num7", 91: "num8", 92: "num9",
    93: "yen", 94: "_", 95: "numpad_comma", 102: "lang2", 104: "lang1",
}

# Canonical modifier names recorded with each keyboard event.
MODIFIER_KEY_NAMES = {
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd",
}
