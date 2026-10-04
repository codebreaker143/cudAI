"""Recording service for managing recording operations."""

import json
import os
import shutil
import threading
import time
from queue import Queue
from datetime import datetime
from typing import Dict, Tuple

from core.logger import logger
from core.recorder import Recorder
from core.action_reduction import Reducer
from core.utils import (
    get_task_name_from_folder,
    get_description_from_folder,
    RECORDING_DIR,
    read_encrypted_json,
    read_encrypted_jsonl,
    write_encrypted_json,
    write_encrypted_jsonl,
    check_recording_visualizable,
    check_recording_broken,
    lock_raw_files,
    primary_screen_size,
)
from core.backend_func import read_recording_status
from core.consent import has_current_consent
from core.permissions import missing_permissions
from core.export import build_timeline, write_export
from core.recovery import (
    find_interrupted_recordings,
    recover_recording,
    stop_orphaned_captures,
)
from core.constants import SUCCEED, FAILED


# Disk space guard (bytes). Video is ~0.5-1.5 GB per hour.
MIN_FREE_BYTES_TO_START = 2 * 1024**3
MIN_FREE_BYTES_WHILE_RECORDING = 500 * 1024**2
DISK_CHECK_INTERVAL = 10


def free_disk_bytes() -> int:
    return shutil.disk_usage(RECORDING_DIR).free


class RecordingService:
    """Service for handling recording operations."""

    def __init__(self, socketio):
        self.socketio = socketio
        self.recorder_thread = None
        self.reducer = None
        self.user_recordings = None
        self.opened_single_recording = None

        # Recording configuration (None = detect from OS settings)
        self.natural_scrolling = None
        self.generate_window_a11y = False
        self.generate_element_a11y = True

        # Setup reducer queue processing
        self.reducer_queue = Queue()
        self.reducer_thread = threading.Thread(
            target=self._process_reducer_queue, daemon=True
        )
        self.reducer_thread.start()

        # Start/stop/pause can come from the UI, shortcuts and the disk monitor.
        self._lifecycle_lock = threading.RLock()

        threading.Thread(target=self._recover_interrupted, daemon=True).start()

    def _recover_interrupted(self) -> None:
        """Finish recordings interrupted by a crash or force quit."""
        try:
            stop_orphaned_captures()
            for path in find_interrupted_recordings():
                try:
                    if recover_recording(path):
                        self.reducer_queue.put(self._make_reducer(path))
                except Exception:
                    logger.exception(f"RecordingService: could not recover {path}")
        except Exception:
            logger.exception("RecordingService: recovery failed")

    def _make_reducer(self, recording_path: str) -> Reducer:
        width, height = primary_screen_size()
        a11y_path = os.path.join(recording_path, "a11y.jsonl")
        return Reducer(
            recording_path=recording_path,
            window_attrs={"width": width, "height": height},
            configs={
                "generate_window_a11y": os.path.exists(a11y_path) and os.path.getsize(a11y_path) > 0,
                "generate_element_a11y": self.generate_element_a11y,
            },
        )

    def start_recording(self) -> Tuple[str, str]:
        with self._lifecycle_lock:
            return self._start_recording()

    def _start_recording(self) -> Tuple[str, str]:
        """Start a new recording session."""
        logger.info("RecordingService: start_recording")

        if self.recorder_thread is not None:
            return FAILED, "Recording already in progress"

        if not has_current_consent():
            return FAILED, "Please review and accept the recording terms first"

        free = free_disk_bytes()
        if free < MIN_FREE_BYTES_TO_START:
            return FAILED, (
                f"Only {free / 1e9:.1f} GB of disk space is free. "
                f"Free up at least {MIN_FREE_BYTES_TO_START / 1e9:.0f} GB to record."
            )

        missing = missing_permissions()
        if missing:
            return FAILED, (
                f"cudAI needs {', '.join(missing)} permission to record. "
                "Grant it in System Settings › Privacy & Security, then restart cudAI."
            )

        try:
            self.recorder_thread = Recorder(
                socketio=self.socketio,
                natural_scrolling=self.natural_scrolling,
                generate_window_a11y=self.generate_window_a11y,
                generate_element_a11y=self.generate_element_a11y,
            )
            recording_path = self.recorder_thread.recording_path

            width, height = primary_screen_size()
            self.reducer = Reducer(
                recording_path=recording_path,
                window_attrs={"width": width, "height": height},
                configs={
                    "generate_window_a11y": self.generate_window_a11y,
                    "generate_element_a11y": self.generate_element_a11y,
                },
            )

            self.recorder_thread.start_recording()
            threading.Thread(
                target=self._monitor_disk, args=(self.recorder_thread,), daemon=True
            ).start()
            logger.info("RecordingService: Recording started successfully")
            return SUCCEED, "Recording started successfully"

        except Exception as e:
            self._cleanup_failed_recording()
            logger.exception("RecordingService: start_recording failed")
            return FAILED, f"Failed to start recording: {str(e)}"

    def stop_recording(self) -> Tuple[str, str]:
        with self._lifecycle_lock:
            return self._stop_recording()

    def _stop_recording(self) -> Tuple[str, str]:
        """Stop the current recording session."""
        logger.info("RecordingService: stop_recording")

        recorder = self.recorder_thread
        if recorder is None:
            return FAILED, "No active recording"

        recording_id = os.path.basename(recorder.recording_path)
        try:
            recorder.stop_recording()
        except Exception as e:
            logger.exception("RecordingService: stop_recording failed")
            return FAILED, (
                f"The recording could not be finalized ({e}). "
                "It will be recovered the next time cudAI starts."
            )
        finally:
            # Never leave the service stuck in "recording".
            self.recorder_thread = None

        # Mark recording as processing while the reducer works.
        if self.user_recordings and recording_id in self.user_recordings:
            self.user_recordings[recording_id]["status"] = "processing"
            self.user_recordings[recording_id]["visualizable"] = False

        self.reducer_queue.put(self.reducer)
        logger.info("RecordingService: Recording stopped successfully")
        return SUCCEED, "Recording stopped successfully"

    def _monitor_disk(self, recorder) -> None:
        """Stop the recording cleanly before the disk fills up."""
        while self.recorder_thread is recorder:
            time.sleep(DISK_CHECK_INTERVAL)
            if self.recorder_thread is not recorder:
                return
            free = free_disk_bytes()
            if free >= MIN_FREE_BYTES_WHILE_RECORDING:
                continue
            logger.warning(f"RecordingService: low disk space ({free} bytes), stopping")
            with self._lifecycle_lock:
                if self.recorder_thread is not recorder:
                    return
                status, message = self._stop_recording()
            self.socketio.emit(
                "recording_auto_stopped",
                {
                    "reason": "low_disk",
                    "message": "Recording stopped and saved: your disk is almost full.",
                    "stopped": status == SUCCEED,
                    "detail": message,
                },
            )
            return

    def pause_recording(self) -> Tuple[str, str]:
        with self._lifecycle_lock:
            return self._pause_recording()

    def _pause_recording(self) -> Tuple[str, str]:
        if self.recorder_thread is None:
            return FAILED, "No active recording"
        try:
            if not self.recorder_thread.pause_recording():
                return FAILED, "Recording is already paused"
            return SUCCEED, "Recording paused"
        except Exception as e:
            logger.exception("RecordingService: pause_recording failed")
            return FAILED, f"Failed to pause recording: {str(e)}"

    def resume_recording(self) -> Tuple[str, str]:
        with self._lifecycle_lock:
            return self._resume_recording()

    def _resume_recording(self) -> Tuple[str, str]:
        if self.recorder_thread is None:
            return FAILED, "No active recording"
        try:
            if not self.recorder_thread.resume_recording():
                return FAILED, "Recording is not paused"
            return SUCCEED, "Recording resumed"
        except Exception as e:
            logger.exception("RecordingService: resume_recording failed")
            return FAILED, f"Failed to resume recording: {str(e)}"

    def get_status(self) -> Dict:
        recorder = self.recorder_thread
        return {
            "recording": recorder is not None,
            "paused": recorder is not None and recorder.is_paused,
            "elapsed_seconds": recorder.elapsed_seconds() if recorder else 0,
        }

    def get_review(self, recording_name: str) -> Tuple[str, Dict]:
        """Everything the review screen needs for one recording."""
        status, data = self.get_single_recording(recording_name)
        if status != SUCCEED:
            return status, data

        folder = self._get_recording_path(recording_name)
        with open(os.path.join(folder, "metadata.json"), "r", encoding="utf-8") as f:
            metadata = json.load(f)

        manifest_path = os.path.join(folder, "manifest.json")
        if not os.path.exists(manifest_path):
            write_export(folder)
        manifest = (
            read_encrypted_json(manifest_path) if os.path.exists(manifest_path) else {}
        )

        timeline_path = os.path.join(folder, "timeline.jsonl")
        timeline = (
            read_encrypted_jsonl(timeline_path)
            if os.path.exists(timeline_path)
            else build_timeline(folder, metadata)
        )
        # Pointer moves are visible in the video itself; keep the payload small.
        timeline = [e for e in timeline if e["type"] != "move"]

        video = metadata.get("video") or manifest.get("video") or {}
        return SUCCEED, {
            "recording_id": recording_name,
            "path": folder,
            "task_name": data.get("task_name"),
            "description": data.get("description"),
            "creation_time": data.get("creation_time"),
            "video_url": f"/api/recording/{recording_name}/video.mp4",
            "video_start_timestamp": metadata["video_start_timestamp"],
            "video": {
                "fps": video.get("fps", 30),
                "width": video.get("width"),
                "height": video.get("height"),
                "duration": video.get("duration"),
                "paused_gaps": video.get("paused_gaps") or [],
            },
            "display": manifest.get("display") or {
                "logical_width": metadata.get("screen_width"),
                "logical_height": metadata.get("screen_height"),
            },
            "actions": data["events"],
            "timeline": timeline,
            "manifest": manifest,
        }

    def update_task(self, recording_name: str, task_name: str, description: str) -> Tuple[str, str]:
        folder = self._get_recording_path(recording_name)
        if not os.path.isdir(folder):
            return FAILED, "Recording not found"
        write_encrypted_json(
            os.path.join(folder, "task_name.json"),
            {"task_name": task_name.strip(), "description": (description or "").strip()},
        )
        write_export(folder)
        if self.user_recordings and recording_name in self.user_recordings:
            self._update_recording_info(self.user_recordings[recording_name], recording_name)
        return SUCCEED, "Task saved"

    def get_user_recordings(self) -> Dict:
        """Get list of user recordings."""
        logger.info("RecordingService: get_user_recordings")

        if not os.path.exists(RECORDING_DIR):
            os.makedirs(RECORDING_DIR, exist_ok=True)
            return {"recordings": []}

        # Handle legacy recording name conversion
        self._convert_legacy_recording_names()

        local_recording_ids = [
            f for f in os.listdir(RECORDING_DIR) if ".ds_store" not in f.lower()
        ]

        if self.user_recordings is not None:
            self._update_existing_recordings(local_recording_ids)
        else:
            self._initialize_recordings(local_recording_ids)

        return {"recordings": list(self.user_recordings.values())}

    def get_single_recording(self, recording_name: str) -> Tuple[str, Dict]:
        """Get details of a single recording."""
        logger.info(f"RecordingService: get_single_recording: {recording_name}")

        folder_path = self._get_recording_path(recording_name)

        if not os.path.exists(folder_path):
            return FAILED, {"error": "Recording not found"}

        # Prevent opening while reduction is still running.
        reduced_events_path = os.path.join(folder_path, "reduced_events_vis.jsonl")
        if not os.path.exists(reduced_events_path):
            return FAILED, {"error": "Recording is still processing"}

        try:
            recording_data = self._build_recording_data(recording_name)
            events = self._load_recording_events(folder_path)
            recording_data["events"] = events

            self.opened_single_recording = recording_data
            logger.info("RecordingService: get_single_recording completed")
            return SUCCEED, recording_data

        except Exception as e:
            logger.exception(f"RecordingService: get_single_recording failed: {e}")
            return FAILED, {"error": "Failed to load recording"}

    def confirm_recording(
        self, recording_name: str, events_data: list
    ) -> Tuple[str, str]:
        """Confirm and save recording modifications."""
        logger.info("RecordingService: confirm_recording")

        if self.opened_single_recording is None:
            return FAILED, "No recording opened"

        try:
            folder_path = os.path.join(RECORDING_DIR, recording_name)
            self._save_modified_events(folder_path, events_data)
            write_export(folder_path)
            return SUCCEED, "Recording modifications saved successfully"

        except Exception as e:
            logger.exception("RecordingService: confirm_recording failed")
            return FAILED, f"Failed to confirm recording: {str(e)}"

    def toggle_window_a11y(self, flag: bool) -> None:
        """Toggle window accessibility generation."""
        self.generate_window_a11y = flag
        logger.info(f"RecordingService: generate_window_a11y set to {flag}")

    def _cleanup_failed_recording(self) -> None:
        """Clean up resources after failed recording."""
        if hasattr(self, "recorder_thread") and self.recorder_thread:
            self.recorder_thread.stop()

        self.recorder_thread = None
        self.reducer = None

    def _process_reducer_queue(self) -> None:
        """Process the reducer queue in background thread."""
        while True:
            reducer = self.reducer_queue.get()

            if reducer is None:
                self.reducer_queue.task_done()
                continue

            try:
                reducer.reduce_pipeline()
                lock_raw_files(reducer.recording_path)

                recording_id = os.path.basename(reducer.recording_path)

                if self.user_recordings and recording_id in self.user_recordings:
                    self.user_recordings[recording_id]["status"] = "local"
                    self.user_recordings[recording_id]["visualizable"] = True

                self.socketio.emit(
                    "reduced",
                    {
                        "status": "succeed",
                        "message": "Recording processing completed",
                    },
                )

            except Exception as e:
                logger.exception(
                    f"RecordingService: Error in reduce_pipeline: {e}"
                )

                self.socketio.emit(
                    "reduced",
                    {
                        "status": "failed",
                        "message": "Recording processing failed",
                    },
                )

            finally:
                self.reducer_queue.task_done()

    def _convert_legacy_recording_names(self) -> None:
        """Convert legacy recording names to recording IDs."""
        for recording_name in os.listdir(RECORDING_DIR):
            if recording_name.startswith("recording"):
                recording_status = read_recording_status(
                    recording_path=os.path.join(
                        RECORDING_DIR, recording_name
                    )
                )

                if recording_status:
                    old_path = os.path.join(
                        RECORDING_DIR, recording_name
                    )

                    new_path = os.path.join(
                        RECORDING_DIR,
                        recording_status["recording_id"],
                    )

                    os.rename(old_path, new_path)

                else:
                    logger.error(
                        f"Invalid recording {recording_name}, removing"
                    )

    def _update_existing_recordings(
        self, local_recording_ids: list
    ) -> None:
        """Update existing recordings list with local changes."""

        # Remove deleted recordings
        for recording_id in list(self.user_recordings.keys()):
            if recording_id not in local_recording_ids:
                del self.user_recordings[recording_id]

        # Add new recordings
        new_recording_ids = []

        for recording_id in local_recording_ids:
            if recording_id not in self.user_recordings:
                new_recording_ids.append(recording_id)

                recording = self._create_recording_info(
                    recording_id
                )

                self.user_recordings[recording_id] = recording

        # Update existing recordings
        for recording_id, recording in self.user_recordings.items():
            if recording_id not in new_recording_ids:
                self._update_recording_info(recording, recording_id)

    def _initialize_recordings(
        self, local_recording_ids: list
    ) -> None:
        """Initialize recordings list from scratch."""
        local_recordings = {}

        for recording_name in local_recording_ids:
            local_recordings[
                recording_name
            ] = self._create_recording_info(
                recording_name
            )

        self.user_recordings = local_recordings

    def _create_recording_info(self, recording_name: str) -> Dict:
        """Create recording info dictionary."""
        recording = {
            "name": recording_name,
            "creation_time": self._recorded_at(recording_name).strftime("%Y-%m-%d %H:%M:%S"),
        }
        return self._update_recording_info(recording, recording_name)

    def _recorded_at(self, recording_name: str) -> datetime:
        """
        When the recording started. Folder timestamps change when recordings
        are moved or migrated, so prefer the start time in metadata.json.
        """
        recording_path = self._get_recording_path(recording_name)
        metadata_path = os.path.join(recording_path, "metadata.json")
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                start = json.load(f).get("start_time")
            if start:
                started = datetime.fromisoformat(start)
                if started.tzinfo is not None:
                    started = started.astimezone().replace(tzinfo=None)
                return started
        except Exception:
            pass
        return datetime.fromtimestamp(os.path.getctime(recording_path))

    def _update_recording_info(self, recording: Dict, recording_name: str) -> Dict:
        """Update recording info with latest data."""
        recording_path = self._get_recording_path(recording_name)

        # A recording is only ready when reducer output exists.
        reduction_complete = os.path.exists(
            os.path.join(recording_path, "reduced_events_vis.jsonl")
        )

        recording["status"] = "local" if reduction_complete else "processing"
        recording["task_name"] = get_task_name_from_folder(recording_name)
        recording["task_description"] = get_description_from_folder(recording_name)

        if reduction_complete:
            recording["visualizable"] = check_recording_visualizable(recording_name)
            recording["broken"] = check_recording_broken(recording_name)
        else:
            recording["visualizable"] = False
            recording["broken"] = False

        manifest_path = os.path.join(recording_path, "manifest.json")
        if reduction_complete and not os.path.exists(manifest_path):
            # Recordings from before the export format existed.
            write_export(recording_path)
        if os.path.exists(manifest_path):
            try:
                manifest = read_encrypted_json(manifest_path)
                stats = manifest.get("stats") or {}
                recording["duration"] = (manifest.get("video") or {}).get("duration")
                recording["action_count"] = stats.get("action_count")
                recording["apps"] = stats.get("apps") or []
            except Exception:
                logger.warning(f"Unreadable manifest for {recording_name}")

        return recording

    def _get_recording_path(self, recording_name: str) -> str:
        """Get the full path to a recording directory."""
        return os.path.join(RECORDING_DIR, recording_name)

    def _build_recording_data(self, recording_name: str) -> Dict:
        """Build recording data dictionary."""
        recording_data = {
            "recording_id": recording_name,
            "recording_name": recording_name,
        }

        if self.user_recordings and recording_name in self.user_recordings:
            recording_data.update(self.user_recordings[recording_name])

        recording_data.update(
            {
                "task_name": get_task_name_from_folder(recording_name),
                "description": get_description_from_folder(recording_name),
            }
        )
        return recording_data

    def _load_recording_events(
        self,
        folder_path: str,
    ) -> list:
        """Load events from recording directory."""

        events_file_path = os.path.join(
            folder_path,
            "reduced_events_vis.jsonl",
        )

        if not os.path.exists(
            events_file_path
        ):
            raise FileNotFoundError(
                "reduced_events_vis.jsonl file not found"
            )

        return read_encrypted_jsonl(
            events_file_path
        )

    def _save_modified_events(
        self,
        folder_path: str,
        events_data: list,
    ) -> None:
        """Save modified events to files."""

        self.opened_single_recording[
            "events"
        ] = events_data

        vis_events_path = os.path.join(
            folder_path,
            "reduced_events_vis.jsonl",
        )

        write_encrypted_jsonl(
            vis_events_path,
            events_data,
        )

        complete_events_path = os.path.join(
            folder_path,
            "reduced_events_complete.jsonl",
        )

        if os.path.exists(
            complete_events_path
        ):
            complete_events_data = (
                read_encrypted_jsonl(
                    complete_events_path
                )
            )

            ids_left = [
                event["id"]
                for event in events_data
            ]

            new_complete_data = [
                action
                for action in complete_events_data
                if action["id"] in ids_left
            ]

            write_encrypted_jsonl(
                complete_events_path,
                new_complete_data,
            )
