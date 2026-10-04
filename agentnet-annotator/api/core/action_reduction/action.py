from collections import OrderedDict
from copy import deepcopy
from typing import List, Optional

from .reduction_helper import (
    MODIFIED_KEYS,
    MOUSE_LONG_PRESS_INTERVAL,
    wrap_func_key,
    typed_key_name,
)
from ..logger import logger


class ActionBuilder:
    @staticmethod
    def build(event):
        action_type = event["action"]
        if action_type == "move":
            return Move(event)
        elif action_type == "click":
            return Click(event)
        elif action_type == "press":
            key_name = event["name"]
            if key_name not in MODIFIED_KEYS:
                return Type(event)
            else:
                return Press(event)
        elif action_type == "type":
            return Type(event)
        elif action_type == "scroll":
            return Scroll(event)
        else:
            raise ValueError(f"Event type {action_type} is not supported.")


class Action:
    def __init__(self, event) -> None:
        self.pre_move = None
        if "pre_move" in event:
            self.pre_move = Move(event["pre_move"])
        # TODO: each action should have action id and event start, end id
        self.event_start_idx = event["event_idx"]
        self.children: Optional[List[Action]] = None
        self.complete: bool = event["complete"]
        self.action: str = event["action"]
        self.start_time: float = event["start_time"]
        self.end_time: float = event["end_time"]
        self.key: tuple = event["key"]
        self.transformed: bool = False
        self.description: str = None
        self.vis: bool = True
        self.show_all_move: bool = False
        self.exception = False
        self.depth = 0
        self.base_ignore_attrs: list = [
            "vis_dump_attrs",
            "ignore_log_attr_names",
            "complete_dump_excluded_attrs",
            "key",
            "show_all_move",
            "transformed",
            "excluded_attrs",
            "base_ignore_attrs",
            "pre_move",
            "children",
            "action_start_video_buffer_time",
            "action_end_video_buffer_time",
        ]

        self.complete_dump_excluded_attrs: list = self.base_ignore_attrs
        self.vis_dump_attrs: list = [
            "id",
            "action",
            "description",
            "start_time",
            "end_time",
            "time_stamp",
            "depth"
        ]

        self.action_start_video_buffer_time = 0.5
        self.action_end_video_buffer_time = 0.2
        self.target = None
        self.axtree = None
        self.past_frame_target = None
        self.gpt_target = None

    def set_id(self, id: int):
        self.id = id

    def get_start_time(self) -> float:
        if self.pre_move is not None:
            return self.pre_move.get_start_time()
        else:
            return self.start_time

    def get_str(self, connect_str=""):
        s = wrap_func_key(self.key_names[0])
        for i in range(1, len(self.key_names)):
            s += connect_str + wrap_func_key(self.key_names[i])
        return s

    def get_end_time(self) -> float | None:
        if self.end_time is not None:
            return self.end_time
        elif self.children is None:
            return self.start_time
        else:
            return self.children[-1].get_end_time()

    def set_pre_move(self, action):
        if isinstance(action, dict):
            self.pre_move = Move(action)
        else:
            self.pre_move = action

    def add_child(self, child_action):
        if not isinstance(child_action, Action):
            child_action = ActionBuilder.build(child_action)

        if self.children is None:
            self.children = []

        self.children.append(child_action)

    def transform(self):
        self.transformed = True

    def complete_dump(self):
        """
        Dump the action's information into a Dict
        Presever the complete information as the raw data.
        """
        attrs = vars(self)

        ordered_attrs = OrderedDict()
        ordered_attrs["action"] = self.action

        self.complete_dump_excluded_attrs += [
            key
            for key in attrs
            if attrs[key] is None or key in self.complete_dump_excluded_attrs
        ]

        for k, v in attrs.items():
            if k not in self.complete_dump_excluded_attrs and k not in ordered_attrs:
                ordered_attrs[k] = v

        if self.pre_move is not None:
            ordered_attrs["pre_move"] = self.pre_move.complete_dump()
        if self.children is not None:
            ordered_attrs["children"] = [
                child.complete_dump() for child in self.children
            ]

        return ordered_attrs

    def vis_dump(self):
        """
        Dump the action into a Dict
        Simplify attributes for visualization
        """
        if self.vis == False:
            return None

        attrs = vars(self)

        ordered_attrs = OrderedDict()
        for k in self.vis_dump_attrs:
            if k in attrs and k not in ordered_attrs:
                ordered_attrs[k] = attrs[k]

        if self.target is not None:
            ordered_attrs["target"] = self.target
        else:
            ordered_attrs["target"] = {"mark": False}

        if self.gpt_target is not None:
            ordered_attrs["gpt_target"] = self.gpt_target

        ordered_attrs["axtree"] = self.axtree
        if self.past_frame_target is not None:
            ordered_attrs["past_frame_target"] = self.past_frame_target

        if self.children is not None and len(self.children) > 0:
            ordered_attrs["children"] = []
            for child in self.children:
                if child.vis == True:
                    child_attrs = child.vis_dump()
                    ordered_attrs["children"].append(child_attrs)
        if "children" in ordered_attrs and len(ordered_attrs["children"]) == 0:
            del ordered_attrs["children"]

        return ordered_attrs

class Move(Action):
    def __init__(self, event):
        super().__init__(event)
        self.trace = event["trace"]
        self.time_trace = event["time_trace"]
        self.vis = False

    def transform(self):
        super().transform()
        self.description = "Mouse move from {} to {}".format(
            self.trace[0], self.trace[-1]
        )


class Type(Action):
    def __init__(self, event):
        super().__init__(event)
        if event["action"] == "type":
            self.action = event["action"]
            self.key_names = event["key_names"]
            
        elif event["action"] == "press":
            self.action = "type"
            self.key_names = [typed_key_name(event)]
            
        self.time_trace = [event["time_stamp"]]
        self.end_time = self.time_trace[-1] + 0.2
        
        self.action_start_video_buffer_time = 0.5
        self.action_end_video_buffer_time = 0.2

    def append(self, event):
        if isinstance(event, dict):
            self.key_names.append(typed_key_name(event))
            self.time_trace.append(event["time_stamp"])
            self.end_time = self.time_trace[-1] + 0.2
        elif isinstance(event, Type):
            self.key_names.extend(event.key_names)
            self.time_trace.extend(event.time_trace)
            self.end_time = self.time_trace[-1] + 0.2

    def extend(self, action):
        self.key_names.extend(action.key_names)
        self.time_trace.extend(action.time_trace)
        self.end_time = self.time_trace[-1] + 0.2

    def transform(self):
        super().transform()
        self.description = "⌨️ Type: "
        for key in self.key_names:
            self.description += wrap_func_key(key)
        logger.debug("transform {}".format(self.key_names))

class Click(Action):  # single, double, triple, drag
    def __init__(self, event):
        super().__init__(event)
        self.click_type = 1
        self.button = event["button"]
        self.pressed = event["pressed"]
        self.coordinate = {"x": event["x"], "y": event["y"]}
        self.coordinates = [{"x": event["x"], "y": event["y"]}]
        self.time_trace = [
            {"start_time": event["start_time"], "end_time": event["end_time"]}
        ]
        if self.pressed == False:
            self.vis = False
        self.action_start_video_buffer_time = 0.5
        self.action_end_video_buffer_time = 0.1

    def _is_long_press(self):
        if self.children:
            if len(self.children) == 1 and self.children[0].action == "click":
                return False
            else:
                logger.debug("is_long_press")
                logger.debug(f"{self.action}, {self.children[0].action}")
                return self.end_time - self.start_time > MOUSE_LONG_PRESS_INTERVAL
        else:
            return False

    def cal_distance(self, mouse_action):
        if isinstance(mouse_action, Click):
            return (
                (self.coordinate["y"] - mouse_action.coordinate["y"]) ** 2
                + (self.coordinate["x"] - mouse_action.coordinate["x"]) ** 2
            ) ** 0.5
        elif isinstance(mouse_action, dict):
            return (
                (self.coordinate["y"] - mouse_action["y"]) ** 2
                + (self.coordinate["x"] - mouse_action["x"]) ** 2
            ) ** 0.5
        else:
            raise ValueError(
                f"Click cal_distance: {type(mouse_action)} type not supported."
            )

    def _is_drag(self):
        if self.children and len(self.children) == 1:
            child_action = self.children[0]
            if child_action.pre_move is not None:
                if self.cal_distance(child_action) > 6:  # TODO: need time?
                    logger.debug(f"{self.action} is drag")
                    return True
        return False

    def transform(self):
        super().transform()
        if self.pressed == False:  # TODO
            self.description = ""
            return

        if self.children and len(self.children) > 0:
            for child in self.children:
                if child.transformed == False:
                    child.transform()

        if self.click_type == 1:
            self.description = "Single {} Click".format(self.button)
        elif self.click_type == 2:
            self.description = "Double {} Click".format(self.button)
        elif self.click_type == 3:
            self.description = "Triple {} Click".format(self.button)
        else:
            self.description = "{} Click".format(self.button)

        if self._is_drag():
            self.action = "drag"
            child_action = self.children.pop(-1)
            self.children.append(child_action.pre_move)
            self.description = "Drag from ({}, {}) to ({}, {})".format(
                self.coordinate["x"],
                self.coordinate["y"],
                child_action.coordinate["x"],
                child_action.coordinate["y"],
            )
            return

        if self._is_long_press():
            self.action = "mouse_press"
            self.description = "Mouse long press {} button:\n".format(self.button)
            if self.children and len(self.children) > 0:
                for child in self.children:
                    if child.description:
                        self.description += child.description + "\n"

    def is_no_move_between_complete_click(self, click_action):
        if click_action.pre_move is None:
            return True
        elif self.cal_distance(click_action) < 4:
            return True
        else:
            return False

    def set_exception_end_event(self):
        self.complete = True
        duration = 0.5
        self.end_time = self.start_time + duration
        self.time_trace[-1]["end_time"] = self.start_time + duration
        self.exception = True
        exception_action = deepcopy(self)
        exception_action.start_time = self.start_time + duration
        exception_action.end_time = self.start_time + duration
        exception_action.pre_move = None
        exception_action.pressed = False
        exception_action.key = (
            exception_action.key[0], not exception_action.key[1])

        self.add_child(exception_action)

    def set_complete_event(self, event):  # TODO: no release coordinate
        self.end_time = event["time_stamp"]
        self.complete = True
        self.time_trace[-1]["end_time"] = event["time_stamp"]

    # TODO: already done / use this function
    def append(self, event):
        self.click_type += 1
        self.coordinates.append({"x": event["x"], "y": event["y"]})
        self.time_trace.append(
            {"start_time": event["start_time"], "end_time": event["end_time"]}
        )
        self.end_time = event["end_time"]

class Press(Action):  # type, press, long press
    def __init__(self, event):
        super().__init__(event)

        self.key_name = event["name"]
        self.complete = event["complete"]
        self.pressed = self.key[-1]
        self.action_start_video_buffer_time = 0.3
        self.action_end_video_buffer_time = 0.2

    def set_complete_event(self, event: dict):
        self.end_time = event["time_stamp"]
        self.complete = True

    def is_typing(self) -> bool:
        if (
            self.complete
            and self.children is not None
            and len(self.children) == 1
            and isinstance(self.children[0], Type)
            and "shift" in self.key_name
        ):
            return True
        else:
            return False

    def transform(self):
        if self.exception:
            self.description = "⌨️ Press: {}".format(
                wrap_func_key(self.key_name))
            return

        super().transform()
        if self.pressed == False:  # TODO
            return

        if not self.children:
            self.description = "⌨️ Press: {}".format(
                wrap_func_key(self.key_name))
            return

        # TODO: sort by time, include child action
        if len(self.children) > 1:
            for i in range(len(self.children) - 1, 0, -1):
                if (
                    self.children[i - 1].end_time and self.children[i].end_time
                    and self.children[i - 1].start_time < self.children[i].start_time
                    and self.children[i - 1].end_time > self.children[i].end_time
                ):
                    logger.debug("Reducer: re-arrange: {} {} {}".format(
                        i-1, i, self.children[i].key))
                    child = self.children.pop(i)
                    self.children[i - 1].add_child(child)

        if self.children and len(self.children) > 0:
            for child in self.children:
                if child.transformed == False:
                    child.transform()

        if len(self.children) == 1:
            if self.children[0].action == "type":
                self.description = "⌨️ Press: {} + {}".format(
                    wrap_func_key(self.key_name), self.children[0].get_str()
                )
                self.children[0].vis = False

            elif self.children[0].action == "press":  # TODO: modify
                self.description = (
                    f"⌨️ Press: {wrap_func_key(self.key_name)} + "
                    + self.children[0].description.lstrip("⌨️ Press: ")
                )
            else:
                self.action = "long_press"
                self.description = "⌨️ Long Press: {}".format(
                    wrap_func_key(self.key_name)
                )
        else:
            self.action = "long_press"
            self.description = "⌨️ Long Press: {}".format(
                wrap_func_key(self.key_name))

        
        
    def set_exception_end_event(self):
        self.complete = True
        duration = 0.01
        self.end_time = self.start_time + duration
        self.exception = True
        exception_action = deepcopy(self)
        exception_action.start_time = self.start_time + duration
        exception_action.end_time = self.start_time + duration
        exception_action.pre_move = None
        exception_action.pressed = False
        exception_action.key = (
            exception_action.key[0], not exception_action.key[1])

        self.add_child(exception_action)


class Scroll(Action):
    def __init__(self, event):
        super().__init__(event)
        self.trace = event["trace"]
        self.time_trace = event["time_trace"]

        self.action_start_video_buffer_time = 0.5
        self.action_end_video_buffer_time = 0.2

    def extend(self, event):
        if event["action"] != self.action:
            raise ValueError(
                "Scroll extend error: action not match {}".format(
                    event["action"])
            )

        self.trace.extend(event["trace"])
        self.time_trace.extend(event["time_trace"])
        self.end_time = event["end_time"]

    def _get_direction_icon(self, dx, dy):
        if dx:
            dx /= abs(dx)
        if dy:
            dy /= abs(dy)
        direction2icon = {
            (0, 1): "⬆️",
            (0, -1): "⬇️",
            (1, 0): "⬅️",
            (-1, 0): "➡️",
            (1, 1): "↖",
            (-1, 1): "↗",
            (1, -1): "↙",
            (-1, -1): "↘",
        }
        return direction2icon[(dx, dy)]

    def _get_direction_text(self, dx, dy):
        if dx:
            dx /= abs(dx)
        if dy:
            dy /= abs(dy)
        direction2text = {
            (0, 1): "Up",
            (0, -1): "Down",
            (1, 0): "Left",
            (-1, 0): "Right",
            (1, 1): "Top Left",
            (-1, 1): "Top Right",
            (1, -1): "Bottom Left",
            (-1, -1): "Bottom Right",
        }
        return direction2text[(dx, dy)]

    def transform(self):
        super().transform()
        self.description = "Scroll "
        direction_count = {}
        for i in range(len(self.trace)):
            dx, dy = self.trace[i]["dx"], self.trace[i]["dy"]
            direction = self._get_direction_icon(dx, dy)
            if direction not in direction_count:
                direction_count[direction] = 1
            else:
                direction_count[direction] += 1

        for direction in direction_count:
            self.description += "{}×{}  ".format(
                direction, direction_count[direction])
