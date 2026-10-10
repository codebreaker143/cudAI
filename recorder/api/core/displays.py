"""
Connected displays, in the order FFmpeg's avfoundation numbers them
("Capture screen 0", "Capture screen 1", ...): the main display first.

Bounds are in global logical coordinates (points on macOS, origin at the top
left of the main display), the same space as mouse event coordinates, so an
event belongs to the display whose bounds contain it.
"""

from platform import system


def list_displays() -> list:
    if system() == "Darwin":
        return _darwin_displays()
    return _fallback_displays()


def _darwin_displays() -> list:
    import Quartz

    err, ids, count = Quartz.CGGetActiveDisplayList(16, None, None)
    if err or not count:
        return _fallback_displays()
    main = Quartz.CGMainDisplayID()
    displays = []
    # `index` is the position in the active display list, which is how FFmpeg
    # numbers "Capture screen N"; Apple documents that the main display is
    # first. Mirrors (e.g. a projector mirroring the laptop) show the same
    # picture and cannot be captured alongside their source, so they are
    # skipped without renumbering the others.
    for index, display_id in enumerate(ids[:count]):
        if Quartz.CGDisplayMirrorsDisplay(display_id) != Quartz.kCGNullDirectDisplay:
            continue
        bounds = Quartz.CGDisplayBounds(display_id)
        mode = Quartz.CGDisplayCopyDisplayMode(display_id)
        pixel_width = Quartz.CGDisplayModeGetPixelWidth(mode) if mode else bounds.size.width
        pixel_height = Quartz.CGDisplayModeGetPixelHeight(mode) if mode else bounds.size.height
        displays.append(
            {
                "index": index,
                "display_id": int(display_id),
                "is_main": display_id == main,
                "builtin": bool(Quartz.CGDisplayIsBuiltin(display_id)),
                "bounds": {
                    "x": bounds.origin.x,
                    "y": bounds.origin.y,
                    "width": bounds.size.width,
                    "height": bounds.size.height,
                },
                "pixel_width": int(pixel_width),
                "pixel_height": int(pixel_height),
                "scale_factor": (pixel_width / bounds.size.width) if bounds.size.width else None,
            }
        )
    return displays


def _fallback_displays() -> list:
    from screeninfo import get_monitors

    monitors = sorted(get_monitors(), key=lambda m: not m.is_primary)
    return [
        {
            "index": i,
            "display_id": None,
            "is_main": bool(m.is_primary),
            "builtin": None,
            "bounds": {"x": m.x, "y": m.y, "width": m.width, "height": m.height},
            "pixel_width": m.width,
            "pixel_height": m.height,
            "scale_factor": 1.0,
        }
        for i, m in enumerate(monitors)
    ]


def display_at(displays: list, x: float, y: float) -> int | None:
    """Index of the display containing global point (x, y)."""
    for d in displays:
        b = d["bounds"]
        if b["x"] <= x < b["x"] + b["width"] and b["y"] <= y < b["y"] + b["height"]:
            return d["index"]
    return None


def video_file_name(display_index: int) -> str:
    return "video.mp4" if display_index == 0 else f"video_display_{display_index}.mp4"


def segments_dir_name(display_index: int) -> str:
    return "segments" if display_index == 0 else f"segments_display_{display_index}"


def chunks_dir_name(display_index: int) -> str:
    """Where a display's 10-second video chunks are written (and uploaded from)."""
    return f"chunks/display_{display_index}"
