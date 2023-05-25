from __future__ import annotations

import re
from typing import Any


def explore_object(data: Any, path: str, print_val: bool = False) -> set[Any]:
    if path == "":
        if print_val:
            print(data)

        if type(data) == list:
            return {"LIST"}
        elif type(data) == dict:
            return set(data.keys())
        else:
            return {data}
    elif path[:3] == ".[]":
        res = set()
        assert (
            type(data) == list
        ), f"Unexpected type on path {path} of {type(data)}"
        for elt in data:
            res |= explore_object(elt, path[3:])
        return res
    elif re.search("^\.\[[0-9]+\]", path):  # Match a specific index
        assert (
            type(data) == list
        ), f"Unexpected type on path {path} of {type(data)}"
        i = int(path[2 : path.find("]")])
        return explore_object(data[i], path[path.find("]") + 1 :])
    elif path[0] == ".":
        assert (
            type(data) == dict
        ), f"Unexpected type on path {path} of {type(data)}"
        i = path.find(".", 1)
        path_end = i == -1
        key = path[1:] if path_end else path[1:i]
        if key not in data:
            return {None}
        if path_end:
            return explore_object(data[key], "")
        return explore_object(data[key], path[i:])
    else:
        raise RuntimeError(f"Unable to parse path {path}")


BLACKLISTED_KEYS = {
    ".gameData.players",
    ".liveData.boxscore.teams.away.players",
    ".liveData.boxscore.teams.home.players",
}


def list_attributes(data: Any, key: str = "") -> Any:
    if key in BLACKLISTED_KEYS:
        return ("TRUNCATED", None)

    if type(data) == dict:
        res = {}
        for k, v in data.items():
            next_key = f"{key}.{k}"
            res[next_key] = list_attributes(v, next_key)
        return ("dict", res)
    elif type(data) == list:
        next_key = f"{key}.[]"
        if len(data) == 0:
            return ("list", None)
        elt = data[
            0
        ]  # TODO Have this look at all elements and collate the results instead of just the first element
        attributes = list_attributes(elt, next_key)
        if not attributes[1]:
            return (f"list[{attributes[0]}]", None)
        else:
            return ("list[object]", attributes)
    else:
        return (type(data).__name__, None)


def print_attributes(key: str, attributes: Any, indent: int = 0) -> None:
    type_name = attributes[0]
    indent_str = "    " * indent
    prefix = f"{indent_str}{key}"
    prefix = f"{prefix:<70}"

    if attributes[1] is None:
        print(f"{prefix}\t\t{type_name}")
    elif isinstance(attributes[1], tuple):
        print(f"{prefix}\t\t{type_name}")
        print_attributes(key, attributes[1], indent)
    else:
        print(f"{prefix}\t\t{type_name}")
        for k, v in attributes[1].items():
            print_attributes(k, v, indent + 1)


def all_attributes(attributes: Any) -> set[str]:
    type_name = attributes[0]

    if attributes[1] is None:
        # terminal type so don't need to do anything furtehr
        return set()
    elif isinstance(attributes[1], tuple):
        return all_attributes(attributes[1])
    else:
        # it is a dictionary
        res = set()
        for k, v in attributes[1].items():
            if v[0] != "dict":
                res.add(k)
            res |= all_attributes(v)
        return res
