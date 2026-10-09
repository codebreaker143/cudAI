import threading
import time

import core.a11y_listener as listener_module
from core.a11y_listener import A11yListener, sanitize_url


def test_url_keeps_state_but_redacts_secrets_and_pii():
    assert (
        sanitize_url("https://erp.example.com/po/4500?session=SECRET&user=a@b.com#step2")
        == "https://erp.example.com/po/4500?session=[SECRET]&user=[EMAIL]#step2"
    )
    assert sanitize_url(None) is None


def window(pid, title, bundle="com.example.app"):
    return {"app_name": f"App{pid}", "bundle_id": bundle, "pid": pid,
            "window_title": title, "window_bounds": None}


def test_window_flicker_is_ignored_and_changes_are_recorded(monkeypatch):
    # One poll of an untitled helper window between steady states must not
    # produce records; a real switch must.
    sequence = [window(1, "Inbox")] * 3 + [window(1, "")] + [window(1, "Inbox")] * 2 + [window(2, "Ledger")] * 3
    feed = iter(sequence)
    done = threading.Event()

    def next_info():
        try:
            return next(feed)
        except StopIteration:
            done.set()
            return sequence[-1]

    monkeypatch.setattr(listener_module, "get_active_app_info", next_info)
    monkeypatch.setattr(listener_module, "enable_full_accessibility", lambda pid, bundle: {})
    monkeypatch.setattr(A11yListener, "POLL_INTERVAL", 0.001)

    listener = A11yListener(False, False)
    listener.running = True
    thread = threading.Thread(target=listener._get_top_window)
    started = time.perf_counter()
    thread.start()
    done.wait(5)
    listener.running = False
    thread.join()

    records = []
    while not listener.top_window_queue.empty():
        records.append(listener.top_window_queue.get())
    assert [(r["pid"], r["window_title"]) for r in records] == [(1, "Inbox"), (2, "Ledger")]
    assert all(r["time_stamp"] >= started for r in records)
