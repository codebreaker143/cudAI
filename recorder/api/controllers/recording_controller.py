"""Recording controller for handling recording-related HTTP endpoints."""

import os

from flask import request, send_file
from typing import Tuple, Dict, Any

from core import timing
from core.backend_func import annotate_task
from core.displays import video_file_name
from core.utils import RECORDING_DIR
from services.recording_service import RecordingService
from services.error_handler import ErrorHandler, handle_api_errors, Validator


class RecordingController:
    """Controller for recording-related endpoints."""

    def __init__(self, recording_service: RecordingService, socketio):
        self.recording_service = recording_service
        self.socketio = socketio

    @handle_api_errors
    def get_user_recordings_list(self) -> Tuple[Dict[str, Any], int]:
        """Get list of user recordings."""
        recordings_data = self.recording_service.get_user_recordings()
        return ErrorHandler.create_success_response(recordings_data)

    @handle_api_errors
    def get_timings(self, recording_name: str) -> Tuple[Dict[str, Any], int]:
        """How long each pipeline step took for this recording."""
        Validator.validate_recording_name(recording_name)
        folder = os.path.join(RECORDING_DIR, recording_name)
        if not os.path.isdir(folder):
            return ErrorHandler.create_error_response("Recording not found", 404)
        lags = [
            {"chunk": row["chunk"], "lag_seconds": row["lag_seconds"]}
            for row in timing.load(folder)
            if row["stage"] == "chunk_uploaded" and "lag_seconds" in row
        ]
        return ErrorHandler.create_success_response({**timing.summary(folder), "chunk_lags": lags})

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
        try:
            display = int(request.args.get("display", 0))
        except ValueError:
            return ErrorHandler.create_error_response("Invalid display", 400)
        if display < 0:
            return ErrorHandler.create_error_response("Invalid display", 400)
        path = os.path.join(RECORDING_DIR, recording_name, video_file_name(display))
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
