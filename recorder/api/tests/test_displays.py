import json

from core.displays import display_at, segments_dir_name, video_file_name
from core.export import build_timeline

LEFT = {"index": 0, "bounds": {"x": 0, "y": 0, "width": 1512, "height": 982}}
RIGHT = {"index": 1, "bounds": {"x": 1512, "y": -200, "width": 1920, "height": 1080}}

def test_point_belongs_to_the_display_containing_it():
    displays = [LEFT, RIGHT]
    assert display_at(displays, 10, 10) == 0
    assert display_at(displays, 1511.9, 981) == 0
    assert display_at(displays, 1512, 0) == 1
    assert display_at(displays, 2000, -150) == 1  # above the main display
    assert display_at(displays, 5000, 5000) is None

def test_file_names_keep_main_display_compatible():
    assert video_file_name(0) == "video.mp4" and segments_dir_name(0) == "segments"
    assert video_file_name(2) == "video_display_2.mp4"
    assert segments_dir_name(2) == "segments_display_2"

def test_timeline_tags_pointer_events_with_display(tmp_path):
    events = [
        {"time_stamp": 10.0, "action": "click", "x": 100, "y": 100, "button": "left", "pressed": True, "event_idx": 0},
        {"time_stamp": 11.0, "action": "click", "x": 2500, "y": 300, "button": "left", "pressed": True, "event_idx": 1},
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    metadata = {"video_start_timestamp": 9.0, "displays": [LEFT, RIGHT]}
    timeline = build_timeline(str(tmp_path), metadata)
    assert [e["display"] for e in timeline] == [0, 1]
