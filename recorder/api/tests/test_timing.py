import json
import multiprocessing
import time

from core import timing


def test_stage_records_duration_and_extra_fields(tmp_path):
    with timing.stage(str(tmp_path), "ocr", chunk="c0", frames=3) as info:
        time.sleep(0.01)
        info["lines"] = 12
    (row,) = timing.load(str(tmp_path))
    assert row["stage"] == "ocr" and row["chunk"] == "c0"
    assert row["frames"] == 3 and row["lines"] == 12 and row["seconds"] >= 0.01


def test_summary_percentiles_and_lag(tmp_path):
    for i, seconds in enumerate([1, 2, 3, 4, 10]):
        timing.record(str(tmp_path), "ocr", 100, 100 + seconds, chunk=f"c{i}")
        timing.record(str(tmp_path), "chunk_uploaded", 100, 100 + seconds, lag_seconds=seconds * 2)
    summary = timing.summary(str(tmp_path))
    assert summary["stages"]["ocr"] == {"count": 5, "total": 20, "p50": 3, "p95": 10, "max": 10}
    assert summary["chunk_lag"]["p50"] == 6


def _write_many(path, tag):
    for i in range(300):
        timing.record(path, "stage", 0, 1, chunk=f"{tag}-{i}", padding="x" * 200)


def test_two_processes_can_log_to_the_same_file(tmp_path):
    procs = [multiprocessing.Process(target=_write_many, args=(str(tmp_path), t)) for t in "ab"]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    lines = (tmp_path / timing.TIMINGS_FILE).read_text().splitlines()
    assert len(lines) == 600
    assert all(json.loads(line)["stage"] == "stage" for line in lines)
