from __future__ import annotations

from enum import Enum

ROOT_KEY = ""
NULL_KEY = "NULL"
OTHER_EVENT_TYPES = {
    "balk",
    "batter_timeout",
    "defensive_switch",
    "game_advisory",
    "mound_visit",
    "offensive_substitution",
    "passed_ball",
    "pitching_substitution",
    "stolen_base_2b",
    "stolen_base_3b",
}
ALL_HIT_METRICS = [
    'coordinates',
    'hardness',
    'launchAngle',
    'launchSpeed',
    'location',
    'totalDistance',
    'trajectory'
]
ALL_PITCH_METRICS = [
    'breaks',
    'coordinates',
    'endSpeed',
    'extension',
    'plateTime',
    'startSpeed',
    'strikeZoneBottom',
    'strikeZoneTop',
    'typeConfidence',
    'zone'
]
VIDEO_URL_ROOT = "https://www.mlb.com/video/"


class PlayResult(str, Enum):
    IN_PLAY = "IN_PLAY"
    STRIKE = "STRIKE"
    BALL = "BALL"

    @classmethod
    def from_bools(
        cls, is_in_play: bool, is_strike: bool, is_ball: bool
    ) -> "PlayResult":
        assert (
            is_in_play + is_strike + is_ball == 1
        ), f"Unknown play result compability: {is_in_play=} {is_strike=} {is_ball=}"

        if is_in_play:
            return cls.IN_PLAY
        elif is_strike:
            return cls.STRIKE
        elif is_ball:
            return cls.BALL
        else:
            raise RuntimeError()


class Trajectory(str, Enum):
    BUNT_GROUNDER = "bunt_grounder"
    FLY_BALL = "fly_ball"
    GROUND_BALL = "ground_ball"
    LINE_DRIVE = "line_drive"
    POPUP = "popup"


class PlayEventType(str, Enum):
    ACTION = "action"
    NO_PITCH = "no_pitch"
    PICKOFF = "pickoff"
    PITCH = "pitch"
