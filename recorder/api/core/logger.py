import os
import sys
from pathlib import Path
from platform import system

from loguru import logger as _logger

logger = _logger


def _log_dir() -> Path:
    # Mirrors utils.get_app_data_dir (which imports this module).
    override = os.environ.get("CUDAI_DATA_DIR")
    if override:
        base = Path(override)
    elif system() == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "cudAI"
    elif system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "cudAI"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "cudAI"
    path = base / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


logger.remove()

# Ensure stdout uses utf-8 encoding
sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

logger.add(sys.stdout, level=os.environ.get("CUDAI_LOG_LEVEL", "INFO"), colorize=True)
logger.add(
    _log_dir() / "backend.log",
    level="INFO",
    colorize=False,
    rotation="10 MB",
    retention=5,
)
