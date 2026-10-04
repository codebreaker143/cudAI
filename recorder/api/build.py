import shutil
import sys
import os
from pathlib import Path
from platform import system
from subprocess import CalledProcessError, run

backend_dir = Path(".")
if system() == "Darwin":
    ffmpeg = backend_dir / "ffmpeg"
elif system() == "Windows":
    ffmpeg = backend_dir / "ffmpeg.exe"


for dir_to_remove in ["dist", "build"]:
    dir_path = backend_dir / dir_to_remove
    if dir_path.exists():
        shutil.rmtree(dir_path)

if system() == "Darwin":
    pyinstaller_cmd = [
        "pyinstaller", "--onedir",
        f"--add-data={ffmpeg}{';' if system() == 'Windows' else ':'}{ffmpeg}",
        "--add-data=licenses:licenses",
        "--hidden-import", "engineio.async_drivers.gevent",
        "--hidden-import", "geventwebsocket",
        # Installed for development/tests only; never needed at runtime.
        "--exclude-module", "cv2",
        "--exclude-module", "PIL",
        "--exclude-module", "cryptography",
        "--exclude-module", "PyQt6",
        "--exclude-module", "pytest",
        "--runtime-hook", "runtime-hook.py",
        "--distpath", "./dist",
        "backend.py"
    ]
else:
    pyinstaller_cmd = [
        "pyinstaller", "--onedir",
        f"--add-data={ffmpeg}{';' if system() == 'Windows' else ':'}{backend_dir / 'ffmpeg'}",
        "--hidden-import", "engineio.async_drivers.gevent",
        "--hidden-import", "geventwebsocket",
        # Installed for development/tests only; never needed at runtime.
        "--exclude-module", "cv2",
        "--exclude-module", "PIL",
        "--exclude-module", "cryptography",
        "--exclude-module", "PyQt6",
        "--exclude-module", "pytest",
        "--runtime-hook", "runtime-hook.py",
        "--distpath", "./dist",
        "--collect-all", "comtypes",
        "backend.py"
    ]

try:
    run(pyinstaller_cmd, check=True, env=os.environ)
except CalledProcessError as e:
    print("An error occurred while running PyInstaller:", e)
    sys.exit(1)
