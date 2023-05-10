from typing import Any
import re

def list_play_ids(game: dict) -> list[str]:
    plays = game['liveData']['plays']['allPlays']
    res = []
    for play in plays:
        res.append(play['playEvents'][-1]['playId'])
    return res


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
        assert type(data) == list, f"Unexpected type on path {path} of {type(data)}"
        for elt in data:
            res |= explore_object(elt, path[3:])
        return res
    elif re.search('^\.\[[0-9]+\]', path):  # Match a specific index
        assert type(data) == list, f"Unexpected type on path {path} of {type(data)}"
        i = int(path[2:path.find(']')])
        return explore_object(data[i], path[path.find(']')+1:])
    elif path[0] == ".":
        assert type(data) == dict, f"Unexpected type on path {path} of {type(data)}"
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

    pass
