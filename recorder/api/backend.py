"""Refactored Backend with modular architecture."""

import sys

if __name__ == "__main__" and "--redaction-worker" in sys.argv:
    # OCR/redaction worker process (core/redaction.py); none of the server.
    from core.redaction import worker_main

    worker_main()
    sys.exit(0)

import os
import signal
from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

from core.logger import logger
from core.security import install_api_token_guard
from core.utils import migrate_legacy_recordings
from services.config_service import ConfigService
from services.recording_service import RecordingService
from controllers.recording_controller import RecordingController
from controllers.websocket_controller import WebSocketController
from controllers.system_controller import SystemController

import importlib

# Imported for its side effect: registers the gevent async driver. PyInstaller
# cannot see this import; it is listed in hiddenimports (backend.spec/build.py).
importlib.import_module("engineio.async_drivers.gevent")


class CudaiBackend:
    """cudAI recorder backend."""

    def __init__(self):
        logger.info("Backend: Initializing modular backend")

        # Initialize configuration
        self.config = ConfigService()

        # Initialize Flask app and SocketIO
        self.app = Flask(__name__)
        CORS(self.app)
        self.socketio = SocketIO(
            self.app,
            cors_allowed_origins=self.config.server.cors_origins,
            async_mode="gevent",
        )
        install_api_token_guard(self.app, self.socketio)

        # Initialize services
        self._initialize_services()

        # Initialize controllers
        self._initialize_controllers()

        # Setup routes and WebSocket events
        self._setup_routes()
        self._setup_websocket_events()

        logger.info("Backend: Initialization completed")

    def _initialize_services(self):
        """Initialize all service instances."""
        self.recording_service = RecordingService(self.socketio)

    def _initialize_controllers(self):
        """Initialize all controller instances."""
        self.recording_controller = RecordingController(
            self.recording_service, self.socketio
        )
        self.websocket_controller = WebSocketController(self.recording_service)
        self.system_controller = SystemController(self.recording_service)

    def _setup_routes(self):
        routes = [
            # System Endpoints
            ("/api/permissions", self.system_controller.check_permissions),
            ("/api/permissions/request", self.system_controller.request_permission, {"methods": ["POST"]}),
            ("/api/consent", self.system_controller.get_consent),
            ("/api/consent", self.system_controller.set_consent, {"methods": ["POST"]}),
            ("/api/recording/status", self.system_controller.recording_status),
            ("/api/recording/pause", self.system_controller.pause_recording, {"methods": ["POST"]}),
            ("/api/system/info", self.system_controller.system_info),
            ("/api/upload/status", self.system_controller.upload_status),
            ("/api/upload/config", self.system_controller.set_upload_config, {"methods": ["PUT"]}),
            # Recording Endpoints
            ("/api/recordings", self.recording_controller.get_user_recordings_list),
            ("/api/recording/<recording_name>/review", self.recording_controller.get_review),
            ("/api/recording/<recording_name>/video.mp4", self.recording_controller.stream_video),
            ("/api/recording/<recording_name>/timings", self.recording_controller.get_timings),
            ("/api/recording/<recording_name>/task", self.recording_controller.update_task, {"methods": ["POST"]}),
            # Recording Operations
            ("/api/recording/<recording_name>/confirm", self.recording_controller.confirm_recording, {"methods": ["POST"]}),
            ("/api/recording/<recording_name>/cut", self.recording_controller.annotate_task_endpoint, {"methods": ["POST"]}),
            # Local Operations
        ]

        for route_info in routes:
            path, handler = route_info[:2]
            kwargs = route_info[2] if len(route_info) > 2 else {}
            self.app.route(path, **kwargs)(handler)

    def _setup_websocket_events(self):
        """Setup WebSocket event handlers."""
        self.websocket_controller.setup_events(self.socketio)

    def run(self, debug=None, host=None, port=None):
        """Run the Flask application."""
        # Use config defaults if not specified
        debug = debug if debug is not None else self.config.server.debug
        host = host if host is not None else self.config.server.host
        port = port if port is not None else self.config.server.port

        self.socketio.run(
            self.app, debug=debug, host=host, port=port, allow_unsafe_werkzeug=True
        )

    def quit(self):
        """Gracefully shutdown the backend."""
        try:
            logger.info("Backend: Starting graceful shutdown")

            # Stop recording if active
            if hasattr(self.recording_service, "recorder_thread"):
                self.recording_service.stop_recording()

            # Stop SocketIO
            if hasattr(self, "socketio"):
                self.socketio.stop()

            # Shutdown Flask
            if hasattr(self, "app"):
                func = os.environ.get("werkzeug.server.shutdown")
                if func is not None:
                    func()

            logger.info("Backend: Graceful shutdown completed")

        except Exception as e:
            logger.exception(f"Backend: Error during shutdown: {e}")


def create_signal_handler(backend: CudaiBackend):
    """Create signal handler for graceful shutdown."""

    def signal_handler(sig, frame):
        logger.info("\nReceived SIGINT (Ctrl+C)")
        logger.info("Do you want to terminate the application? (Y/N)")
        try:
            choice = input().strip().lower()
            if choice == "y":
                logger.info("Shutting down the application...")
                backend.quit()
                os._exit(0)
            else:
                logger.info("Continuing to run the application.")
        except (EOFError, KeyboardInterrupt):
            # Handle case where input is not available or interrupted
            logger.info("Shutting down the application...")
            backend.quit()
            os._exit(0)

    return signal_handler


def main():
    """Main entry point for the application."""
    try:
        migrate_legacy_recordings()
        backend = CudaiBackend()

        # Setup signal handler
        signal.signal(signal.SIGINT, create_signal_handler(backend))

        logger.info("Backend started. Press CTRL+C to shut down the app.")
        server_config = backend.config.get_server_config()
        backend.run(
            debug=False,  # Override config for production
            host=server_config.host,
            port=5328,  # Keep original port
        )

    except Exception as e:
        logger.exception(f"Application error: {e}")
    finally:
        if "backend" in locals():
            backend.quit()
        os._exit(0)


if __name__ == "__main__":
    main()
