import os
import re
import time

from pynput import mouse
from queue import Queue
from threading import Thread

from .a11y import (
    enable_full_accessibility,
    get_active_app_info,
    get_active_element_data,
    get_browser_url,
    is_browser,
    restore_accessibility,
    running_apps,
)
from .logger import logger
from .privacy import redact_text
from .url_privacy import sanitize_url


# Invisible direction marks some apps put in their names ("\u200eWhatsApp").
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def clean_text(value):
    return _INVISIBLE.sub("", value).strip() if isinstance(value, str) else value


def get_recorder_app_pid() -> int | None:
    """PID of the cudAI desktop app, whose own windows must not be recorded."""
    pid = os.environ.get("CUDAI_APP_PID")
    return int(pid) if pid and pid.isdigit() else None


class A11yListener:
    POLL_INTERVAL = 0.2
    URL_INTERVAL = 1.0  # single-page apps change URL without changing the title

    def __init__(self, generate_window_a11y, generate_element_a11y,
                 poll_interval: float | None = None, url_interval: float | None = None):
        if poll_interval:
            self.POLL_INTERVAL = poll_interval
        if url_interval:
            self.URL_INTERVAL = url_interval
        self._element_queue = Queue()
        self.gen_element = generate_element_a11y
        self.running = False
        self.paused = False
        self.recorder_pid = get_recorder_app_pid()
        # pid -> attribute values to restore when recording stops
        self._accessibility_enabled = {}

        self.mouse_listener = mouse.Listener(on_click=self.on_click)
        self._top_window_queue = Queue()

        self.top_window_getter = Thread(target=self._get_top_window, daemon=True)

    def on_click(self, x, y, button, pressed):
        if pressed and not self.paused:
            timestamp = time.perf_counter()
            if self.gen_element:
                Thread(
                    target=self._enqueue_element_data, args=(timestamp, x, y)
                ).start()

    def _enqueue_element_data(self, timestamp, x, y):
        self._element_queue.put(
            {"time_stamp": timestamp, "a11y_tree": get_active_element_data(x, y)},
            block=False,
        )

    # A window/page change must hold for this many polls to be recorded, which
    # filters flicker from transient windows. It is timestamped when first seen.
    STABLE_POLLS = 2

    def _get_top_window(self):
        last_key = None
        pending_key, pending_since, pending_count = None, None, 0
        # Cached page URL, the (pid, title) it was read for, and when.
        url, url_window, url_checked_at = None, None, 0.0

        while self.running:
            try:
                if self.paused:
                    # Force a fresh record on resume.
                    last_key, pending_key = None, None
                    time.sleep(self.POLL_INTERVAL)
                    continue

                info = get_active_app_info()
                if info is not None:
                    info["app_name"] = clean_text(info["app_name"])
                    info["window_title"] = redact_text(clean_text(info["window_title"]))
                    self._enable_accessibility(info["pid"], info["bundle_id"])
                    if is_browser(info["bundle_id"]) or info["bundle_id"] == "com.apple.Safari":
                        window = (info["pid"], info["window_title"])
                        now = time.monotonic()
                        if window != url_window or now - url_checked_at >= self.URL_INTERVAL:
                            url = sanitize_url(get_browser_url(info["pid"]))
                            url_window, url_checked_at = window, now
                        info["url"] = url
                    key = (info["pid"], info["window_title"], info.get("url"))
                    if key == last_key:
                        pending_key = None
                    elif key != pending_key:
                        pending_key, pending_since, pending_count = key, time.perf_counter(), 1
                    else:
                        pending_count += 1
                    if pending_key is not None and pending_count >= self.STABLE_POLLS:
                        info["is_recorder"] = (
                            self.recorder_pid is not None
                            and info["pid"] == self.recorder_pid
                        )
                        self._top_window_queue.put(
                            {
                                "time_stamp": pending_since,
                                # Kept for compatibility with older readers.
                                "top_window_name": info["app_name"],
                                **info,
                            }
                        )
                        last_key, pending_key = key, None
            except Exception:
                logger.exception("a11y_listener _get_top_window error.")
            time.sleep(self.POLL_INTERVAL)

    def _enable_accessibility(self, pid: int, bundle_id: str | None) -> None:
        if pid in self._accessibility_enabled or pid == self.recorder_pid:
            return
        try:
            self._accessibility_enabled[pid] = enable_full_accessibility(pid, bundle_id)
        except Exception:
            self._accessibility_enabled[pid] = {}
            logger.debug(f"a11y_listener: could not enable accessibility for pid {pid}")

    def _restore_accessibility(self) -> None:
        for pid, previous in self._accessibility_enabled.items():
            if previous:
                try:
                    restore_accessibility(pid, previous)
                except Exception:
                    logger.debug(f"a11y_listener: could not restore accessibility for pid {pid}")
        self._accessibility_enabled = {}

    def start(self):
        # Before the first click, so web content trees have time to build.
        for pid, bundle_id in running_apps():
            self._enable_accessibility(pid, bundle_id)
        self.running = True
        self.mouse_listener.start()
        self.top_window_getter.start()

    def stop(self):
        self.running = False
        self.mouse_listener.stop()
        self.top_window_getter.join()
        self._restore_accessibility()

    @property
    def element_queue(self):
        return self._element_queue

    @property
    def top_window_queue(self):
        return self._top_window_queue
