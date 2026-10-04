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
    running_app_pids,
)
from .logger import logger


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

    def __init__(self, generate_window_a11y, generate_element_a11y):
        self._element_queue = Queue()
        self.gen_element = generate_element_a11y
        self.running = False
        self.paused = False
        self.recorder_pid = get_recorder_app_pid()
        self._accessibility_enabled = set()

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

    def _get_top_window(self):
        last_key = None

        while self.running:
            try:
                if self.paused:
                    # Force a fresh record on resume.
                    last_key = None
                    time.sleep(self.POLL_INTERVAL)
                    continue

                info = get_active_app_info()
                if info is not None:
                    info["app_name"] = clean_text(info["app_name"])
                    info["window_title"] = clean_text(info["window_title"])
                    self._enable_accessibility(info["pid"])
                    key = (info["pid"], info["window_title"])
                    if key != last_key:
                        info["is_recorder"] = (
                            self.recorder_pid is not None
                            and info["pid"] == self.recorder_pid
                        )
                        self._top_window_queue.put(
                            {
                                "time_stamp": time.perf_counter(),
                                # Kept for compatibility with older readers.
                                "top_window_name": info["app_name"],
                                **info,
                            }
                        )
                        last_key = key
            except Exception:
                logger.exception("a11y_listener _get_top_window error.")
            time.sleep(self.POLL_INTERVAL)

    def _enable_accessibility(self, pid: int) -> None:
        if pid in self._accessibility_enabled or pid == self.recorder_pid:
            return
        self._accessibility_enabled.add(pid)
        try:
            enable_full_accessibility(pid)
        except Exception:
            logger.debug(f"a11y_listener: could not enable accessibility for pid {pid}")

    def start(self):
        # Before the first click, so web content trees have time to build.
        for pid in running_app_pids():
            self._enable_accessibility(pid)
        self.running = True
        self.mouse_listener.start()
        self.top_window_getter.start()

    def stop(self):
        self.running = False
        self.mouse_listener.stop()
        self.top_window_getter.join()

    @property
    def element_queue(self):
        return self._element_queue

    @property
    def top_window_queue(self):
        return self._top_window_queue
