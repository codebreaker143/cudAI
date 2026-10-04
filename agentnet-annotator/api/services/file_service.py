"""File service for handling file operations and browser integration."""

import os
import time
from typing import Dict, Tuple

from core.logger import logger
from core.utils import (
    write_encrypt_line,
    init_encrpted_jsonl,
)
from core.dom_utils import convert_webpage_to_json_elements, prune_html
from core.constants import SUCCEED, FAILED


class FileService:
    """Service for handling file operations."""

    def __init__(self):
        self.active_recording_path = None

    def set_active_recording(self, recording_path: str) -> None:
        """Set the active recording path."""
        self.active_recording_path = recording_path

    def append_browser_element(self, element_data: Dict) -> Tuple[str, str]:
        """Append browser element data to recording."""
        if not self.active_recording_path:
            return FAILED, "No active recording"

        try:
            element_path = os.path.join(
                self.active_recording_path, "html_element.jsonl"
            )
            if not os.path.exists(element_path):
                init_encrpted_jsonl(path=element_path)

            element_entry = {
                "time_stamp": time.perf_counter(),
                "element": element_data,
            }

            with open(element_path, "a", encoding="utf-8") as f:
                write_encrypt_line(f, data=element_entry)

            return SUCCEED, "Element appended successfully"

        except Exception as e:
            logger.exception(f"FileService: append_browser_element failed: {e}")
            return FAILED, f"Failed to append element: {str(e)}"

    def append_browser_html(self, html_data: Dict) -> Tuple[str, str]:
        """Append browser HTML data to recording."""
        if not self.active_recording_path:
            return FAILED, "No active recording"

        try:
            html_path = os.path.join(self.active_recording_path, "html.jsonl")
            if not os.path.exists(html_path):
                init_encrpted_jsonl(html_path)

            html_entry = {
                "time_stamp": time.perf_counter(),
                "html": prune_html(html_data.get("data", {}).get("html", "")),
                "dom": convert_webpage_to_json_elements(
                    html_data.get("data", {}).get("dom", {})
                ),
                "url": html_data.get("data", {}).get("url", ""),
                "axtree": html_data.get("pageAxTree", {}),
            }

            with open(html_path, "a", encoding="utf-8") as f:
                write_encrypt_line(f, data=html_entry)

            return SUCCEED, "HTML appended successfully"

        except Exception as e:
            logger.exception(f"FileService: append_browser_html failed: {e}")
            return FAILED, f"Failed to append HTML: {str(e)}"


class AccessibilityService:
    """Service for handling accessibility tree operations."""

    def __init__(self):
        self.active_recording_path = None

    def set_active_recording(self, recording_path: str) -> None:
        """Set the active recording path."""
        self.active_recording_path = recording_path

    def save_accessibility_tree(self, axtree_data: Dict) -> Tuple[str, str]:
        """Save accessibility tree data."""
        if not self.active_recording_path:
            return FAILED, "No active recording"

        try:
            axtree_path = os.path.join(self.active_recording_path, "axtree.jsonl")
            if not os.path.exists(axtree_path):
                init_encrpted_jsonl(path=axtree_path)

            axtree_entry = {
                "time_stamp": time.perf_counter(),
                "data": axtree_data,
            }

            with open(axtree_path, "a", encoding="utf-8") as f:
                write_encrypt_line(f, data=axtree_entry)

            return SUCCEED, "Accessibility tree saved successfully"

        except Exception as e:
            logger.exception(
                f"AccessibilityService: save_accessibility_tree failed: {e}"
            )
            return FAILED, f"Failed to save accessibility tree: {str(e)}"

