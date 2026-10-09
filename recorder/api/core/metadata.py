import json
import locale
import os
import platform
import subprocess
import time
from datetime import datetime

from screeninfo import get_monitors

from .consent import get_consent, get_contributor_id
from .constants import RECORDER_VERSION, SCHEMA_VERSION


def _run(cmd: list) -> str | None:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


def detect_natural_scrolling() -> bool:
    if platform.system() == "Darwin":
        # Missing key means the macOS default, which is natural scrolling.
        return _run(["defaults", "read", "-g", "com.apple.swipescrolldirection"]) != "0"
    return False


def _locale() -> str | None:
    if platform.system() == "Darwin":
        # The process locale is often unset for GUI-launched apps.
        value = _run(["defaults", "read", "-g", "AppleLocale"])
        if value:
            return value
    return locale.getlocale()[0]


def _keyboard_layout() -> str | None:
    if platform.system() == "Darwin":
        return _run([
            "defaults", "read",
            os.path.expanduser("~/Library/Preferences/com.apple.HIToolbox.plist"),
            "AppleCurrentKeyboardLayoutInputSourceID",
        ])
    if platform.system() == "Windows":
        try:
            import ctypes
            layout = ctypes.windll.user32.GetKeyboardLayout(0) & 0xFFFF
            return hex(layout)
        except Exception:
            return None
    return None


def _device_model() -> str:
    try:
        match platform.system():
            case "Windows":
                import wmi
                for item in wmi.WMI().Win32_ComputerSystem():
                    return item.Model
            case "Darwin":
                return _run(["sysctl", "-n", "hw.model"]) or "Unknown"
            case "Linux":
                with open("/sys/devices/virtual/dmi/id/product_name", "r") as f:
                    return f.read().strip()
    except Exception:
        pass
    return "Unknown"


def _os_version() -> str:
    if platform.system() == "Darwin":
        return platform.mac_ver()[0]
    return platform.version()


def _monitors() -> list:
    monitors = []
    for m in get_monitors():
        monitors.append({
            "name": m.name,
            "x": m.x,
            "y": m.y,
            "width": m.width,
            "height": m.height,
            "width_mm": m.width_mm,
            "height_mm": m.height_mm,
            "is_primary": bool(m.is_primary),
        })
    return monitors


class MetadataManager:
    """
    Builds metadata.json for a recording.

    Timestamps in all recording files are time.perf_counter() seconds.
    `clock` pairs a perf_counter reading with wall-clock time so any event can
    be converted: unix_time = clock.unix_time + (t - clock.perf_counter).
    """

    def __init__(self, recording_path: str, recording_id: str, natural_scrolling: bool | None = None):
        self.recording_path = recording_path
        if natural_scrolling is None:
            natural_scrolling = detect_natural_scrolling()

        uname = platform.uname()
        monitors = _monitors()
        primary = next((m for m in monitors if m["is_primary"]), monitors[0])

        self.metadata = {
            "schema_version": SCHEMA_VERSION,
            "recording_id": recording_id,
            "recorder": {"name": "cudAI", "version": RECORDER_VERSION},
            "contributor_id": get_contributor_id(),
            "consent": get_consent(),
            # Legacy flat fields read by the reducer / annotation UI.
            "system": uname.system,
            "release": uname.release,
            "version": uname.version,
            "machine": uname.machine,
            "model": _device_model(),
            "screen_width": primary["width"],
            "screen_height": primary["height"],
            "scroll_direction": -1 if natural_scrolling else 1,
            "os": {
                "name": uname.system,
                "version": _os_version(),
                "architecture": uname.machine,
            },
            "locale": _locale(),
            "keyboard_layout": _keyboard_layout(),
            "timezone": time.strftime("%Z"),
            "utc_offset_seconds": int(datetime.now().astimezone().utcoffset().total_seconds()),
            "natural_scrolling": natural_scrolling,
            "monitors": monitors,
            # Input coordinates are in the primary display's logical
            # coordinate space (points on macOS); see display.scale_factor
            # to convert to video pixels.
            "coordinate_space": "logical",
            "display": {
                "captured_monitor": primary["name"],
                "logical_width": primary["width"],
                "logical_height": primary["height"],
                "scale_factor": None,
            },
            "pauses": [],
            # Extra (perf_counter, unix_time) pairs taken after the clocks
            # diverged, i.e. after the Mac slept (perf_counter stops then).
            "clock_anchors": [],
            "system_sleeps": [],
        }

    def collect(self):
        now = datetime.now().astimezone()
        self.metadata["start_time"] = now.isoformat()
        self.metadata["clock"] = {
            "perf_counter": time.perf_counter(),
            "unix_time": time.time(),
        }

    def end_collect(self):
        self.metadata["stop_time"] = datetime.now().astimezone().isoformat()

    def add_clock_anchor(self, perf: float, unix: float, slept_seconds: float):
        self.metadata["clock_anchors"].append({"perf_counter": perf, "unix_time": unix})
        self.metadata["system_sleeps"].append(
            {"resumed_at": perf, "slept_seconds": round(slept_seconds, 1)}
        )

    def add_pause(self, start: float, end: float | None = None):
        self.metadata["pauses"].append({"start_timestamp": start, "end_timestamp": end})

    def end_pause(self, end: float):
        if self.metadata["pauses"] and self.metadata["pauses"][-1]["end_timestamp"] is None:
            self.metadata["pauses"][-1]["end_timestamp"] = end

    def set_displays(self, displays: list):
        """All displays captured in this recording (one video per display)."""
        self.metadata["displays"] = [{**d, "video": None} for d in displays]

    def set_display_videos(self, videos: list):
        by_index = {v["display_index"]: v for v in videos}
        for display in self.metadata.get("displays", []):
            display["video"] = by_index.get(display["index"])

    def set_video(self, video: dict):
        self.metadata["video"] = video
        self.metadata["video_start_timestamp"] = video["video_start_timestamp"]
        if video.get("width") and self.metadata["display"]["logical_width"]:
            self.metadata["display"]["scale_factor"] = (
                video["width"] / self.metadata["display"]["logical_width"]
            )

    def save_metadata(self):
        metadata_path = os.path.join(self.recording_path, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=4, ensure_ascii=False)
