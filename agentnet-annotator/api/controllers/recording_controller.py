"""Recording controller for handling recording-related HTTP endpoints."""

import os

from flask import request, send_file
from typing import Tuple, Dict, Any

from core.backend_func import annotate_task
from core.utils import RECORDING_DIR
from services.recording_service import RecordingService
from services.file_service import FileService
from services.error_handler import ErrorHandler, handle_api_errors, Validator


class RecordingController:
    """Controller for recording-related endpoints."""

    def __init__(self, recording_service: RecordingService, file_service: FileService, socketio):
        self.recording_service = recording_service
        self.file_service = file_service
        self.socketio = socketio

    @handle_api_errors
    def get_user_recordings_list(self) -> Tuple[Dict[str, Any], int]:
        """Get list of user recordings."""
        recordings_data = self.recording_service.get_user_recordings()
        return ErrorHandler.create_success_response(recordings_data)

    @handle_api_errors
    def get_single_user_recording(self, recording_name: str) -> Tuple[Dict[str, Any], int]:
        """Get details of a single user recording."""
        Validator.validate_recording_name(recording_name)

        status, data = self.recording_service.get_single_recording(recording_name)
        return ErrorHandler.handle_service_response((status, data))

    @handle_api_errors
    def confirm_recording(self, recording_name: str) -> Tuple[Dict[str, Any], int]:
        """Confirm and save recording modifications."""
        Validator.validate_recording_name(recording_name)

        if not request.json:
            return ErrorHandler.create_error_response("No data provided", 400)

        events_data = request.json
        if not isinstance(events_data, list):
            return ErrorHandler.create_error_response("Events data must be a list", 400)

        status, message = self.recording_service.confirm_recording(recording_name, events_data)
        return ErrorHandler.handle_service_response((status, message))

    @handle_api_errors
    def annotate_task_endpoint(self, recording_name: str) -> Tuple[Dict[str, Any], int]:
        """Create annotation task for recording."""
        Validator.validate_recording_name(recording_name)

        # Use existing function but wrap in error handling
        try:
            result = annotate_task(recording_name=recording_name, socketservice=self.socketio)
            return result
        except Exception as e:
            return ErrorHandler.create_error_response(f"Failed to annotate task: {str(e)}")

    @handle_api_errors
    def get_review(self, recording_name: str) -> Tuple[Dict[str, Any], int]:
        """Review screen payload: actions, event timeline, video and details."""
        Validator.validate_recording_name(recording_name)
        status, data = self.recording_service.get_review(recording_name)
        return ErrorHandler.handle_service_response((status, data))

    @handle_api_errors
    def stream_video(self, recording_name: str):
        """Full recording video with HTTP range support (seekable player)."""
        Validator.validate_recording_name(recording_name)
        path = os.path.join(RECORDING_DIR, recording_name, "video.mp4")
        if not os.path.exists(path):
            return ErrorHandler.create_error_response("Video not found", 404)
        return send_file(path, mimetype="video/mp4", conditional=True, max_age=0)

    @handle_api_errors
    def update_task(self, recording_name: str) -> Tuple[Dict[str, Any], int]:
        Validator.validate_recording_name(recording_name)
        data = request.json or {}
        Validator.validate_required_fields(data, ["task_name"])
        if not str(data["task_name"]).strip():
            return ErrorHandler.create_error_response("Task name is required", 400)
        status, message = self.recording_service.update_task(
            recording_name, str(data["task_name"]), data.get("description", "")
        )
        return ErrorHandler.handle_service_response((status, message))
