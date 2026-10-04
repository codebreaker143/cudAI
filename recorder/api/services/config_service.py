"""Configuration service for managing application settings."""

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class RecordingConfig:
    """Configuration for recording settings."""

    natural_scrolling: bool = True
    generate_window_a11y: bool = False
    generate_element_a11y: bool = True


@dataclass
class ServerConfig:
    """Configuration for server settings."""

    debug: bool = True
    # Local-only: never expose recordings to the network.
    host: str = "127.0.0.1"
    port: int = 5328
    cors_origins: str = "*"


class ConfigService:
    """Service for managing application configuration."""

    def __init__(self):
        self.recording = RecordingConfig()
        self.server = ServerConfig()

    def get_recording_config(self) -> RecordingConfig:
        """Get recording configuration."""
        return self.recording

    def get_server_config(self) -> ServerConfig:
        """Get server configuration."""
        return self.server

    def update_recording_config(self, **kwargs) -> None:
        """Update recording configuration."""
        for key, value in kwargs.items():
            if hasattr(self.recording, key):
                setattr(self.recording, key, value)

    def update_server_config(self, **kwargs) -> None:
        """Update server configuration."""
        for key, value in kwargs.items():
            if hasattr(self.server, key):
                setattr(self.server, key, value)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "recording": self.recording.__dict__,
            "server": self.server.__dict__,
        }

    def from_dict(self, config_dict: Dict[str, Any]) -> None:
        """Load configuration from dictionary."""

        if "recording" in config_dict:
            for key, value in config_dict["recording"].items():
                if hasattr(self.recording, key):
                    setattr(self.recording, key, value)

        if "server" in config_dict:
            for key, value in config_dict["server"].items():
                if hasattr(self.server, key):
                    setattr(self.server, key, value)