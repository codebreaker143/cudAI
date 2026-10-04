"""WebSocket controller for handling real-time events."""

import time
from flask_socketio import emit

from core.logger import logger
from core.a11y import get_accessibility_tree
from services.recording_service import RecordingService
from services.file_service import AccessibilityService
from services.error_handler import Validator
from core.constants import SUCCEED, FAILED


class WebSocketController:
    """Controller for WebSocket events."""

    def __init__(self, recording_service: RecordingService):
        self.recording_service = recording_service
        self.accessibility_service = AccessibilityService()

    def start_record(self, data: dict = None) -> None:
        """Handle start recording WebSocket event."""
        logger.info("WebSocketController: start_record")

        try:
            status, message = self.recording_service.start_recording()

            if (
                self.recording_service.recorder_thread
                and hasattr(
                    self.recording_service.recorder_thread,
                    "recording_path",
                )
            ):
                self.accessibility_service.set_active_recording(
                    self.recording_service.recorder_thread.recording_path
                )

            emit(
                "start_record",
                {
                    "status": status,
                    "message": message,
                },
            )

        except Exception as e:
            logger.exception("WebSocketController: start_record failed")
            emit(
                "start_record",
                {
                    "status": FAILED,
                    "message": f"Failed to start recording: {str(e)}",
                },
            )

    def stop_record(self, data: dict = None) -> None:
        """Handle stop recording WebSocket event."""
        logger.info("WebSocketController: stop_record")

        try:
            status, message = self.recording_service.stop_recording()

            emit(
                "stop_record",
                {
                    "status": status,
                    "message": message,
                },
            )

        except Exception as e:
            logger.exception("WebSocketController: stop_record failed")
            emit(
                "stop_record",
                {
                    "status": FAILED,
                    "message": f"Failed to stop recording: {str(e)}",
                },
            )

    def pause_record(self, data: dict = None) -> None:
        """Pause: stops screen capture and input logging until resumed."""
        status, message = self.recording_service.pause_recording()
        emit("pause_record", {"status": status, "message": message})

    def resume_record(self, data: dict = None) -> None:
        status, message = self.recording_service.resume_recording()
        emit("resume_record", {"status": status, "message": message})

    def get_axtree(self, data: dict = None) -> None:
        """Handle accessibility tree request."""
        try:
            start_time = time.time()

            axtree_data = get_accessibility_tree()

            status, message = (
                self.accessibility_service.save_accessibility_tree(
                    axtree_data
                )
            )

            logger.info(
                "WebSocketController: get_axtree completed in "
                f"{time.time() - start_time:.2f}s"
            )

            emit(
                "get_axtree",
                {
                    "status": (
                        "succeed"
                        if status == SUCCEED
                        else "failed"
                    )
                },
            )

        except Exception:
            logger.exception(
                "WebSocketController: get_axtree failed"
            )

            emit(
                "get_axtree",
                {"status": "failed"},
            )

    def toggle_generate_window_a11y(
        self,
        data: dict,
    ) -> None:
        """Handle toggle window accessibility generation."""
        try:
            if (
                not isinstance(data, dict)
                or "flag" not in data
            ):
                logger.warning(
                    "WebSocketController: Invalid data for "
                    "toggle_generate_window_a11y"
                )
                return

            flag = Validator.validate_boolean_flag(
                data["flag"],
                "flag",
            )

            self.recording_service.toggle_window_a11y(
                flag
            )

        except Exception:
            logger.exception(
                "WebSocketController: "
                "toggle_generate_window_a11y failed"
            )

    def setup_events(
        self,
        socketio,
    ) -> None:
        """Setup WebSocket event handlers."""

        socketio.on_event(
            "start_record",
            self.start_record,
        )

        socketio.on_event(
            "stop_record",
            self.stop_record,
        )

        socketio.on_event(
            "pause_record",
            self.pause_record,
        )

        socketio.on_event(
            "resume_record",
            self.resume_record,
        )

        socketio.on_event(
            "get_axtree",
            self.get_axtree,
        )

        socketio.on_event(
            "toggle_generate_window_a11y",
            self.toggle_generate_window_a11y,
        )
