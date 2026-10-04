import os
import json
import uuid
from flask import jsonify, request

from .logger import logger
from .export import write_export
from .utils import (
    RECORDING_DIR,
    cut_video,
    find_mp4,
    read_encrypted_jsonl,
    write_encrypted_json,
    write_encrypted_jsonl,
    write_jsonl
)

def annotate_task(recording_name, socketservice):
    """
    Payload:
        cutTaskName: new task name
        cutDescription: new task description
        valMin: start index of reduced_events_vis
        valMax: end index of reduced_events_vis

    Functionality:
        - Save new .jsonl and .json files
        - Save new video clips
        - Save new full video

    TODO:
        - read all files and write all files efficiently
    """

    folder_path = os.path.join(RECORDING_DIR, recording_name)
    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
        return jsonify({"error": "Recording not found"}), 404

    reduced_events_vis_path = os.path.join(folder_path, "reduced_events_vis.jsonl")
    reduced_events_vis = read_encrypted_jsonl(reduced_events_vis_path)

    data = request.json

    if "cutTaskName" not in data or not data["cutTaskName"]:
        logger.warning("annotate_task must have cutTaskName")
        return jsonify({"error": "annotate_task must have cutTaskName"}), 400

    task_name = data["cutTaskName"]
    description = data.get("cutDescription", "")
    start_idx = int(data["valMin"]) - 1
    end_idx = int(data["valMax"]) - 1

    if end_idx - start_idx + 1 == len(reduced_events_vis):
        write_encrypted_json(
            os.path.join(folder_path, "task_name.json"),
            {"task_name": task_name, "description": description},
        )

        write_export(folder_path)
        return jsonify({"success": "Save task name and description successfully"}), 200

    raw_events_path = os.path.join(folder_path, "events.jsonl")
    event_buffer_path = os.path.join(folder_path, "event_buffer.jsonl")
    reduced_events_complete_path = os.path.join(
        folder_path, "reduced_events_complete.jsonl"
    )
    element_path = os.path.join(folder_path, "element.jsonl")
    html_path = os.path.join(folder_path, "html.jsonl")
    metadata_path = os.path.join(folder_path, "metadata.json")

    # Fetch start and end timestamp

    reduced_events_vis = reduced_events_vis[start_idx : end_idx + 1]
    for idx in range(len(reduced_events_vis)):
        reduced_events_vis[idx]["id"] = idx
    start_timestamp = reduced_events_vis[0]["start_time"]
    end_timestamp = reduced_events_vis[-1]["end_time"]

    logger.info(f"Backend: cut_task: start_idx: {start_idx}, end_idx: {end_idx}")

    recording_id = str(uuid.uuid4())
    new_folder_path = os.path.join(RECORDING_DIR, recording_id)

    os.makedirs(new_folder_path, exist_ok=True)
    # events.jsonl
    with open(raw_events_path, encoding="utf-8") as f:
        raw_events = [json.loads(line) for line in f]
    new_raw_events = [
        event
        for event in raw_events
        if start_timestamp <= event["time_stamp"] <= end_timestamp
    ]
    write_jsonl(os.path.join(new_folder_path, "events.jsonl"), new_raw_events)

    # reduced_events_vis.jsonl
    write_encrypted_jsonl(
        os.path.join(new_folder_path, "reduced_events_vis.jsonl"), reduced_events_vis
    )

    # event_buffer.jsonl
    event_buffer = read_encrypted_jsonl(event_buffer_path)
    new_event_buffer = [
        event
        for event in event_buffer
        if start_timestamp <= event["time_stamp"] <= end_timestamp
    ]
    write_encrypted_jsonl(
        os.path.join(new_folder_path, "event_buffer.jsonl"), new_event_buffer
    )

    # reduced_events_complete.jsonl
    reduced_events_complete = read_encrypted_jsonl(reduced_events_complete_path)
    new_reduced_events_complete = [
        event
        for event in reduced_events_complete
        if start_timestamp <= event["start_time"] <= end_timestamp
    ]
    write_encrypted_jsonl(
        os.path.join(new_folder_path, "reduced_events_complete.jsonl"),
        new_reduced_events_complete,
    )

    # Optional: html.jsonl
    if os.path.exists(html_path):
        html_data = read_encrypted_jsonl(html_path)
        new_html = [
            event
            for event in html_data
            if start_timestamp <= event["time_stamp"] <= end_timestamp
        ]
        write_encrypted_jsonl(os.path.join(new_folder_path, "html.jsonl"), new_html)

    # Optional: element
    if os.path.exists(element_path):
        element = read_encrypted_jsonl(element_path)
        new_element = [
            event
            for event in element
            if start_timestamp <= event["time_stamp"] <= end_timestamp
        ]
        write_encrypted_jsonl(
            os.path.join(new_folder_path, "element.jsonl"), new_element
        )

    # Optional: axtree.jsonl
    axtree_path = os.path.join(folder_path, "axtree.jsonl")
    if os.path.exists(axtree_path):
        axtree = read_encrypted_jsonl(axtree_path)
        new_tree = [
            tree
            for tree in axtree
            if start_timestamp <= tree["time_stamp"] <= end_timestamp
        ]
        write_encrypted_jsonl(os.path.join(new_folder_path, "axtree.jsonl"), new_tree)

    write_encrypted_json(
        os.path.join(new_folder_path, "task_name.json"),
        {"task_name": task_name, "description": description},
    )

    # metadata.json
    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    old_start_timestamp = metadata["video_start_timestamp"]
    # Clips before the first frame are clamped by cut_video.
    new_video_start = max(start_timestamp, old_start_timestamp)
    metadata["parent_recording_id"] = metadata.get("recording_id", recording_name)
    metadata["recording_id"] = recording_id
    metadata["video_start_timestamp"] = new_video_start
    if isinstance(metadata.get("video"), dict):
        metadata["video"]["video_start_timestamp"] = new_video_start
        metadata["video"]["duration"] = end_timestamp - new_video_start
        metadata["video"]["segments"] = None
        metadata["video"]["paused_gaps"] = [
            gap for gap in metadata["video"].get("paused_gaps") or []
            if gap["end_timestamp"] > new_video_start
            and gap["start_timestamp"] < end_timestamp
        ]
    with open(
        os.path.join(new_folder_path, "metadata.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(metadata, f, indent=4)
    # top_window.jsonl
    top_window_path = os.path.join(folder_path, "top_window.jsonl")
    if os.path.exists(top_window_path):
        top_windows = read_encrypted_jsonl(top_window_path)
        new_top_windows = [
            window
            for window in top_windows
            if start_timestamp <= window["time_stamp"] <= end_timestamp
        ]
        write_encrypted_jsonl(
            os.path.join(new_folder_path, "top_window.jsonl"), new_top_windows
        )
    # edit full video
    old_video_path = find_mp4(folder_path)
    cut_video(
        old_video_path=os.path.join(folder_path, old_video_path),
        new_video_path=new_folder_path,
        start_time=start_timestamp - old_start_timestamp,
        end_time=end_timestamp - old_start_timestamp,
    )
    socketservice.emit(
        "reduced", 
        {
            "status": "succeed",
            "message": "stop_recording succeed."
        }
    )
    write_export(new_folder_path)
    return jsonify({"success": "Cut task successfully"}), 200


# legacy
def read_recording_status(recording_path):
    recording_status_path = os.path.join(recording_path, "recording_status.json")
    if os.path.exists(recording_status_path):
        with open(recording_status_path, "r", encoding="utf-8") as f:
            recording_status = json.load(f)
    else:
        recording_status = None
    return recording_status
