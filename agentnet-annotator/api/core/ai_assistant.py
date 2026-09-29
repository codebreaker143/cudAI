import requests
import os
import json

from flask import jsonify, request

from .constants import FAILED, SUCCEED, SERVER_URL
from .logger import logger
from .utils import extract_frames_from_video, find_mp4, RECORDING_DIR, REVIEW_RECORDING_DIR, read_encrypted_jsonl

def predict_targets(recording_path, events):
    """
    Local-first V1.

    AgentNet originally sent screenshots and actions to its remote
    /interpret_actions service to infer missing UI targets.

    xrec does not use external AI services during recording/reduction.
    """
    logger.info(
        f"Skipping remote target prediction for {len(events)} event(s)"
    )
    return []