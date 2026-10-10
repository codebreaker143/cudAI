"""
Rebuild a recording's videos from its uploaded parts.

The app uploads each display's 10-second chunks (redacted on the device)
and pause-gap clips, and metadata.json lists them in order
(displays[].video.parts). Videos are rebuilt from clean/ (after the
server's name removal), never from the raw uploads. Parts all encoded on the
device join with stream copy; if the server re-encoded some, the join is
re-encoded so the result decodes cleanly.

Usage: python -m cudai_ingest.assemble <recording id> <output dir>
(storage is configured with the same environment as the server)
"""

import os
import shutil
import subprocess
import sys
import tempfile

from .app import config_from_env
from .storage import storage_from_config


def _videos(metadata: dict) -> list:
    videos = [d["video"] for d in metadata.get("displays") or [] if d.get("video")]
    return videos or [metadata["video"]]


def assemble(storage, recording_id: str, out_dir: str, ffmpeg: str = "ffmpeg", prefix: str = "clean") -> list:
    """Write every display's video to out_dir; returns the file paths."""
    info = storage.read_json(f"{prefix}/{recording_id}/_clean.json") or {}
    mixed = "server" in (info.get("encoders") or {}).values()
    prefix = f"{prefix}/{recording_id}/"
    metadata = storage.read_json(prefix + "metadata.json")
    if metadata is None:
        raise FileNotFoundError(f"{recording_id}: metadata.json not uploaded yet")
    os.makedirs(out_dir, exist_ok=True)
    written = []
    with tempfile.TemporaryDirectory() as work:
        for video in _videos(metadata):
            parts = video.get("parts")
            if not parts:
                raise ValueError(f"{recording_id}: {video.get('file')} has no uploaded parts")
            local = []
            for i, part in enumerate(parts):
                dest = os.path.join(work, f"{i:05d}.mp4")
                storage.download(prefix + part, dest)
                local.append(dest)
            output = os.path.join(out_dir, video["file"])
            if len(local) == 1:
                shutil.copyfile(local[0], output)
            else:
                list_path = os.path.join(work, "concat.txt")
                with open(list_path, "w") as f:
                    f.writelines(f"file '{p}'\n" for p in local)
                codec = (["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
                         if mixed else ["-c", "copy"])
                result = subprocess.run(
                    [ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", list_path,
                     *codec, "-movflags", "+faststart", output],
                    capture_output=True, text=True,
                )
                if result.returncode != 0:
                    raise RuntimeError(f"ffmpeg failed: {result.stderr[-500:]}")
            for p in local:
                os.remove(p)
            written.append(output)
    return written


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    storage = storage_from_config(config_from_env())
    for path in assemble(storage, sys.argv[1], sys.argv[2]):
        print(path)


if __name__ == "__main__":
    main()
