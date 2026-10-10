"""
Benchmark on-device redaction on fixed sample chunks.

    python -m core.bench <dir of .mp4 chunks> [--threads 4] [--max-side 1600]
                         [--interval 15] [--json out.json]

For each chunk: wall time, CPU time (this process plus FFmpeg), seconds per
stage (decode, change detection, OCR, Presidio, mask, encode), OCR passes and
what was masked. Use the same chunks before and after a change; run with
`taskpolicy -c background` and --threads 2 to approximate a low-end Mac.
"""

import argparse
import json
import os
import resource
import tempfile
import time


def _cpu_seconds() -> float:
    own = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return own.ru_utime + own.ru_stime + children.ru_utime + children.ru_stime


def run(chunks: list, threads: int, settings) -> list:
    from cudai_privacy.video import redact_video

    from .redaction import RapidOcr
    from .utils import get_ffmpeg_path, h264_encoder_args

    ocr = RapidOcr(threads=threads)
    results = []
    with tempfile.TemporaryDirectory() as work:
        for path in chunks:
            stages = {}
            wall, cpu = time.perf_counter(), _cpu_seconds()
            result = redact_video(
                path, os.path.join(work, "out.mp4"), ocr, get_ffmpeg_path(), h264_encoder_args(),
                settings=settings, on_timing=lambda stage, seconds, **_: stages.__setitem__(stage, round(seconds, 2)),
            )
            results.append({
                "chunk": os.path.basename(path),
                "wall": round(time.perf_counter() - wall, 2),
                "cpu": round(_cpu_seconds() - cpu, 2),
                "ocr_frames": result["ocr_frames"],
                "lines_recognised": result.get("lines_recognised"),
                "lines_reused": result.get("lines_reused"),
                "masked": result["masked"],
                "entities": result["entities"],
                **stages,
            })
    return results


def main() -> None:
    from cudai_privacy.video import Settings

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chunks")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-side", type=int, default=Settings.analysis_max_side)
    parser.add_argument("--interval", type=int, default=Settings.min_ocr_interval)
    parser.add_argument("--json")
    args = parser.parse_args()

    chunks = sorted(os.path.join(args.chunks, f) for f in os.listdir(args.chunks) if f.endswith(".mp4"))
    settings = Settings(analysis_max_side=args.max_side, min_ocr_interval=args.interval)
    results = run(chunks, args.threads, settings)
    columns = ["chunk", "wall", "cpu", "ocr_frames", "lines_recognised", "lines_reused",
               "decode", "change_detection", "ocr", "presidio", "mask", "encode"]
    print(" ".join(f"{c:>16}" for c in columns) + "  masked")
    for r in results:
        print(" ".join(f"{str(r.get(c, '-')):>16}" for c in columns) + f"  {r['entities'] or '-'}")
    print(f"{'total':>16} {sum(r['wall'] for r in results):>16.2f} {sum(r['cpu'] for r in results):>16.2f}")
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"threads": args.threads, "settings": vars(settings), "results": results}, f, indent=2)


if __name__ == "__main__":
    main()
