"""Deterministic synthetic recording (realistic mix of input) for reducer tests."""
import json
import os
import random


def write_synthetic_recording(path: str, hours: float = 0.1, seed: int = 7) -> None:
    os.makedirs(path, exist_ok=True)
    rec_id = os.path.basename(path)
    HOURS = hours
    random.seed(seed)

    T0 = 1_000_000.0
    end = T0 + HOURS * 3600
    events, windows = [], []
    t = T0
    x, y = 700.0, 500.0
    idx = 0
    APPS = [("SAP GUI", "com.sap.gui"), ("Microsoft Excel", "com.microsoft.Excel"), ("Google Chrome", "com.google.Chrome"), ("Workday", "com.google.Chrome")]


    def add(e):
        nonlocal idx
        e["event_idx"] = idx
        idx += 1
        events.append(e)


    def key(action, name, ts, mods=(), text=None):
        add({"time_stamp": ts, "action": action, "name": name, "vk": None, "char": text,
             "text": text if action == "press" else None, "modifiers": sorted(mods), "pynput_key": name})


    next_window = T0
    while t < end:
        if t >= next_window:
            app = random.choice(APPS)
            windows.append({"time_stamp": t, "top_window_name": app[0], "app_name": app[0], "bundle_id": app[1],
                            "pid": 100, "window_title": f"{app[0]} - doc {random.randint(1, 50)}",
                            "window_bounds": {"x": 0, "y": 38, "width": 1512, "height": 944}, "is_recorder": False})
            next_window = t + random.uniform(15, 60)
        kind = random.choices(["move", "click", "type", "hotkey", "scroll", "idle"], [30, 25, 15, 5, 10, 15])[0]
        if kind == "move":
            for _ in range(random.randint(30, 120)):  # 0.5-2 s at 60 Hz
                x = min(1511, max(0, x + random.uniform(-15, 15)))
                y = min(981, max(0, y + random.uniform(-15, 15)))
                t += 1 / 60
                add({"time_stamp": t, "action": "move", "x": x, "y": y})
        elif kind == "click":
            add({"time_stamp": t, "action": "click", "x": x, "y": y, "button": "left", "pressed": True})
            t += random.uniform(0.06, 0.15)
            add({"time_stamp": t, "action": "click", "x": x, "y": y, "button": "left", "pressed": False})
        elif kind == "type":
            for ch in random.choice(["PO-4500012345", "Quarterly invoice", "vendor@acme.com", "1200.50", "Approved"]):
                name = ch.lower() if ch.isalnum() else {"-": "-", " ": "space", "@": "2", ".": "."}.get(ch, ch)
                mods = {"shift"} if ch.isupper() or ch == "@" else set()
                if mods:
                    key("press", "shift", t)
                key("press", name, t + 0.01, mods, ch)
                key("release", name, t + 0.08, mods)
                if mods:
                    key("release", "shift", t + 0.09)
                t += random.uniform(0.08, 0.25)
        elif kind == "hotkey":
            k = random.choice(["c", "v", "s", "z", "tab"])
            key("press", "cmd", t)
            key("press", k, t + 0.05, {"cmd"})
            key("release", k, t + 0.12, {"cmd"})
            key("release", "cmd", t + 0.18)
            t += 0.2
        elif kind == "scroll":
            for _ in range(random.randint(5, 30)):
                add({"time_stamp": t, "action": "scroll", "x": x, "y": y, "dx": 0, "dy": random.choice([-1, 1])})
                t += 0.016
        t += random.uniform(0.2, 2.5)

    with open(os.path.join(path, "events.jsonl"), "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    with open(os.path.join(path, "top_window.jsonl"), "w") as f:
        for w in windows:
            f.write(json.dumps(w) + "\n")
    for name in ("element.jsonl", "html.jsonl"):
        open(os.path.join(path, name), "w").close()
    metadata = {
        "schema_version": "cudai.recording.v1", "recording_id": rec_id, "screen_width": 1512, "screen_height": 982,
        "start_time": "2026-10-04T10:00:00+05:30", "clock": {"perf_counter": T0, "unix_time": 1_790_000_000.0},
        "video_start_timestamp": T0 + 0.5, "pauses": [], "display": {"logical_width": 1512, "logical_height": 982, "scale_factor": 2.0},
        "video": {"file": "video.mp4", "fps": 30, "width": 3024, "height": 1964, "duration": HOURS * 3600,
                  "video_start_timestamp": T0 + 0.5, "segments": [], "paused_gaps": []},
    }
    json.dump(metadata, open(os.path.join(path, "metadata.json"), "w"))
    open(os.path.join(path, "video.mp4"), "w").close()  # processing no longer reads the video
    open(os.path.join(path, "task_name.json"), "w").write(json.dumps({"task_name": "Soak", "description": ""}))

