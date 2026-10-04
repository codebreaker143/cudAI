"""Socket.IO events for controlling a recording. Each event replies on the same name."""

from flask_socketio import emit

from core.constants import FAILED
from core.logger import logger
from services.error_handler import Validator
from services.recording_service import RecordingService


class WebSocketController:
    def __init__(self, recording_service: RecordingService):
        self.recording_service = recording_service

    def _reply(self, event: str, action) -> None:
        try:
            status, message = action()
        except Exception as e:
            logger.exception(f"WebSocketController: {event} failed")
            status, message = FAILED, f"Unexpected error: {e}"
        emit(event, {"status": status, "message": message})

    def start_record(self, data: dict = None) -> None:
        self._reply("start_record", self.recording_service.start_recording)

    def stop_record(self, data: dict = None) -> None:
        self._reply("stop_record", self.recording_service.stop_recording)

    def pause_record(self, data: dict = None) -> None:
        """Pause: stops screen capture and input logging until resumed."""
        self._reply("pause_record", self.recording_service.pause_recording)

    def resume_record(self, data: dict = None) -> None:
        self._reply("resume_record", self.recording_service.resume_recording)

    def toggle_generate_window_a11y(self, data: dict) -> None:
        """Enable/disable full-window accessibility snapshots for the next recording."""
        try:
            flag = Validator.validate_boolean_flag((data or {}).get("flag"), "flag")
            self.recording_service.toggle_window_a11y(flag)
        except Exception:
            logger.exception("WebSocketController: toggle_generate_window_a11y failed")

    def setup_events(self, socketio) -> None:
        for event in (
            "start_record",
            "stop_record",
            "pause_record",
            "resume_record",
            "toggle_generate_window_a11y",
        ):
            socketio.on_event(event, getattr(self, event))
