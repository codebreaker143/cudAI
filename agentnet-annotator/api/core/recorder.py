import json
import os
import time
import uuid
from platform import system
from queue import Empty, Queue
from threading import Thread

from pynput import keyboard, mouse

from .metadata import MetadataManager
from .xrec_capture import XrecCapture
from .constants import MODIFIER_KEY_NAMES
from .utils import (
    fix_windows_dpi_scaling,
    get_recordings_dir,
    get_key_char,
    get_key_name,
    get_key_str,
    get_key_vk,
    init_encrpted_jsonl,
    write_encrypt_line,
)
from .a11y_listener import A11yListener
from .axtree_getter import KeyFrameDetector
from .logger import logger

_STOP = object()

# Modifiers that turn a key press into a shortcut rather than typed text.
SHORTCUT_MODIFIERS = {"ctrl", "alt", "cmd"}


class Recorder(Thread):
    """
    Records one session: screen video, input events, active window and a11y
    data. All timestamps are time.perf_counter() seconds (see metadata.clock).
    """

    FLUSH_INTERVAL = 1.0

    def __init__(
        self,
        socketio,
        natural_scrolling: bool | None = None,
        generate_window_a11y: bool = False,
        generate_element_a11y: bool = True,
    ):
        super().__init__(daemon=True)

        if system() == "Windows":
            fix_windows_dpi_scaling()
        self.socketio = socketio
        self.recording_path = self._get_recording_path()
        self._is_recording = False
        self._is_paused = False
        self._held_modifiers = set()
        self.use_a11y = system() != "Linux"
        logger.info(
            f"Gen Window: {generate_window_a11y}, Gen Element: {generate_element_a11y}"
        )

        self.event_queue = Queue()
        self.events_file = open(
            os.path.join(self.recording_path, "events.jsonl"), "a", encoding="utf-8"
        )
        self.a11y_file = self._open_jsonl("a11y.jsonl") if generate_window_a11y else None
        self.element_file = (
            self._open_jsonl("element.jsonl") if generate_element_a11y else None
        )
        self.html_file = self._open_jsonl("html.jsonl")
        self.top_window_file = self._open_jsonl("top_window.jsonl")

        self.metadata_manager = MetadataManager(
            recording_path=self.recording_path,
            recording_id=self.recording_id,
            natural_scrolling=natural_scrolling,
        )
        self.capture_client = XrecCapture(recording_path=self.recording_path)

        self.mouse_listener = mouse.Listener(
            on_move=self.on_move, on_click=self.on_click, on_scroll=self.on_scroll
        )
        self.keyboard_listener = keyboard.Listener(
            on_press=self.on_press, on_release=self.on_release
        )

        # The a11y listener also tracks the active app/window.
        self.a11y_listener = (
            A11yListener(generate_window_a11y, generate_element_a11y)
            if self.use_a11y
            else None
        )
        self.keyframe_detector = (
            KeyFrameDetector(self.socketio) if generate_window_a11y else None
        )

        self.event_count = 0

    def _open_jsonl(self, name: str):
        path = os.path.join(self.recording_path, name)
        init_encrpted_jsonl(path)
        return open(path, "a", encoding="utf-8")

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def elapsed_seconds(self) -> float:
        """Recorded (not paused) time so far."""
        clock = self.metadata_manager.metadata.get("clock")
        if not clock:
            return 0.0
        now = time.perf_counter()
        paused = sum(
            (p["end_timestamp"] or now) - p["start_timestamp"]
            for p in self.metadata_manager.metadata["pauses"]
        )
        return max(0.0, now - clock["perf_counter"] - paused)

    # Input listeners ------------------------------------------------------

    def _put(self, event: dict):
        if not self._is_paused:
            self.event_queue.put(event, block=False)

    def on_move(self, x, y):
        self._put({"time_stamp": time.perf_counter(), "action": "move", "x": x, "y": y})

    def on_click(self, x, y, button, pressed):
        self._put(
            {
                "time_stamp": time.perf_counter(),
                "action": "click",
                "x": x,
                "y": y,
                "button": button.name,
                "pressed": pressed,
            }
        )

    def on_scroll(self, x, y, dx, dy):
        self._put(
            {
                "time_stamp": time.perf_counter(),
                "action": "scroll",
                "x": x,
                "y": y,
                "dx": dx,
                "dy": dy,
            }
        )

    def _key_event(self, action: str, key) -> dict:
        timestamp = time.perf_counter()
        name = get_key_name(key)
        char = get_key_char(key)
        modifiers = sorted(self._held_modifiers)
        is_shortcut = bool(SHORTCUT_MODIFIERS & self._held_modifiers)
        return {
            "time_stamp": timestamp,
            "action": action,
            # Physical key; identical for press and release.
            "name": name,
            "vk": get_key_vk(key),
            # Character the OS produced (may be composed, e.g. "†" for ⌥T).
            "char": char,
            # Character this press contributes to typed text, if any.
            "text": char if (action == "press" and char and not is_shortcut) else None,
            # Modifiers held when the key was pressed/released (excluding itself).
            "modifiers": modifiers,
            "pynput_key": get_key_str(key),
        }

    def on_press(self, key):
        event = self._key_event("press", key)
        modifier = MODIFIER_KEY_NAMES.get(event["name"])
        if modifier:
            self._held_modifiers.add(modifier)
        self._put(event)

    def on_release(self, key):
        event = self._key_event("release", key)
        modifier = MODIFIER_KEY_NAMES.get(event["name"])
        if modifier:
            self._held_modifiers.discard(modifier)
            event["modifiers"] = sorted(self._held_modifiers)
        self._put(event)

    # Lifecycle ------------------------------------------------------------

    def run(self):
        logger.info("Recorder: run")
        last_flush = time.perf_counter()

        while True:
            try:
                event = self.event_queue.get(timeout=0.2)
            except Empty:
                event = None

            if event is _STOP:
                break
            if event is not None:
                event["event_idx"] = self.event_count
                self.event_count += 1
                self.events_file.write(json.dumps(event) + "\n")

            self._drain_aux_queues()

            if time.perf_counter() - last_flush > self.FLUSH_INTERVAL:
                self._flush()
                last_flush = time.perf_counter()

        self._drain_aux_queues()
        self._flush()
        logger.info("Recorder: run done.")

    def start_recording(self):
        """Start capture and listeners, then the writer thread."""
        self.metadata_manager.collect()
        # Saved now so an interrupted recording can be recovered; rewritten at stop.
        self.metadata_manager.save_metadata()
        video_segment = self.capture_client.start_recording()
        logger.info(f"Recorder: video starts at {video_segment['start_timestamp']}")

        self.mouse_listener.start()
        self.keyboard_listener.start()
        if self.a11y_listener:
            self.a11y_listener.start()
        if self.keyframe_detector:
            self.keyframe_detector.start()

        self._is_recording = True
        self.start()

    def _drain_aux_queues(self):
        if self.keyframe_detector:
            self._drain(self.keyframe_detector.axtree_queue, self.a11y_file)
        if self.a11y_listener:
            if self.element_file:
                self._drain(self.a11y_listener.element_queue, self.element_file)
            self._drain(self.a11y_listener.top_window_queue, self.top_window_file)

    @staticmethod
    def _drain(queue: Queue, fp):
        while not queue.empty():
            write_encrypt_line(fp, queue.get())

    def _flush(self):
        for fp in self._files():
            fp.flush()

    def _files(self):
        return [
            fp
            for fp in (
                self.events_file,
                self.a11y_file,
                self.element_file,
                self.html_file,
                self.top_window_file,
            )
            if fp is not None
        ]

    def stop_recording(self):
        logger.info("Recorder: stop_recording")
        if not self._is_recording:
            return
        requested_at = time.perf_counter()
        self._is_recording = False
        self.metadata_manager.end_collect()

        self.mouse_listener.stop()
        self.keyboard_listener.stop()
        if self.a11y_listener:
            self.a11y_listener.stop()
        if self.keyframe_detector:
            self.keyframe_detector.stop()

        if self._is_paused:
            self.metadata_manager.end_pause(requested_at)
        else:
            self.capture_client.stop_recording(requested_at)

        # Let in-flight element lookups (spawned per click) land.
        time.sleep(0.3)
        self.event_queue.put(_STOP)
        self.join()

        for fp in self._files():
            fp.close()

        try:
            self.metadata_manager.set_video(self.capture_client.finalize())
        finally:
            self.metadata_manager.save_metadata()
        logger.info("Recorder: stop_recording done.")

    def pause_recording(self) -> bool:
        if self._is_paused or not self._is_recording:
            return False
        self._is_paused = True
        if self.a11y_listener:
            self.a11y_listener.paused = True
        if self.keyframe_detector:
            self.keyframe_detector.paused = True
        now = time.perf_counter()
        # Written directly: _put() drops events while paused.
        self.event_queue.put({"time_stamp": now, "action": "pause"}, block=False)
        self.metadata_manager.add_pause(now)
        self.capture_client.pause_recording(now)
        return True

    def resume_recording(self) -> bool:
        if not self._is_paused or not self._is_recording:
            return False
        self.capture_client.resume_recording()
        now = time.perf_counter()
        self.metadata_manager.end_pause(now)
        self.event_queue.put({"time_stamp": now, "action": "resume"}, block=False)
        if self.a11y_listener:
            self.a11y_listener.paused = False
        if self.keyframe_detector:
            self.keyframe_detector.paused = False
        self._is_paused = False
        return True

    def stop(self):
        """Abort a recording that failed to start."""
        self._is_recording = False
        self.capture_client.stop_recording()

    def _get_recording_path(self) -> str:
        recordings_dir = get_recordings_dir()
        self.recording_id = str(uuid.uuid4())
        recording_path = os.path.join(recordings_dir, self.recording_id)
        os.makedirs(recording_path, exist_ok=True)
        return recording_path
