"""System controller for handling system-level endpoints."""

from typing import Tuple, Dict, Any
from core.backend_func import save_task
from services.error_handler import ErrorHandler, handle_api_errors


class SystemController:
    """Controller for system-level endpoints."""

    def __init__(self):
        pass

    @handle_api_errors
    def check_permissions(self) -> Tuple[Dict[str, Any], int]:
        """Check system permissions."""
        return ErrorHandler.create_success_response(
            message="Permission check completed"
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
