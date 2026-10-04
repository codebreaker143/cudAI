"""System controller for handling system-level endpoints."""

from flask import request
from typing import Tuple, Dict, Any
from core.backend_func import save_task
from core.permissions import check_permissions, request_permission
from core.consent import CONSENT_VERSION, get_consent, get_contributor_id, record_consent
from core.constants import RECORDER_VERSION, SCHEMA_VERSION
from core.utils import RECORDING_DIR, get_app_data_dir
from services.error_handler import ErrorHandler, handle_api_errors, Validator
from services.recording_service import RecordingService


class SystemController:
    """Controller for system-level endpoints."""

    def __init__(self, recording_service: RecordingService):
        self.recording_service = recording_service

    @handle_api_errors
    def check_permissions(self) -> Tuple[Dict[str, Any], int]:
        """Status of the macOS permissions a complete recording needs."""
        return ErrorHandler.create_success_response(check_permissions())

    @handle_api_errors
    def request_permission(self) -> Tuple[Dict[str, Any], int]:
        data = request.json or {}
        Validator.validate_required_fields(data, ["name"])
        request_permission(str(data["name"]))
        return ErrorHandler.create_success_response(check_permissions())

    @handle_api_errors
    def get_consent(self) -> Tuple[Dict[str, Any], int]:
        consent = get_consent()
        return ErrorHandler.create_success_response(
            {
                "current_version": CONSENT_VERSION,
                "consent": consent,
                "accepted": bool(
                    consent
                    and consent.get("accepted")
                    and consent.get("version") == CONSENT_VERSION
                ),
            }
        )

    @handle_api_errors
    def set_consent(self) -> Tuple[Dict[str, Any], int]:
        """Accept the current terms. Consent cannot be declined or withdrawn."""
        data = request.json or {}
        Validator.validate_required_fields(data, ["accepted", "version"])
        if data["version"] != CONSENT_VERSION:
            return ErrorHandler.create_error_response(
                "Terms have changed; please review the current version", 409
            )
        if not Validator.validate_boolean_flag(data["accepted"], "accepted"):
            return ErrorHandler.create_error_response(
                "Accepting the terms is required to use cudAI", 400
            )
        return ErrorHandler.create_success_response({"consent": record_consent()})

    @handle_api_errors
    def system_info(self) -> Tuple[Dict[str, Any], int]:
        return ErrorHandler.create_success_response(
            {
                "version": RECORDER_VERSION,
                "schema_version": SCHEMA_VERSION,
                "data_dir": str(get_app_data_dir()),
                "recordings_dir": RECORDING_DIR,
                "contributor_id": get_contributor_id(),
            }
        )

    @handle_api_errors
    def recording_status(self) -> Tuple[Dict[str, Any], int]:
        return ErrorHandler.create_success_response(
            self.recording_service.get_status()
        )

    @handle_api_errors
    def save_task_endpoint(self) -> Tuple[Dict[str, Any], int]:
        """Save task data."""
        try:
            return save_task()
        except Exception as e:
            return ErrorHandler.create_error_response(
                f"Failed to save task: {str(e)}"
            )
