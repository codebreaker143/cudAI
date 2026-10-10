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
        # Redaction: shared Presidio rules, spaCy tokenizer, OCR models.
        "--paths", "../../privacy",
        "--hidden-import", "cudai_privacy.video",
        "--collect-all", "presidio_analyzer",
        "--collect-all", "spacy",
        "--collect-all", "thinc",
        "--collect-data", "phonenumbers",
        "--collect-data", "tldextract",
        "--collect-all", "rapidocr",
        "--copy-metadata", "presidio-analyzer",
        # Installed for development/tests only; never needed at runtime.
        "--exclude-module", "cryptography",
        "--exclude-module", "PyQt6",
        "--exclude-module", "pytest",
        "--exclude-module", "boto3",
        "--exclude-module", "botocore",
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
        "--exclude-module", "cryptography",
        "--exclude-module", "PyQt6",
        "--exclude-module", "pytest",
        "--runtime-hook", "runtime-hook.py",
        "--distpath", "./dist",
        "--collect-all", "comtypes",
        "backend.py"
    ]

# Fetch the OCR models now, so they ship inside the app (no download at runtime).
run([sys.executable, "-c", "from rapidocr import RapidOCR; RapidOCR()"], check=True)

try:
    run(pyinstaller_cmd, check=True, env=os.environ)
except CalledProcessError as e:
    print("An error occurred while running PyInstaller:", e)
    sys.exit(1)
