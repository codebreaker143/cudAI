import os
import sys
import json
import shutil
import subprocess

from platform import system
from pathlib import Path
from datetime import datetime
from pynput.keyboard import Key, KeyCode
from typing import List

from .logger import logger
from .constants import VK_CODE, MAC_VK_CODE, INCLUDE_LIST

APP_NAME = "cudAI"


# NOTE: recording files are stored as plain JSON / JSONL. The "encrypted"
# names are kept for compatibility with existing call sites.
def write_encrypt_line(fp, data):
    fp.write(json.dumps(data, ensure_ascii=False) + "\n")


def init_encrpted_jsonl(path):
    with open(path, "w", encoding="utf-8") as f:
        pass


def write_encrypted_jsonl(path, data: List):
    with open(path, "w", encoding="utf-8") as f:
        for data_row in data:
            write_encrypt_line(fp=f, data=data_row)


def write_jsonl(path, data: List):
    with open(path, "w", encoding="utf-8") as f:
        pass
    with open(path, "a", encoding="utf-8") as f:
        for data_row in data:
            f.write(json.dumps(data_row, ensure_ascii=False) + "\n")


def read_encrypted_jsonl(path):
    with open(path, "r", encoding="utf-8") as f:
        data = []
        for line in f:
            data.append(json.loads(line.strip()))

    return data


def write_encrypted_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False))


def read_encrypted_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.loads(f.read())


def ensure_dir_exists(path: Path) -> None:
    if not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
            print(f"Created directory: {path}")
        except PermissionError:
            print(f"Permission denied: Cannot create directory {path}")
        except Exception as e:
            print(f"Error creating directory {path}: {e}")


def get_app_data_dir() -> Path:
    """Per-user, persistent application data directory."""
    override = os.environ.get("CUDAI_DATA_DIR")
    if override:
        base = Path(override)
    elif system() == "Darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    ensure_dir_exists(base)
    return base


# Folders used by the AgentNet-based predecessor of this app.
LEGACY_RECORDING_DIRS = [Path.home() / "Documents" / "AgentNetRecordings"]


def migrate_legacy_recordings() -> None:
    """
    Move recordings from legacy folders into the cudAI data directory.
    Called once at backend startup; skipped when CUDAI_DATA_DIR is set so
    tests and custom setups never touch the user's real recordings.
    """
    if os.environ.get("CUDAI_DATA_DIR"):
        return
    recordings_dir = Path(get_recordings_dir())
    for legacy_dir in LEGACY_RECORDING_DIRS:
        if not legacy_dir.is_dir():
            continue
        for entry in legacy_dir.iterdir():
            target = recordings_dir / entry.name
            if not entry.is_dir() or target.exists():
                continue
            try:
                shutil.move(str(entry), str(target))
                logger.info(f"Migrated legacy recording {entry} -> {target}")
            except Exception as e:
                logger.warning(f"Could not migrate legacy recording {entry}: {e}")


def get_recordings_dir() -> str:
    recordings_dir = get_app_data_dir() / "recordings"
    ensure_dir_exists(recordings_dir)
    return str(recordings_dir)


RECORDING_DIR = get_recordings_dir()


# Source data of a recording. Derived files (actions, clips, manifest) stay
# writable so annotation edits and re-exports keep working.
RAW_RECORDING_FILES = (
    "video.mp4",
    "events.jsonl",
    "top_window.jsonl",
    "element.jsonl",
    "a11y.jsonl",
    "metadata.json",
)


def lock_raw_files(recording_path: str) -> None:
    """
    Mark raw recording files immutable (Finder shows them as "Locked"), so
    they cannot be trashed or deleted without explicitly unlocking them.
    """
    if not hasattr(os, "chflags"):
        return
    import stat

    for name in RAW_RECORDING_FILES:
        path = os.path.join(recording_path, name)
        if os.path.exists(path):
            try:
                os.chflags(path, os.stat(path).st_flags | stat.UF_IMMUTABLE)
            except OSError as e:
                logger.warning(f"Could not lock {path}: {e}")


def get_video_by_id(video_path, id):
    for file_name in os.listdir(video_path):
        video_id = file_name.split("_")[0]
        if video_id == str(id):
            return file_name
    return None


def get_task_name_from_folder(recording_name):
    recording_path = os.path.join(RECORDING_DIR, recording_name)
    task_name_path = os.path.join(recording_path, "task_name.json")

    if not os.path.exists(task_name_path):
        creation_time = os.path.getctime(recording_path)
        creation_time_formatted = datetime.fromtimestamp(creation_time).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        return "Recording-" + creation_time_formatted + " (Untitled)"
    else:
        task = read_encrypted_json(task_name_path)
        return task["task_name"].strip()


def get_description_from_folder(recording_name):
    task_name_path = os.path.join(RECORDING_DIR, recording_name, "task_name.json")

    if not os.path.exists(task_name_path):
        return None
    else:
        task = read_encrypted_json(task_name_path)
        if (task["description"] is None) or (task["description"] == ""):
            return ""
        else:
            return task["description"].strip()


def check_recording_broken(recording_name: str) -> bool:
    recording_path = os.path.join(RECORDING_DIR, recording_name)

    if not os.path.exists(recording_path):
        logger.warning(f"check_recording_broken: {recording_path} doesn't exist.")
        return True

    vis_path = os.path.join(recording_path, "reduced_events_vis.jsonl")
    if not os.path.exists(vis_path):
        return True

    video_clips_path = os.path.join(recording_path, "video_clips")
    if not os.path.exists(video_clips_path):
        return True

    return False


def check_recording_visualizable(recording_name):
    recording_path = os.path.join(RECORDING_DIR, recording_name)

    if not os.path.exists(recording_path):
        logger.warning(f"check_recording_visualizable: {recording_path} doesn't exist.")
        return False

    for file_name in INCLUDE_LIST:
        file_path = os.path.join(recording_path, file_name)
        if not os.path.exists(file_path):
            logger.warning(
                f"check_recording_visualizable: {file_name} doesn't exist in {recording_path}"
            )
            return False

    vis_path = os.path.join(recording_path, "reduced_events_vis.jsonl")
    if os.path.exists(vis_path):
        #vis_data = read_encrypted_jsonl(vis_path)
        if os.path.exists(os.path.join(recording_path, "video_clips")):
            if len(os.listdir(os.path.join(recording_path, "video_clips"))) > 0:
                return True
    logger.warning(
        f"check_recording_visualizable: video clip number doesn't match in {recording_path}"
    )
    return False


def get_latest_folder(parent_directory):
    subdirectories = [
        os.path.join(parent_directory, d)
        for d in os.listdir(parent_directory)
        if os.path.isdir(os.path.join(parent_directory, d))
    ]
    if not subdirectories:
        return None
    latest_subdirectory = max(subdirectories, key=os.path.getctime)
    return latest_subdirectory


def find_mp4(folder_path):
    for filename in os.listdir(folder_path):
        if filename.endswith(".mp4"):
            return filename
    return None


def fix_windows_dpi_scaling():
    """
    Fixes DPI scaling issues with legacy windows applications
    Reference: https://pynput.readthedocs.io/en/latest/mouse.html#ensuring-consistent-coordinates-between-listener-and-controller-on-windows
    """
    import ctypes

    PROCESS_PER_MONITOR_DPI_AWARE = 2
    ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)


def get_ffmpeg_path() -> str:
    exe = "ffmpeg.exe" if system() == "Windows" else "ffmpeg"
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return str(Path(sys._MEIPASS) / "ffmpeg" / exe)
    return str(Path(__file__).resolve().parents[1] / exe)


VIDEO_FPS = 30
# Keyframe interval: every 2 s, so fixed-length chunks can start on a keyframe.
KEYFRAME_INTERVAL = 2 * VIDEO_FPS


def h264_encoder_args(realtime: bool = False) -> List[str]:
    """
    H.264 encoder settings shared by capture, pause-gap clips and cuts (they
    must match for stream-copy joins).

    macOS uses the system VideoToolbox encoder, so the bundled FFmpeg can be
    an LGPL build without libx264.
    """
    if system() == "Darwin":
        args = [
            "-c:v", "h264_videotoolbox",
            "-profile:v", "high",
            "-b:v", "1500k",
            "-maxrate", "3M",
            "-bufsize", "6M",
            "-allow_sw", "1",
        ]
        if realtime:
            args += ["-realtime", "1"]
    else:
        # TODO(windows): use h264_mf (Media Foundation) in the LGPL build.
        args = ["-c:v", "libx264", "-preset", "ultrafast"]
    return args + ["-g", str(KEYFRAME_INTERVAL), "-pix_fmt", "yuv420p"]


def run_ffmpeg(args: List[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [get_ffmpeg_path(), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        **kwargs,
    )


def cut_video(
    old_video_path: str, new_video_path: str, start_time: float, end_time: float
):
    os.makedirs(new_video_path, exist_ok=True)
    output_file_path = os.path.join(new_video_path, "video.mp4")
    # Re-encode instead of stream copy: with -c copy the cut snaps to the
    # previous keyframe (seconds away), breaking video/event alignment.
    start_time = max(0.0, start_time)
    result = run_ffmpeg(
        [
            "-y",
            "-ss", str(start_time),
            "-i", str(old_video_path),
            "-t", str(max(0.0, end_time - start_time)),
            *h264_encoder_args(),
            "-movflags", "+faststart",
            str(output_file_path),
        ]
    )
    if result.returncode != 0:
        logger.error(f"FFmpeg Error: {result.stderr}")
        return False
    logger.info(f"Video cut successfully: {output_file_path}")
    return True


def get_key_name(key) -> str:
    """
    Stable name of the physical key, independent of held modifiers.

    pynput reports the *composed* character for a KeyCode (e.g. Option+T gives
    "†" on macOS, Ctrl+A gives "\\x01" on Windows), and the press and release of
    the same key can report different characters when a modifier is released
    first. Resolve from the virtual keycode instead so they always match.
    """
    if isinstance(key, Key):
        return key.name
    if isinstance(key, KeyCode):
        vk = key.vk
        if vk is not None:
            if system() == "Darwin" and vk in MAC_VK_CODE:
                return MAC_VK_CODE[vk]
            if system() == "Windows" and vk in VK_CODE:
                return VK_CODE[vk].lower()
        if key.char is not None:
            if ord(key.char) < 32:
                return chr(ord(key.char) + 96)  # control character -> letter
            return key.char.lower()
        return f"vk_{vk}"
    return str(key)


def get_key_char(key) -> str | None:
    """The character the key produced, if printable."""
    if isinstance(key, KeyCode) and key.char is not None:
        if ord(key.char) >= 32 and key.char != "\x7f":
            return key.char
    return None


def get_key_vk(key) -> int | None:
    if isinstance(key, Key):
        return getattr(key.value, "vk", None)
    if isinstance(key, KeyCode):
        return key.vk
    return None


def get_key_str(key):
    try:
        return str(key)
    except Exception:
        return f"<Unprintable key: {type(key).__name__}>"


def send_notification(title, message):
    if system() == "Darwin":
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "{title}"',
            ]
        )
