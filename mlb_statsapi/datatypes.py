from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Sequence

import pandas as pd

from . import utils as ut
from .constants import (NULL_KEY, VIDEO_URL_ROOT, PlayEventType, PlayResult,
                        Trajectory)
from .decorators import t

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
        logger.debug(f"{type(self)} {self._metadata}")
        pass

    @classmethod
    def subclass_field_names(cls) -> set[str]:
        """
        Returns all explicitly defined fields in the subclass
        """
        parent_fields = {f.name for f in dataclasses.fields(Base)}
        field_names = {
            f.name
            for f in dataclasses.fields(cls)
            if f.name not in parent_fields
        }
        return field_names

    @property
    def all_terminal_fields(self) -> set[str]:
        """
        Returns all explicitly defined fields in the subclass plus all terminal fields in the raw json
        """
        dataclass_fields = self.subclass_field_names()
        raw_fields = ut.all_attributes(ut.list_attributes(self._raw))
        return dataclass_fields | raw_fields

    @property
    def flattened_values(self) -> dict[str, Any]:
        """
        Maps all terminal fields to their value
        """
        res = {}
        for k in self.all_terminal_fields:
            res[k] = self.get_flattened_value(k)
        return res

    def get_flattened_value(self, k: str) -> Any:
        """
        Enables you to get values multiple layers deep in the raw json object
        """
        # Use leading . to denote in _raw
        if k[0] == ".":
            v = ut.explore_object(self._raw, k)
            assert len(v) == 1
            return [*v][0]
        else:
            return getattr(self, k)

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

        self.id = t(lambda: self._raw["mediaPlayback"][0]["id"])
        self.slug = t(lambda: self._raw["mediaPlayback"][0]["slug"])

    @property
    def video_url(self) -> str:
        return f"{VIDEO_URL_ROOT}{self.slug}"


@dataclass
class PlayVideos(Base):
    play_videos: list[PlayVideo] = field(default=FAKE_DEFAULT, init=False)

    def __post_init__(self):
        self.init_helper()

        self.play_videos = t(
            lambda: [
                PlayVideo(
                    play_video,
                    self._metadata.add_key("plays").add_key_i(i),
                    {**self._extra_fields},
                )
                for i, play_video in enumerate(
                    self._raw["data"]["search"]["plays"]
                )
            ]
        )

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

        self.launch_angle = t(
            lambda: (
                decimal_from_float(self._raw["launchAngle"])
                if "launchAngle" in self._raw
                else None
            )
        )
        self.launch_speed = t(
            lambda: (
                decimal_from_float(self._raw["launchSpeed"])
                if "launchSpeed" in self._raw
                else None
            )
        )
        self.total_distance = t(
            lambda: (
                decimal_from_float(self._raw["totalDistance"])
                if "totalDistance" in self._raw
                else None
            )
        )
        self.trajectory = t(lambda: Trajectory(self._raw["trajectory"]))


@dataclass
class Pitch(Base):
    start_speed: Decimal = field(init=False)
    end_speed: Decimal = field(init=False)
    spin_rate: int | None = field(init=False)
    spin_direction: int | None = field(init=False)
    zone: int = field(init=False)

    def __post_init__(self):
        self.init_helper()

        self.start_speed = t(
            lambda: decimal_from_float(self._raw["startSpeed"])
        )
        self.end_speed = t(lambda: decimal_from_float(self._raw["endSpeed"]))
        self.spin_rate = t(lambda: self._raw["breaks"].get("spinRate"))
        self.spin_direction = t(
            lambda: self._raw["breaks"].get("spinDirection")
        )
        self.zone = t(lambda: self._raw["zone"])

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

        self.play_event_type = t(lambda: PlayEventType(self._raw["type"]))
        # self.play_result = PlayResult.from_bools(self._raw['details']['isInPlay'], self._raw['details']['isStrike'], self._raw['details']['isBall'])

        if self.play_event_type != PlayEventType.PITCH:
            return

        self.play_id = t(lambda: self._raw["playId"])
        self.swing = t(
            lambda: (
                Swing(
                    self._raw["hitData"],
                    self._metadata.add_key("hitData"),
                    {**self._extra_fields},
                )
                if "hitData" in self._raw
                else None
            )
        )
        self.pitch = t(
            lambda: (
                Pitch(
                    self._raw["pitchData"],
                    self._metadata.add_key("pitchData"),
                    {**self._extra_fields},
                )
                if self._raw["isPitch"]
                else None
            )
        )

        self.description = t(lambda: self._raw["details"]["description"])

        if "matchup" in self._extra_fields:
            self.batter_name = t(
                lambda: self._extra_fields["matchup"]["batter"]["fullName"]
            )
            self.pitcher_name = t(
                lambda: self._extra_fields["matchup"]["pitcher"]["fullName"]
            )

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

        self.play_events = t(
            lambda: [
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
        )

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
        base_metadata = t(
            lambda: self._metadata.add_keys(["liveData", "plays", "allPlays"])
        )
        self.plays = t(
            lambda: [
                Play(play, base_metadata.add_key_i(i), {**self._extra_fields})
                for i, play in enumerate(
                    self._raw["liveData"]["plays"]["allPlays"]
                )
            ]
        )

    @property
    def play_ids(self) -> list[str]:
        """
        :return: list of play ids for this game
        """
        return [elt for p in self.plays for elt in p.play_ids]

    @property
    def pitches_by_play_id(self) -> dict[str, Pitch]:
        """
        :return: Map of play id to pitch objects
        """
        return {
            k: v for p in self.plays for k, v in p.pitches_by_play_id.items()
        }

    @property
    def swings_by_play_id(self) -> dict[str, Swing]:
        """
        :return: Map of play id to swing objects
        """
        return {
            k: v for p in self.plays for k, v in p.swings_by_play_id.items()
        }

    @property
    def play_event_by_play_id(self) -> dict[str, PlayEvent]:
        """
        :return: Map of play id to play event objects
        """
        return {
            k: v for p in self.plays for k, v in p.play_event_by_play_id.items()
        }

    @property
    def play_video_by_play_id(self) -> dict[str, str]:
        """
        :return: Map of play id to play video url
        """
        return {
            k: v for p in self.plays for k, v in p.play_video_by_play_id.items()
        }

    def get_filtered_pitch_metrics_by_play_id(
        self,
        metrics: Sequence[str] | None = None,
        play_ids: Sequence[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """
        :param metrics: Optional list of metrics for the result. Omit to get all metrics
        :param play_ids: Optional list of play ids to filter down the result

        :result: Nested dictionary for plays and metrics
        """
        pitches_by_play_id = self.pitches_by_play_id
        if play_ids:
            pitches_by_play_id = {
                k: v for k, v in pitches_by_play_id.items() if k in play_ids
            }

        if metrics:
            return {
                play_id: {
                    metric: pitch.get_flattened_value(metric)
                    for metric in metrics
                }
                for play_id, pitch in pitches_by_play_id.items()
            }
        else:
            return {
                play_id: pitch.flattened_values
                for play_id, pitch in pitches_by_play_id.items()
            }

    def get_filtered_pitch_metrics_by_play_id_as_df(
        self,
        metrics: Sequence[str] | None = None,
        play_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """
        :param metrics: Optional list of metrics for the result. Omit to get all metrics
        :param play_ids: Optional list of play ids to filter down the result

        :result: DataFrame with plays and metrics
        """
        return pd.DataFrame.from_dict(
            self.get_filtered_pitch_metrics_by_play_id(
                metrics, play_ids=play_ids
            ),
            orient="index",
        )

    def get_filtered_swing_metrics_by_play_id(
        self,
        metrics: Sequence[str] | None = None,
        play_ids: Sequence[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """
        :param metrics: Optional list of metrics for the result. Omit to get all metrics
        :param play_ids: Optional list of play ids to filter down the result

        :result: Nested dictionary for plays and metrics
        """
        swings_by_play_id = self.swings_by_play_id
        if play_ids:
            swings_by_play_id = {
                k: v for k, v in swings_by_play_id.items() if k in play_ids
            }

        if metrics:
            return {
                play_id: {
                    metric: (
                        swing.get_flattened_value(metric) if swing else None
                    )
                    for metric in metrics
                }
                for play_id, swing in swings_by_play_id.items()
            }
        else:
            return {
                play_id: swing.flattened_values if swing else {"": None}
                for play_id, swing in swings_by_play_id.items()
            }

    def get_filtered_swing_metrics_by_play_id_as_df(
        self,
        metrics: Sequence[str] | None = None,
        play_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """
        :param metrics: Optional list of metrics for the result. Omit to get all metrics
        :param play_ids: Optional list of play ids to filter down the result

        :result: DataFrame with plays and metrics
        """
        return pd.DataFrame.from_dict(
            self.get_filtered_swing_metrics_by_play_id(
                metrics, play_ids=play_ids
            ),
            orient="index",
        )
