"""
macOS privacy permissions required for a complete recording.

Missing permissions fail silently on macOS: without Screen Recording the video
shows only the desktop, without Input Monitoring no mouse/keyboard events are
delivered, and without Accessibility clicked UI elements cannot be read. So we
check them explicitly and refuse to record until all are granted.

Note: macOS often keeps reporting "denied" to a running process after the user
grants a permission; the app must be restarted to pick it up.
"""

from platform import system

from .logger import logger

PERMISSIONS = {
    "screen_recording": {
        "label": "Screen Recording",
        "reason": "Records the video of your screen.",
        "settings_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    },
    "input_monitoring": {
        "label": "Input Monitoring",
        "reason": "Records mouse clicks, scrolling and keystrokes.",
        "settings_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    },
    "accessibility": {
        "label": "Accessibility",
        "reason": "Identifies the buttons, fields and windows you interact with.",
        "settings_url": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    },
}


def _is_granted(name: str) -> bool:
    if system() != "Darwin":
        return True
    try:
        import ApplicationServices
        import Quartz

        if name == "screen_recording":
            return bool(Quartz.CGPreflightScreenCaptureAccess())
        if name == "input_monitoring":
            return bool(Quartz.CGPreflightListenEventAccess())
        if name == "accessibility":
            return bool(ApplicationServices.AXIsProcessTrusted())
    except Exception:
        logger.exception(f"permissions: could not check {name}")
    return False


def check_permissions() -> dict:
    """{name: {label, reason, settings_url, granted}} plus an overall flag."""
    items = {
        name: {**info, "granted": _is_granted(name)} for name, info in PERMISSIONS.items()
    }
    return {"all_granted": all(i["granted"] for i in items.values()), "permissions": items}


def missing_permissions() -> list:
    return [i["label"] for i in check_permissions()["permissions"].values() if not i["granted"]]


def request_permission(name: str) -> None:
    """Show the macOS prompt (only shown once per app; afterwards use Settings)."""
    if system() != "Darwin" or name not in PERMISSIONS:
        return
    import ApplicationServices
    import Quartz

    if name == "screen_recording":
        Quartz.CGRequestScreenCaptureAccess()
    elif name == "input_monitoring":
        Quartz.CGRequestListenEventAccess()
    elif name == "accessibility":
        ApplicationServices.AXIsProcessTrustedWithOptions(
            {ApplicationServices.kAXTrustedCheckOptionPrompt: True}
        )
