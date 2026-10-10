"""
Spot-check the server's name removal.

    python -m cudai_ingest.qa sample --n 50 --out review/
        Exports N random frames from clean/ recordings as PNGs plus
        review.csv. A reviewer fills in `names_visible` (how many readable
        person names the frame still shows) and `notes`.

    python -m cudai_ingest.qa report review/review.csv
        Miss rate = reviewed frames still showing a name / reviewed frames.

If the miss rate is too high, or buyers ask for device-side guarantees, move
name removal onto the device (a small quantized GLiNER).
"""

import argparse
import csv
import json
import os
import random
import tempfile

from .worker import CLEAN, _parts

FIELDS = ["recording_id", "part", "frame", "image", "names_visible", "notes"]


def sample(storage, n: int, out_dir: str, seed: int | None = None) -> str:
    import cv2

    rng = random.Random(seed)
    candidates = []
    for recording_id in storage.list_ids(CLEAN):
        metadata = storage.read_json(f"{CLEAN}/{recording_id}/metadata.json") or {}
        candidates += [(recording_id, part) for part in _parts(metadata) if "/gap_" not in part]
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory() as work:
        for i in range(n if candidates else 0):
            recording_id, part = rng.choice(candidates)
            local = os.path.join(work, "chunk.mp4")
            storage.download(f"{CLEAN}/{recording_id}/{part}", local)
            video = cv2.VideoCapture(local)
            frame = rng.randrange(max(1, int(video.get(cv2.CAP_PROP_FRAME_COUNT))))
            video.set(cv2.CAP_PROP_POS_FRAMES, frame)
            ok, image_data = video.read()
            video.release()
            if not ok:
                continue
            image = f"{i:04d}_{recording_id[:8]}_{os.path.basename(part)[:-4]}_{frame}.png"
            cv2.imwrite(os.path.join(out_dir, image), image_data)
            rows.append({"recording_id": recording_id, "part": part, "frame": frame,
                         "image": image, "names_visible": "", "notes": ""})
    path = os.path.join(out_dir, "review.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def report(csv_path: str) -> dict:
    with open(csv_path, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["names_visible"].strip() != ""]
    missed = [r for r in rows if int(r["names_visible"]) > 0]
    return {
        "reviewed_frames": len(rows),
        "frames_with_names": len(missed),
        "miss_rate": round(len(missed) / len(rows), 4) if rows else None,
    }


def main() -> None:
    from .app import config_from_env
    from .storage import storage_from_config

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--n", type=int, default=50)
    s.add_argument("--out", default="review")
    s.add_argument("--seed", type=int)
    r = sub.add_parser("report")
    r.add_argument("csv")
    args = parser.parse_args()
    if args.command == "sample":
        storage = storage_from_config(config_from_env())
        print(sample(storage, args.n, args.out, args.seed))
    else:
        print(json.dumps(report(args.csv), indent=2))


if __name__ == "__main__":
    main()
