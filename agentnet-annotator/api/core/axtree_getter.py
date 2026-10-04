"""
Full-window accessibility snapshots at "key frames" (optional; off by default).

A snapshot is taken after a click, after scrolling stops, and when the screen
settles after a large visual change. Requests arriving while a snapshot is
being taken are coalesced into one follow-up snapshot.
"""

import threading
import time
from platform import system
from queue import Queue

import mss
import numpy as np
from pynput import mouse

from .a11y import get_accessibility_tree, get_top_window_name
from .logger import logger

# Browsers expose huge trees; their pages are better captured another way.
BROWSERS = {
    "Darwin": {"Microsoft Edge", "Google Chrome", "Arc", "Safari", "Firefox"},
    "Windows": {"msedge", "chrome", "firefox"},
}

SAMPLE_INTERVAL = 0.15  # seconds between screen samples
DOWNSCALE = 8  # compare every 8th pixel in each direction
BIG_CHANGE = 0.4  # fraction of pixels changed => something happened
SETTLED = 0.01  # fraction changed => screen is stable
SETTLED_SAMPLES = 3
SETTLE_DELAY = 0.3  # let the UI react to a click before snapshotting


class KeyFrameDetector:
    def __init__(self, socketio):
        self.socketio = socketio
        self.axtree_queue = Queue()
        self.running = False
        self.paused = False
        self._requested = threading.Event()
        self._scrolling = False
        self._sampler = threading.Thread(target=self._detect_visual_keyframes, daemon=True)
        self._worker = threading.Thread(target=self._snapshot_worker, daemon=True)
        self._mouse = mouse.Listener(on_click=self._on_click, on_scroll=self._on_scroll, on_move=self._on_move)

    # Triggers -----------------------------------------------------------

    def _on_click(self, x, y, button, pressed):
        if not pressed:
            self.request_snapshot()

    def _on_scroll(self, x, y, dx, dy):
        self._scrolling = True

    def _on_move(self, x, y):
        if self._scrolling:
            self._scrolling = False
            self.request_snapshot()

    def request_snapshot(self):
        if self.running and not self.paused:
            self._requested.set()

    def _detect_visual_keyframes(self):
        previous = None
        changed, stable = False, 0
        with mss.mss() as screen:
            monitor = screen.monitors[1]
            while self.running:
                time.sleep(SAMPLE_INTERVAL)
                if self.paused:
                    previous = None
                    continue
                frame = np.asarray(screen.grab(monitor))[::DOWNSCALE, ::DOWNSCALE, :3]
                if previous is not None:
                    ratio = float(np.mean(np.any(frame != previous, axis=-1)))
                    if ratio > BIG_CHANGE:
                        changed, stable = True, 0
                    elif changed and ratio < SETTLED:
                        stable += 1
                        if stable >= SETTLED_SAMPLES:
                            self.request_snapshot()
                            changed, stable = False, 0
                previous = frame

    # Snapshot ------------------------------------------------------------

    def _snapshot_worker(self):
        while self.running:
            if not self._requested.wait(timeout=0.5):
                continue
            self._requested.clear()
            time.sleep(SETTLE_DELAY)
            if self.running and not self.paused:
                self._save_snapshot()

    def _save_snapshot(self):
        if get_top_window_name() in BROWSERS.get(system(), set()):
            logger.debug("KeyFrameDetector: browser in front, skipping snapshot")
            return
        self.socketio.emit("axtree", {"status": "start"})
        time_stamp = time.perf_counter()
        try:
            tree = get_accessibility_tree()
            if tree is not None:
                tree["time_stamp"] = time_stamp
                self.axtree_queue.put({"time_stamp": time_stamp, "axtree": tree})
                logger.info(
                    f"KeyFrameDetector: snapshot in {time.perf_counter() - time_stamp:.2f}s"
                )
        except Exception:
            logger.exception("KeyFrameDetector: snapshot failed")
        finally:
            self.socketio.emit("axtree", {"status": "end"})

    # Lifecycle ------------------------------------------------------------

    def start(self):
        self.running = True
        self._mouse.start()
        self._sampler.start()
        self._worker.start()

    def stop(self):
        self.running = False
        self._mouse.stop()
        self._sampler.join()
        self._worker.join()
