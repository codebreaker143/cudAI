from core.a11y_listener import clean_text
from core.export import clock_anchors, to_unix


def test_wall_clock_stays_correct_across_system_sleep():
    # Recording starts at perf 1000 / unix 5000. The Mac sleeps 800 s at
    # perf 1350; perf_counter does not advance during sleep.
    metadata = {
        "clock": {"perf_counter": 1000.0, "unix_time": 5000.0},
        "clock_anchors": [{"perf_counter": 1351.0, "unix_time": 6151.0}],
    }
    anchors = clock_anchors(metadata)
    assert to_unix(1100.0, anchors) == 5100.0  # before sleep
    assert to_unix(1400.0, anchors) == 6200.0  # after sleep: +800 s
    assert to_unix(999.0, anchors) == 4999.0  # before start


def test_without_anchors_falls_back_to_start_clock():
    anchors = clock_anchors({"clock": {"perf_counter": 10.0, "unix_time": 100.0}})
    assert to_unix(15.0, anchors) == 105.0
    assert to_unix(15.0, clock_anchors({})) is None


def test_recorder_records_anchor_when_clocks_diverge(monkeypatch):
    import core.recorder as recorder_module
    from core.recorder import Recorder

    anchors = []

    class FakeMetadata:
        def add_clock_anchor(self, perf, unix, slept):
            anchors.append((perf, unix, round(slept)))

    rec = Recorder.__new__(Recorder)
    rec._last_clock = None
    rec.metadata_manager = FakeMetadata()
    readings = iter([(100.0, 1000.0), (101.0, 1001.0), (102.0, 1802.0)])
    perf_unix = {}

    def fake_perf():
        perf_unix["now"] = next(readings)
        return perf_unix["now"][0]

    monkeypatch.setattr(recorder_module.time, "perf_counter", fake_perf)
    monkeypatch.setattr(recorder_module.time, "time", lambda: perf_unix["now"][1])
    for _ in range(3):
        rec._check_clock()
    assert anchors == [(102.0, 1802.0, 800)]


def test_invisible_direction_marks_are_removed():
    assert clean_text("\u200EWhatsApp") == "WhatsApp"
    assert clean_text(None) is None
