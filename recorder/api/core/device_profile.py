"""
How much work this Mac can take while someone is working on it.

A tier is chosen from the hardware and decides the capture resolution and
frame rate, and how hard on-device redaction may push the CPU:

  high      Apple Silicon Pro/Max (>= 5 performance cores, >= 16 GB)
  standard  other Apple Silicon (base M1-M4)
  low       Intel Macs, or 8 GB of memory or less

On battery, redaction uses one thread fewer. If redaction fell far behind in
the last recording, the next one starts a tier lower. The tier used is saved
with each recording (metadata.capture_profile, manifest.capture_profile).
Override with CUDAI_TIER=high|standard|low or the Settings page.
"""

import json
import os
import platform
import subprocess
from dataclasses import asdict, dataclass

TIERS = ("high", "standard", "low")
BACKLOG_DOWNGRADE_SECONDS = 120


@dataclass(frozen=True)
class Profile:
    tier: str
    capture_scale: str  # "native" (Retina pixels) or "logical" (points)
    fps: int
    ocr_threads: int
    min_ocr_interval_seconds: float  # at most this often per chunk region
    analysis_max_side: int  # OCR resolution, longest side in pixels
    window_poll_seconds: float
    url_poll_seconds: float


PROFILES = {
    "high": Profile("high", "native", 30, 4, 0.5, 1600, 0.2, 1.0),
    "standard": Profile("standard", "logical", 30, 3, 0.5, 1600, 0.25, 1.5),
    # OCR never runs below screen resolution: smaller text gets misread.
    "low": Profile("low", "logical", 15, 2, 1.0, 1600, 0.5, 2.0),
}


def _sysctl(name: str) -> int | None:
    try:
        return int(subprocess.run(["sysctl", "-n", name], capture_output=True, text=True).stdout.strip())
    except (ValueError, OSError):
        return None


def hardware() -> dict:
    performance_cores = _sysctl("hw.perflevel0.physicalcpu") or _sysctl("hw.physicalcpu") or 2
    # sysctl.proc_translated is 1 when this process runs under Rosetta.
    apple_silicon = platform.machine() == "arm64" or _sysctl("sysctl.proc_translated") == 1
    return {
        "apple_silicon": apple_silicon,
        "performance_cores": performance_cores,
        "memory_gb": round((_sysctl("hw.memsize") or 0) / 2**30, 1),
        "on_battery": on_battery(),
    }


def on_battery() -> bool:
    try:
        return "Battery Power" in subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True).stdout
    except OSError:
        return False


def hardware_tier(hw: dict) -> str:
    if not hw["apple_silicon"] or hw["memory_gb"] <= 8:
        return "low"
    if hw["performance_cores"] >= 5 and hw["memory_gb"] >= 16:
        return "high"
    return "standard"


def _state_path() -> str:
    from .utils import get_app_data_dir

    return str(get_app_data_dir() / "device_profile.json")


def _load_state() -> dict:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def set_override(tier: str | None) -> None:
    """Tier chosen in Settings (None: automatic)."""
    if tier is not None and tier not in TIERS:
        raise ValueError(f"unknown tier {tier}")
    state = _load_state()
    state["override"] = tier
    _save_state(state)


def report_backlog(seconds: float) -> None:
    """Called when redaction falls behind; the next recording goes a tier lower."""
    if seconds >= BACKLOG_DOWNGRADE_SECONDS:
        state = _load_state()
        state["downgrade"] = True
        _save_state(state)


def current(hw: dict | None = None, consume_downgrade: bool = False) -> dict:
    """The profile for the next recording, with why it was chosen."""
    hw = hw or hardware()
    state = _load_state()
    tier = os.environ.get("CUDAI_TIER") or state.get("override") or hardware_tier(hw)
    reason = "override" if (os.environ.get("CUDAI_TIER") or state.get("override")) else "hardware"
    if state.get("downgrade") and reason == "hardware" and tier != "low":
        tier = TIERS[TIERS.index(tier) + 1]
        reason = "redaction fell behind last time"
        if consume_downgrade:
            state["downgrade"] = False
            _save_state(state)
    profile = PROFILES[tier]
    threads = max(1, profile.ocr_threads - (1 if hw["on_battery"] else 0))
    return {**asdict(profile), "ocr_threads": threads, "reason": reason, "hardware": hw}
