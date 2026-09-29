import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path


class XrecCapture:
    def __init__(self, recording_path: str, fps: int = 30):
        self.recording_path = recording_path
        self.fps = fps
        self.process = None
        self.log_file = None

    def _ffmpeg_path(self) -> str:
        # Packaged application
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return str(Path(sys._MEIPASS) / "ffmpeg" / "ffmpeg")

        # Development
        return str(Path(__file__).resolve().parents[1] / "ffmpeg")

    def _find_screen_device(self) -> str:
        ffmpeg = self._ffmpeg_path()

        result = subprocess.run(
            [
                ffmpeg,
                "-f", "avfoundation",
                "-list_devices", "true",
                "-i", ""
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        output = result.stderr

        match = re.search(
            r"\[(\d+)\]\s+Capture screen 0",
            output
        )

        if not match:
            match = re.search(
                r"\[(\d+)\]\s+Capture screen",
                output
            )

        if not match:
            raise RuntimeError(
                "xrec could not find a screen capture device."
            )

        return match.group(1)

    def start_recording(self):
        if self.process and self.process.poll() is None:
            raise RuntimeError("Recording is already running.")

        ffmpeg = self._ffmpeg_path()
        screen_device = self._find_screen_device()

        output_path = os.path.join(
            self.recording_path,
            "video.mp4"
        )

        log_path = os.path.join(
            self.recording_path,
            "ffmpeg.log"
        )

        self.log_file = open(log_path, "a")

        command = [
            ffmpeg,
            "-y",

            "-f", "avfoundation",
            "-framerate", str(self.fps),

            "-capture_cursor", "1",
            "-capture_mouse_clicks", "1",

            "-pixel_format", "nv12",

            "-i", f"{screen_device}:none",

            "-c:v", "libx264",
            "-preset", "ultrafast",

            "-vf", "format=yuv420p",

            "-movflags", "+faststart",

            output_path
        ]

        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self.log_file
        )

        # Give FFmpeg a moment to fail if something is wrong.
        time.sleep(0.7)

        if self.process.poll() is not None:
            if self.log_file:
                self.log_file.close()

            raise RuntimeError(
                "xrec screen capture failed to start. "
                f"See {log_path}"
            )

    def stop_recording(self):
        if not self.process:
            return

        if self.process.poll() is None:
            try:
                # Graceful FFmpeg shutdown so MP4 is finalized correctly.
                self.process.stdin.write(b"q\n")
                self.process.stdin.flush()
                self.process.wait(timeout=10)

            except Exception:
                try:
                    self.process.send_signal(signal.SIGINT)
                    self.process.wait(timeout=5)

                except Exception:
                    self.process.kill()

        self.process = None

        if self.log_file:
            self.log_file.close()
            self.log_file = None

    def pause_recording(self):
        if self.process and self.process.poll() is None:
            os.kill(self.process.pid, signal.SIGSTOP)

    def resume_recording(self):
        if self.process and self.process.poll() is None:
            os.kill(self.process.pid, signal.SIGCONT)
