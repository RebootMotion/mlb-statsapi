from dataclasses import dataclass, field
from typing import Any, Optional
from decimal import Decimal
from enum import Enum
import logging
from constants import OTHER_EVENT_TYPES, PlayResult, Trajectory

logger = logging.getLogger(__name__)





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


@dataclass
class Base:
    _metadata: Metadata
    _raw: dict[str, Any] = field(repr=False)

    def init_helper(self) -> None:
        pass
        # logger.debug(f"{type(self)} {self._metadata}")



@dataclass
class Swing(Base):
    launch_angle: Decimal | None = field(init=False)
    launch_speed: Decimal | None = field(init=False)
    total_distance: Decimal | None = field(init=False)
    trajectory: Trajectory | None = field(init=False)

    def __post_init__(self):
        self.init_helper()

        self.launch_angle = decimal_from_float(self._raw['launchAngle']) if 'launchAngle' in self._raw else None
        self.launch_speed = decimal_from_float(self._raw['launchSpeed']) if 'launchSpeed' in self._raw else None
        self.total_distance = decimal_from_float(self._raw['totalDistance']) if 'totalDistance' in self._raw else None
        self.trajectory = Trajectory(self._raw['trajectory'])


@dataclass
class Pitch(Base):
    start_speed: Decimal = field(init=False)
    end_speed: Decimal = field(init=False)

    def __post_init__(self):
        self.init_helper()
        self.start_speed = decimal_from_float(self._raw['startSpeed'])
        self.end_speed = decimal_from_float(self._raw['endSpeed'])

    @property
    def velocity(self) -> Decimal:
        return self.start_speed


@dataclass
class PlayEvent(Base):
    swing: Swing | None = field(init=False)
    pitch: Pitch | None = field(init=False)

    def __post_init__(self):
        self.init_helper()
        if self._raw['details'].get('eventType', "") in OTHER_EVENT_TYPES:
            self.swing = self.pitch = None
            return
        # self.play_result = PlayResult.from_bools(self._raw)
        self.swing = Swing(self._metadata.add_key('hitData'), self._raw['hitData']) if 'hitData' in self._raw else None
        self.pitch = Pitch(self._metadata.add_key('pitchData'), self._raw['pitchData']) if self._raw["isPitch"] else None


@dataclass
# TODO A play can have multiple play events
class Play(Base):
    play_id: str = field(init=False)
    play_events: list[PlayEvent] = field(init=False)


    def __post_init__(self):
        self.init_helper()
        self.play_id = self._raw['playEvents'][-1]['playId']

        self.play_events = [PlayEvent(self._metadata.add_key('playEvents').add_key_i(i), play_event) for i, play_event in enumerate(self._raw['playEvents'])]



@dataclass
class Game(Base):
    plays: list[Play] = field(init=False)

    def __post_init__(self):
        self.init_helper()
        base_metadata = self._metadata.add_keys(['liveData', 'plays', 'allPlays'])
        self.plays = [Play(base_metadata.add_key_i(i), play) for i, play in enumerate(self._raw['liveData']['plays']['allPlays'])]

    @property
    def play_ids(self) -> list[str]:
        return [p.play_id for p in self.plays]
    



