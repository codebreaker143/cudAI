from core.action_reduction.preprocess import drop_recorder_app_events


def click(t, pressed=True):
    return {"time_stamp": t, "action": "click", "x": 1, "y": 1, "button": "left", "pressed": pressed}


def window(t, is_recorder):
    return {"time_stamp": t, "app_name": "cudAI" if is_recorder else "Excel", "is_recorder": is_recorder}


def test_input_to_recorder_window_is_dropped():
    windows = [window(0.0, False), window(10.0, True)]
    events = [click(5.0), click(5.1, False), click(11.0), click(11.1, False)]
    kept = drop_recorder_app_events(events, windows)
    assert [e["time_stamp"] for e in kept] == [5.0, 5.1]


def test_click_that_focuses_recorder_is_dropped():
    # The window poll notices the switch shortly after the click.
    windows = [window(0.0, False), window(10.2, True)]
    events = [click(10.0), click(10.1, False)]
    assert drop_recorder_app_events(events, windows) == []


def test_legacy_top_window_records_are_ignored():
    windows = [{"time_stamp": 0.0, "top_window_name": "Excel"}]
    events = [click(1.0)]
    assert drop_recorder_app_events(events, windows) == events
