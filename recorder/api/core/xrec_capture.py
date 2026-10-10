import os
import re
import shutil
import signal
import subprocess
import threading
import time

from . import timing
from .displays import chunks_dir_name, segments_dir_name, video_file_name
from .logger import logger
from .utils import (
    KEYFRAME_INTERVAL,
    VIDEO_FPS,
    get_ffmpeg_path,
    h264_encoder_args,
    run_ffmpeg,
)

# Video is written as standalone MP4 chunks of this length, so it can be
# uploaded while recording and survives a crash or power loss up to the last
# closed chunk.
CHUNK_SECONDS = 10


# FFmpeg does not exit when its parent dies, so an orphaned capture would keep
# recording the screen with no UI showing it. This guardian runs FFmpeg and
# stops it (gracefully, so the file stays playable) as soon as the backend
# process is gone. Our own "q" on stdin still reaches FFmpeg for normal stops.
# A capture that hangs (e.g. while macOS initializes the screen stream) may
# ignore SIGINT, so after a grace period the guardian force-kills it.
WATCHDOG = r"""
owner=$1; shift
"$@" <&0 &
ffmpeg_pid=$!
trap 'kill -INT "$ffmpeg_pid" 2>/dev/null' INT TERM
while kill -0 "$owner" 2>/dev/null && kill -0 "$ffmpeg_pid" 2>/dev/null; do
  sleep 0.5
done
kill -INT "$ffmpeg_pid" 2>/dev/null
for _ in 1 2 3 4 5 6 7 8 9 10; do
  kill -0 "$ffmpeg_pid" 2>/dev/null || exit 0
  sleep 0.5
done
kill -KILL "$ffmpeg_pid" 2>/dev/null
"""

START_RE = re.compile(r"start: (\d+\.\d+)")
FRAME_RE = re.compile(r"frame=\s*(\d+)")
SIZE_RE = re.compile(r"Video: \w+.*?, (\d{2,5})x(\d{2,5})")


def read_chunk_list(chunk_dir: str, fps: int) -> list:
    """
    Closed chunks of a segment, in order. FFmpeg appends a line to chunks.csv
    ("name,start,end" in seconds) as each chunk is closed; a chunk still
    being written (or cut off by a crash) is not listed.
    """
    path = os.path.join(chunk_dir, "chunks.csv")
    if not os.path.exists(path):
        return []
    with open(path, "r", errors="replace") as f:
        lines = f.read().split("\n")[:-1]  # the last piece may be partial
    chunks, next_frame = [], 0
    for line in lines:
        try:
            name, start, end = line.split(",")
            start_frame, end_frame = round(float(start) * fps), round(float(end) * fps)
        except ValueError:
            continue
        file = os.path.join(chunk_dir, name)
        if not os.path.exists(file) or end_frame <= start_frame:
            continue
        if start_frame != next_frame:
            logger.warning(f"read_chunk_list: {file} does not follow the previous chunk")
            break
        chunks.append({"file": file, "start_frame": start_frame, "frames": end_frame - start_frame})
        next_frame = end_frame
    return chunks


def trim_video(path: str, frames: int) -> None:
    """Keep only the first `frames` frames of an MP4 (stream copy, in place)."""
    trimmed = path[: -len(".mp4")] + "_trimmed.mp4"
    result = run_ffmpeg(
        ["-y", "-i", path, "-frames:v", str(frames),
         "-c", "copy", "-movflags", "+faststart", trimmed]
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to trim {path}: {result.stderr[-500:]}")
    os.replace(trimmed, path)


class XrecCapture:
    """
    Native screen capture with FFmpeg (macOS avfoundation).

    Every start/resume records a separate segment, written as 10-second MP4
    chunks (chunks/display_N/segment_SSS/chunk_CCCCC.mp4). On macOS the capture
    timestamps reported by avfoundation (`start:` in FFmpeg's log) use the
    same monotonic host clock as Python's time.perf_counter(), so each
    segment's first frame is known exactly in the event timeline.

    When a segment stops, its chunks are sealed: frames captured after the
    pause/stop request are cut, so they never reach an uploaded chunk.
    finalize() joins all chunks into video.mp4 and fills paused gaps with
    black frames, so video time == perf_counter time - video_start_timestamp
    for the whole recording.
    """

    START_TIMEOUT = 15.0

    def __init__(
        self,
        recording_path: str,
        fps: int = VIDEO_FPS,
        display_index: int = 0,
        screen_device: str | None = None,
    ):
        self.recording_path = recording_path
        self.display_index = display_index
        self.segments_dir = os.path.join(recording_path, segments_dir_name(display_index))
        self.chunks_dir = os.path.join(recording_path, chunks_dir_name(display_index))
        self.output_name = video_file_name(display_index)
        self.fps = fps
        self.screen_device = screen_device
        self.process = None
        self.log_file = None
        self._pending = None
        self.segments = []
        self._lock = threading.Lock()  # segments are read by the uploader

    def _find_screen_device(self) -> str:
        if self.screen_device is None:
            self.screen_device = find_screen_devices().get(self.display_index)
        if self.screen_device is None:
            raise RuntimeError(
                f"cudAI could not find a capture device for display {self.display_index}."
            )
        return self.screen_device

    @property
    def is_capturing(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start_segment(self) -> dict:
        self.launch_segment()
        return self.await_segment_start()

    def launch_segment(self) -> None:
        """Start FFmpeg for a new segment without waiting for its first frame."""
        if self.is_capturing:
            raise RuntimeError("Recording is already running.")

        os.makedirs(self.segments_dir, exist_ok=True)
        index = len(self.segments)
        log_path = os.path.join(self.segments_dir, f"segment_{index:03d}.log")
        chunk_dir = self._chunk_dir(index)
        os.makedirs(chunk_dir, exist_ok=True)
        screen_device = self._find_screen_device()

        command = [
            get_ffmpeg_path(),
            "-y",
            "-f", "avfoundation",
            "-framerate", str(self.fps),
            "-capture_cursor", "1",
            "-capture_mouse_clicks", "1",
            "-pixel_format", "nv12",
            "-i", f"{screen_device}:none",
            *h264_encoder_args(realtime=True),
            # Constant frame rate: frame n is exactly at start + n / fps.
            "-fps_mode", "cfr",
            "-r", str(self.fps),
            # Keyframes exactly every 2 s, so chunks split exactly at 10 s.
            "-force_key_frames", f"expr:gte(t,n_forced*{KEYFRAME_INTERVAL / self.fps:g})",
            "-f", "segment",
            "-segment_time", str(CHUNK_SECONDS),
            "-reset_timestamps", "1",
            "-segment_format", "mp4",
            "-segment_format_options", "movflags=+faststart",
            "-segment_list", os.path.join(chunk_dir, "chunks.csv"),
            "-segment_list_type", "csv",
            "-segment_list_flags", "+live",
            os.path.join(chunk_dir, "chunk_%05d.mp4"),
        ]

        if os.name != "nt":
            command = ["/bin/sh", "-c", WATCHDOG, "cudai-capture", str(os.getpid()), *command]

        self.log_file = open(log_path, "w")
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self.log_file,
            # Own process group, so the guardian and FFmpeg can be killed together.
            start_new_session=os.name != "nt",
        )
        self._pending = {"index": index, "chunk_dir": chunk_dir, "log": log_path,
                         "launched_unix": time.time()}

    def _chunk_dir(self, index: int) -> str:
        return os.path.join(self.chunks_dir, f"segment_{index:03d}")

    def await_segment_start(self) -> dict:
        segment = self._pending
        segment["start_timestamp"] = self._wait_for_start(segment["log"])
        timing.record(self.recording_path, "capture_start", segment.pop("launched_unix"),
                      timing.perf_to_unix(segment["start_timestamp"]),
                      display=self.display_index, segment=segment["index"])
        with self._lock:
            self.segments.append(segment)
        logger.info(
            f"XrecCapture: display {self.display_index} segment {segment['index']} "
            f"first frame at {segment['start_timestamp']}"
        )
        return segment

    def _wait_for_start(self, log_path: str) -> float:
        deadline = time.perf_counter() + self.START_TIMEOUT
        while time.perf_counter() < deadline:
            if self.process.poll() is not None:
                self._close_log()
                self.process = None
                raise RuntimeError(
                    f"Screen capture failed to start. See {log_path}"
                )
            with open(log_path, "r", errors="replace") as f:
                match = START_RE.search(f.read())
            if match:
                return float(match.group(1))
            time.sleep(0.02)

        self.abort()
        raise RuntimeError(
            f"Screen capture did not report a start time. See {log_path}"
        )

    def stop_segment(self, requested_at: float | None = None) -> dict | None:
        """
        Stop the running segment. `requested_at` (perf_counter) is when the
        user asked to pause/stop; FFmpeg keeps capturing until it shuts down,
        so frames after that instant are trimmed in finalize().
        """
        if not self.process:
            return None
        if requested_at is None:
            requested_at = time.perf_counter()
        segment = self.segments[-1]
        # Set first: from now on ready_chunks() holds back anything after it.
        segment["stop_requested_at"] = requested_at
        stop_started = time.time()

        if self.process.poll() is None:
            try:
                # Graceful FFmpeg shutdown so the MP4 is finalized correctly.
                self.process.stdin.write(b"q\n")
                self.process.stdin.flush()
                self.process.wait(timeout=15)
            except Exception:
                self._terminate()

        self.process = None
        self._close_log()

        self._read_segment_log(segment)
        self._seal(segment)
        timing.record(self.recording_path, "capture_stop", stop_started, time.time(),
                      display=self.display_index, segment=segment["index"])
        return segment

    def _seal(self, segment: dict) -> None:
        """
        Fix a stopped segment's chunk list: frames after the pause/stop
        request are cut from the last chunk and later chunks are removed.
        Idempotent, so recovery can seal again.
        """
        chunks = read_chunk_list(segment["chunk_dir"], self.fps)
        allowed = sum(c["frames"] for c in chunks)
        requested_at = segment.get("stop_requested_at")
        if requested_at is not None:
            # Epsilon: (104.8 - 104.0) * 30 is 23.999... in floating point.
            wanted = int((requested_at - segment["start_timestamp"]) * self.fps + 1e-6)
            allowed = max(0, min(allowed, wanted))
        kept = []
        for chunk in chunks:
            if chunk["start_frame"] >= allowed:
                os.remove(chunk["file"])
                continue
            keep = allowed - chunk["start_frame"]
            if keep < chunk["frames"]:
                trim_video(chunk["file"], keep)
                chunk["frames"] = keep
            kept.append(chunk)
        segment["chunks"] = kept
        segment["frames"] = allowed
        segment["duration"] = allowed / self.fps

    def ready_chunks(self) -> list:
        """
        Chunks that are final and safe to upload: closed, and entirely before
        any pause/stop request (a chunk spanning a pause is trimmed first).
        """
        with self._lock:
            segments = list(self.segments)
        ready = []
        for segment in segments:
            if "chunk_dir" not in segment:
                continue
            chunks = segment.get("chunks")
            if chunks is None:
                chunks = read_chunk_list(segment["chunk_dir"], self.fps)
                requested_at = segment.get("stop_requested_at")
                if requested_at is not None:
                    limit = (requested_at - segment["start_timestamp"]) * self.fps
                    chunks = [c for c in chunks if c["start_frame"] + c["frames"] <= limit]
            ready += [self._chunk_info(segment, c) for c in chunks]
        return ready

    def _chunk_info(self, segment: dict, chunk: dict) -> dict:
        return {
            "display": self.display_index,
            "segment": segment["index"],
            "path": os.path.relpath(chunk["file"], self.recording_path).replace(os.sep, "/"),
            "file": chunk["file"],
            "start_frame": chunk["start_frame"],
            "frames": chunk["frames"],
            # perf_counter time of the chunk's last frame (upload lag).
            "end_perf": segment["start_timestamp"] + (chunk["start_frame"] + chunk["frames"]) / self.fps,
        }

    def _read_segment_log(self, segment: dict) -> None:
        """Fill frames/duration/size from the segment's FFmpeg log."""
        with open(segment["log"], "r", errors="replace") as f:
            log = f.read()
        frames = [int(m) for m in FRAME_RE.findall(log)]
        output_log = log.split("Output #0", 1)[-1]
        size = SIZE_RE.search(output_log)
        segment["frames"] = frames[-1] if frames else None
        segment["duration"] = (
            segment["frames"] / self.fps if segment["frames"] is not None else None
        )
        if size:
            segment["width"], segment["height"] = int(size.group(1)), int(size.group(2))

    def load_segments_from_disk(self, stop_requests: list) -> None:
        """
        Rebuild segment info after an interrupted recording (crash recovery).
        `stop_requests[i]` is when segment i was paused/stopped, if known.
        """
        logs = sorted(
            f for f in os.listdir(self.segments_dir)
            if re.fullmatch(r"segment_\d{3}\.log", f)
        )
        self.segments = []
        for i, name in enumerate(logs):
            log_path = os.path.join(self.segments_dir, name)
            with open(log_path, "r", errors="replace") as f:
                match = START_RE.search(f.read())
            if not match:
                continue
            segment = {
                "index": i,
                "log": log_path,
                "start_timestamp": float(match.group(1)),
                "stop_requested_at": stop_requests[i] if i < len(stop_requests) else None,
            }
            index = int(name[len("segment_"):-len(".log")])
            video_path = log_path[: -len(".log")] + ".mp4"
            if os.path.isdir(self._chunk_dir(index)):
                segment["chunk_dir"] = self._chunk_dir(index)
            elif os.path.exists(video_path):
                segment["file"] = video_path  # recorded before chunking
            else:
                continue
            self._read_segment_log(segment)
            if "chunk_dir" in segment:
                self._seal(segment)
            self.segments.append(segment)

    def _terminate(self):
        """Stop FFmpeg (and its guardian): politely, then by force."""
        process = self.process
        try:
            process.send_signal(signal.SIGINT)
            process.wait(timeout=5)
        except Exception:
            pass
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)  # whole group, incl. FFmpeg
            except (ProcessLookupError, PermissionError):
                pass
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    def abort(self) -> None:
        """Discard a segment that failed to start (or never will)."""
        if self.process is not None:
            self._terminate()
            self.process = None
        self._close_log()
        self._pending = None

    def _close_log(self):
        if self.log_file:
            self.log_file.close()
            self.log_file = None

    # Recorder API -----------------------------------------------------------

    def start_recording(self) -> dict:
        return self.start_segment()

    def pause_recording(self, requested_at: float | None = None):
        self.stop_segment(requested_at)

    def resume_recording(self) -> dict:
        return self.start_segment()

    def stop_recording(self, requested_at: float | None = None):
        self.stop_segment(requested_at)

    def finalize(self) -> dict:
        """
        Join segments into video.mp4. Returns video metadata for metadata.json.
        """
        with timing.stage(self.recording_path, "finalize_video", display=self.display_index):
            return self._finalize()

    def _finalize(self) -> dict:
        output_path = os.path.join(self.recording_path, self.output_name)
        for segment in self.segments:
            if "chunk_dir" in segment:
                if "chunks" not in segment:
                    self._seal(segment)
            else:
                self._trim_after_stop_request(segment)
        segments = [s for s in self.segments if s.get("frames")]
        if not segments:
            raise RuntimeError("No video was captured.")

        first = segments[0]
        width, height = first.get("width"), first.get("height")
        timeline = []  # files of video.mp4, in order
        chunked = all("chunks" in s for s in segments)
        gaps = []
        offset = 0.0
        for i, segment in enumerate(segments):
            if i > 0:
                prev = segments[i - 1]
                prev_end = prev["start_timestamp"] + prev["duration"]
                gap = segment["start_timestamp"] - prev_end
                gap_frames = max(0, round(gap * self.fps))
                if gap_frames > 0:
                    # Chunked recordings keep gap clips with the chunks, so
                    # video.mp4 can be rebuilt from uploaded files alone.
                    gap_dir = self.chunks_dir if chunked else self.segments_dir
                    os.makedirs(gap_dir, exist_ok=True)
                    gap_path = os.path.join(gap_dir, f"gap_{i:03d}.mp4")
                    self._make_black_clip(gap_path, width, height, gap_frames)
                    timeline.append(gap_path)
                    gaps.append(
                        {
                            "start_timestamp": prev_end,
                            "end_timestamp": segment["start_timestamp"],
                            "video_offset": offset,
                            "frames": gap_frames,
                        }
                    )
                    offset += gap_frames / self.fps
            segment["video_offset"] = offset
            if "chunks" in segment:
                timeline += [c["file"] for c in segment["chunks"]]
            else:
                timeline.append(segment["file"])
            offset += segment["duration"]

        if len(timeline) > 1:
            self._concat(timeline, output_path, width, height)
        elif "chunks" in segments[0]:
            shutil.copyfile(timeline[0], output_path)  # chunks are kept for upload
        else:
            shutil.move(timeline[0], output_path)

        # Chunks stay in chunks/ until they are uploaded (see core.upload).
        shutil.rmtree(self.segments_dir, ignore_errors=True)

        parts = (
            {"parts": [os.path.relpath(p, self.recording_path).replace(os.sep, "/") for p in timeline]}
            if chunked else {}
        )
        return {
            "file": self.output_name,
            "display_index": self.display_index,
            "codec": "h264",
            "fps": self.fps,
            "width": width,
            "height": height,
            "duration": offset,
            "video_start_timestamp": first["start_timestamp"],
            "segments": [
                {
                    "start_timestamp": s["start_timestamp"],
                    "duration": s["duration"],
                    "frames": s["frames"],
                    "video_offset": s["video_offset"],
                    **(
                        {"chunks": [
                            {k: v for k, v in self._chunk_info(s, c).items() if k in ("path", "start_frame", "frames")}
                            for c in s["chunks"]
                        ]}
                        if "chunks" in s else {}
                    ),
                }
                for s in segments
            ],
            "paused_gaps": gaps,
            # Files that, concatenated in this order (stream copy), give video.mp4.
            **parts,
        }

    def _trim_after_stop_request(self, segment: dict):
        """Drop frames captured after the user paused or stopped."""
        requested_at = segment.get("stop_requested_at")
        if not segment.get("frames") or requested_at is None:
            return
        # Epsilon: (104.8 - 104.0) * 30 is 23.999... in floating point.
        allowed = int((requested_at - segment["start_timestamp"]) * self.fps + 1e-6)
        if allowed >= segment["frames"]:
            return
        if allowed <= 0:
            segment["frames"], segment["duration"] = 0, 0.0
            return

        trim_video(segment["file"], allowed)
        logger.info(
            f"XrecCapture: trimmed segment {segment['index']} "
            f"from {segment['frames']} to {allowed} frames"
        )
        segment["frames"] = allowed
        segment["duration"] = allowed / self.fps

    def _make_black_clip(self, path: str, width: int, height: int, frames: int):
        result = run_ffmpeg(
            [
                "-y",
                "-f", "lavfi",
                "-i", f"color=c=black:s={width}x{height}:r={self.fps}",
                "-frames:v", str(frames),
                *h264_encoder_args(),
                path,
            ]
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create pause gap clip: {result.stderr[-500:]}")

    def _concat(self, paths, output_path, width, height):
        os.makedirs(self.segments_dir, exist_ok=True)
        list_path = os.path.join(self.segments_dir, "concat.txt")
        with open(list_path, "w") as f:
            for path in paths:
                f.write(f"file '{path}'\n")

        result = run_ffmpeg(
            ["-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-c", "copy", "-movflags", "+faststart", output_path]
        )
        if result.returncode == 0:
            return

        # Segments differ (e.g. display resolution changed): re-encode.
        logger.warning("XrecCapture: stream copy concat failed, re-encoding.")
        result = run_ffmpeg(
            ["-y", "-f", "concat", "-safe", "0", "-i", list_path,
             "-vf", f"scale={width}:{height}",
             "-fps_mode", "cfr", "-r", str(self.fps),
             *h264_encoder_args(),
             "-movflags", "+faststart", output_path]
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to join video segments: {result.stderr[-500:]}")


def find_screen_devices() -> dict:
    """{display index: avfoundation device number} from FFmpeg's device list."""
    output = run_ffmpeg(["-f", "avfoundation", "-list_devices", "true", "-i", ""]).stderr
    return {
        int(screen): device
        for device, screen in re.findall(r"\[(\d+)\]\s+Capture screen (\d+)", output)
    }


class MultiCapture:
    """
    Captures every display as its own video (native resolution each). The main
    display is display 0 and keeps the file name video.mp4.
    """

    def __init__(self, recording_path: str, displays: list, fps: int = VIDEO_FPS):
        devices = find_screen_devices()
        self.captures = []
        for display in displays:
            device = devices.get(display["index"])
            if device is None:
                logger.warning(f"MultiCapture: no capture device for display {display['index']}")
                continue
            self.captures.append(
                XrecCapture(recording_path, fps, display["index"], screen_device=device)
            )
        if not self.captures:
            raise RuntimeError("cudAI could not find a screen capture device.")

    @property
    def primary(self) -> XrecCapture:
        return self.captures[0]

    def _start_all(self) -> dict:
        # Launch every display first so they start together, then wait. If any
        # display fails, stop all of them: never leave a capture running.
        try:
            for capture in self.captures:
                capture.launch_segment()
            segments = [capture.await_segment_start() for capture in self.captures]
        except Exception:
            for capture in self.captures:
                capture.abort()
            raise
        return segments[0]

    def start_recording(self) -> dict:
        return self._start_all()

    def resume_recording(self) -> dict:
        return self._start_all()

    def pause_recording(self, requested_at: float | None = None):
        for capture in self.captures:
            capture.stop_segment(requested_at)

    def stop_recording(self, requested_at: float | None = None):
        for capture in self.captures:
            capture.stop_segment(requested_at)

    def ready_chunks(self) -> list:
        return [c for capture in self.captures for c in capture.ready_chunks()]

    def finalize(self) -> list:
        """Video info per display; the main display must succeed."""
        results = [self.primary.finalize()]
        for capture in self.captures[1:]:
            try:
                results.append(capture.finalize())
            except Exception:
                logger.exception(f"MultiCapture: display {capture.display_index} failed")
        return results
