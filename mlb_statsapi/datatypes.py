from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence

import pandas as pd

from .constants import (
    NULL_KEY,
    VIDEO_URL_ROOT,
    PlayEventType,
    PlayResult,
    Trajectory,
)

logger = logging.getLogger(__name__)


FAKE_DEFAULT: Any = object()


def decimal_from_float(f: float) -> Decimal:
    return Decimal(str(f))


@dataclass
class Metadata:
    keys: list[str]

    def add_key(self, key: str) -> "Metadata":
        return Metadata(keys=list(self.keys) + [key])

    def add_keys(self, keys: list[str]) -> "Metadata":
        return Metadata(keys=list(self.keys) + keys)

    def add_key_i(self, i: int) -> "Metadata":
        return self.add_key(f"[{i}]")

    def __str__(self) -> str:
        return ".".join(self.keys)

    def __repr__(self) -> str:
        return str(self)


@dataclass
class Base:
    _raw: dict[str, Any] = field(repr=False)
    _metadata: Metadata = field(
        default_factory=lambda: Metadata(keys=[NULL_KEY]), repr=False
    )  # TODO Verify this creates new copy of list
    # Used for passing optional extra data to decorate the object
    _extra_fields: dict[str, Any] = field(default_factory=dict)

    # TODO Add a post post init to check that no FAKE_DEFAULT are still there
    def init_helper(self) -> None:
        # logger.debug(f"{type(self)} {self._metadata}")
        pass

    # __getattr__ is only call if the attribute is not found by default (default call is to __getattribute__)
    # Override the fallback behavior so that it looks in the underlying object before raising an error
    # TODO also look for snake case names
    def __getattr__(self, __name: str) -> Any:
        if __name in self._raw:
            return self._raw[__name]

        if __name in self._extra_fields:
            return self._extra_fields[__name]

        raise AttributeError(
            f"'{self.__class__.__name__}' object has no attribute '{__name}'"
        )


@dataclass
class PlayVideo(Base):
    id: str = field(default=FAKE_DEFAULT, init=False)
    slug: str = field(default=FAKE_DEFAULT, init=False)

    def __post_init__(self):
        self.init_helper()

        self.id = self._raw["mediaPlayback"][0]["id"]
        self.slug = self._raw["mediaPlayback"][0]["slug"]

    @property
    def video_url(self) -> str:
        return f"{VIDEO_URL_ROOT}{self.slug}"


@dataclass
class PlayVideos(Base):
    play_videos: list[PlayVideo] = field(default=FAKE_DEFAULT, init=False)

    def __post_init__(self):
        self.init_helper()

        self.play_videos = [
            PlayVideo(
                play_video,
                self._metadata.add_key("plays").add_key_i(i),
                {**self._extra_fields},
            )
            for i, play_video in enumerate(self._raw["data"]["search"]["plays"])
        ]

    @property
    def video_url_by_play_id(self) -> dict[str, str]:
        return {
            play_video.id: play_video.video_url
            for play_video in self.play_videos
        }


@dataclass
class Swing(Base):
    launch_angle: Decimal | None = field(default=FAKE_DEFAULT, init=False)
    launch_speed: Decimal | None = field(default=FAKE_DEFAULT, init=False)
    total_distance: Decimal | None = field(default=FAKE_DEFAULT, init=False)
    trajectory: Trajectory | None = field(default=FAKE_DEFAULT, init=False)

    def __post_init__(self):
        self.init_helper()

        self.launch_angle = (
            decimal_from_float(self._raw["launchAngle"])
            if "launchAngle" in self._raw
            else None
        )
        self.launch_speed = (
            decimal_from_float(self._raw["launchSpeed"])
            if "launchSpeed" in self._raw
            else None
        )
        self.total_distance = (
            decimal_from_float(self._raw["totalDistance"])
            if "totalDistance" in self._raw
            else None
        )
        self.trajectory = Trajectory(self._raw["trajectory"])


@dataclass
class Pitch(Base):
    start_speed: Decimal = field(init=False)
    end_speed: Decimal = field(init=False)
    spin_rate: int = field(init=False)
    spin_direction: int = field(init=False)
    zone: int = field(init=False)

    def __post_init__(self):
        self.init_helper()

        self.start_speed = decimal_from_float(self._raw["startSpeed"])
        self.end_speed = decimal_from_float(self._raw["endSpeed"])
        self.spin_rate = self._raw["breaks"]["spinRate"]
        self.spin_direction = self._raw["breaks"]["spinDirection"]
        self.zone = self._raw["zone"]

    @property
    def velocity(self) -> Decimal:
        return self.start_speed


@dataclass
class PlayEvent(Base):
    play_event_type: PlayEventType = field(init=False)
    play_id: str | None = None
    swing: Swing | None = None
    pitch: Pitch | None = None
    play_result: PlayResult | None = None
    description: str | None = None
    batter_name: str | None = None
    pitcher_name: str | None = None

    _play_video: str | None = None

    def __post_init__(self):
        self.init_helper()

        self.play_event_type = PlayEventType(self._raw["type"])
        # self.play_result = PlayResult.from_bools(self._raw['details']['isInPlay'], self._raw['details']['isStrike'], self._raw['details']['isBall'])

        if self.play_event_type != PlayEventType.PITCH:
            return

        self.play_id = self._raw["playId"]
        self.swing = (
            Swing(
                self._raw["hitData"],
                self._metadata.add_key("hitData"),
                {**self._extra_fields},
            )
            if "hitData" in self._raw
            else None
        )
        self.pitch = (
            Pitch(
                self._raw["pitchData"],
                self._metadata.add_key("pitchData"),
                {**self._extra_fields},
            )
            if self._raw["isPitch"]
            else None
        )

        self.description = self._raw["details"]["description"]

        if "matchup" in self._extra_fields:
            self.batter_name = self._extra_fields["matchup"]["batter"][
                "fullName"
            ]
            self.pitcher_name = self._extra_fields["matchup"]["pitcher"][
                "fullName"
            ]

    @property
    def play_video(self) -> str | None:
        # If video link == "", then that means we have already checked it and cannot get the video
        if self._play_video == "":
            return None
        elif self._play_video != None:
            return self._play_video

        # If the decoration is in the extra fields, use that
        if "play_videos" in self._extra_fields:
            play_videos: PlayVideos = self._extra_fields["play_videos"]
            self._play_video = play_videos.video_url_by_play_id.get(
                self.play_id, ""
            )
            return self._play_video or None

        if not (self.batter_name and self.pitcher_name and self.description):
            self._play_video = ""
            return None

        # Transform to url format
        pitcher_name = self.pitcher_name.lower().replace(" ", "-")
        batter_name = self.batter_name.lower().replace(" ", "-")
        description = (
            self.description.lower()
            .replace("(", "-")
            .replace(")", "-")
            .replace(" ", "-")
            .replace(",", "")
            .strip("-")
        )

        url = f"{VIDEO_URL_ROOT}{pitcher_name}-{description}-to-{batter_name}"

        return url


@dataclass
class Play(Base):
    play_events: list[PlayEvent] = field(init=False)

    def __post_init__(self):
        self.init_helper()

        self.play_events = [
            PlayEvent(
                play_event,
                _metadata=self._metadata.add_key("playEvents").add_key_i(i),
                _extra_fields={
                    **self._extra_fields,
                    "matchup": self._raw["matchup"],
                },
            )
            for i, play_event in enumerate(self._raw["playEvents"])
        ]

    @property
    def play_ids(self) -> list[str]:
        parent_attr = "play_events"
        a1 = "play_id"
        return [getattr(o, a1) for o in getattr(self, parent_attr)]

    @property
    def pitches_by_play_id(self) -> dict[str, Pitch]:
        parent_attr = "play_events"
        a1, a2 = "play_id", "pitch"
        return {
            getattr(o, a1): getattr(o, a2)
            for o in getattr(self, parent_attr)
            if getattr(o, a1) is not None
        }

    @property
    def swings_by_play_id(self) -> dict[str, Swing]:
        parent_attr = "play_events"
        a1, a2 = "play_id", "swing"
        return {
            getattr(o, a1): getattr(o, a2)
            for o in getattr(self, parent_attr)
            if getattr(o, a1) is not None
        }

    @property
    def play_event_by_play_id(self) -> dict[str, PlayEvent]:
        parent_attr = "play_events"
        a1 = "play_id"
        return {
            getattr(o, a1): o
            for o in getattr(self, parent_attr)
            if getattr(o, a1) is not None
        }
    
    @property
    def play_video_by_play_id(self) -> dict[str, str]:
        parent_attr = "play_events"
        a1, a2 = "play_id", "play_video"
        return {
            getattr(o, a1): getattr(o, a2)
            for o in getattr(self, parent_attr)
            if getattr(o, a1) is not None
        }


@dataclass
class Game(Base):
    plays: list[Play] = field(init=False)

    def __post_init__(self):
        self.init_helper()
        base_metadata = self._metadata.add_keys(
            ["liveData", "plays", "allPlays"]
        )
        self.plays = [
            Play(play, base_metadata.add_key_i(i), {**self._extra_fields})
            for i, play in enumerate(self._raw["liveData"]["plays"]["allPlays"])
        ]

    @property
    def play_ids(self) -> list[str]:
        return [elt for p in self.plays for elt in p.play_ids]

    @property
    def pitches_by_play_id(self) -> dict[str, Pitch]:
        return {
            k: v for p in self.plays for k, v in p.pitches_by_play_id.items()
        }

    @property
    def swings_by_play_id(self) -> dict[str, Swing]:
        return {
            k: v for p in self.plays for k, v in p.swings_by_play_id.items()
        }

    @property
    def play_event_by_play_id(self) -> dict[str, PlayEvent]:
        return {
            k: v for p in self.plays for k, v in p.play_event_by_play_id.items()
        }
    
    @property
    def play_video_by_play_id(self) -> dict[str, str]:
        return {
            k: v for p in self.plays for k, v in p.play_video_by_play_id.items()
        }

    def get_filtered_pitch_metrics_by_play_id(
        self, metrics: list[str], play_ids: Sequence[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        pitches_by_play_id = self.pitches_by_play_id
        if play_ids:
            pitches_by_play_id = {
                k: v for k, v in pitches_by_play_id.items() if k in play_ids
            }
        return {
            play_id: {metric: getattr(pitch, metric) for metric in metrics}
            for play_id, pitch in pitches_by_play_id.items()
        }

    def get_filtered_pitch_metrics_by_play_id_as_df(
        self, metrics: list[str], play_ids: Sequence[str] | None = None
    ) -> pd.DataFrame:
        return pd.DataFrame.from_dict(
            self.get_filtered_pitch_metrics_by_play_id(
                metrics, play_ids=play_ids
            ),
            orient="index",
        )

    def get_filtered_swing_metrics_by_play_id(
        self, metrics: list[str], play_ids: Sequence[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        swings_by_play_id = self.swings_by_play_id
        if play_ids:
            swings_by_play_id = {
                k: v for k, v in swings_by_play_id.items() if k in play_ids
            }
        return {
            play_id: {
                metric: getattr(swing, metric, None) for metric in metrics
            }
            for play_id, swing in swings_by_play_id.items()
        }

    def get_filtered_swing_metrics_by_play_id_as_df(
        self, metrics: list[str], play_ids: Sequence[str] | None = None
    ) -> pd.DataFrame:
        return pd.DataFrame.from_dict(
            self.get_filtered_swing_metrics_by_play_id(
                metrics, play_ids=play_ids
            ),
            orient="index",
        )
