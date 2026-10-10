from core import device_profile as dp


def hw(apple=True, cores=5, mem=18.0, battery=False):
    return {"apple_silicon": apple, "performance_cores": cores, "memory_gb": mem, "on_battery": battery}


def test_tiers_from_hardware():
    assert dp.hardware_tier(hw()) == "high"  # M3 Pro
    assert dp.hardware_tier(hw(cores=4, mem=16)) == "standard"  # base M-series
    assert dp.hardware_tier(hw(mem=8)) == "low"
    assert dp.hardware_tier(hw(apple=False, cores=8, mem=32)) == "low"  # Intel


def test_profile_settings_and_battery(monkeypatch):
    monkeypatch.delenv("CUDAI_TIER", raising=False)
    dp.set_override(None)
    low = dp.current(hw(mem=8))
    assert (low["tier"], low["capture_scale"], low["fps"]) == ("low", "logical", 15)
    assert dp.current(hw())["ocr_threads"] == 4
    assert dp.current(hw(battery=True))["ocr_threads"] == 3


def test_override_and_downgrade_after_backlog(monkeypatch):
    monkeypatch.delenv("CUDAI_TIER", raising=False)
    dp.set_override(None)
    dp.report_backlog(300)
    first = dp.current(hw(), consume_downgrade=True)
    assert first["tier"] == "standard" and "behind" in first["reason"]
    assert dp.current(hw())["tier"] == "high"  # only the next recording
    dp.set_override("low")
    assert dp.current(hw())["tier"] == "low"
    dp.set_override(None)
