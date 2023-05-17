import inspect
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Type

import requests

from .constants import ROOT_KEY
from .datatypes import Base, Game, Metadata


class BaseRequest(ABC):
    BASE_URI = "https://statsapi.mlb.com/api"
    VERSION: str = "v1.1"
    API_PATH: str  # TODO Make this prevent creating an instance of this class
    DATATYPE: Type[Base]

    @property
    def class_obj(self):
        return type(self)

    @property
    def params(self) -> dict[str, str]:
        params = vars(self)

        # Assumes that all class variables are before first private method
        class_vars = inspect.getmembers(self.class_obj)
        for i in range(len(class_vars)):
            if class_vars[i][0][:2] == "__":
                break
        class_vars = class_vars[:i]

        params.update({k: v for k, v in class_vars})
        return params

    @property
    def request_uri(self) -> str:
        return f"{self.BASE_URI}{self.API_PATH}".format(**self.params)

    def make_request(self) -> Any:
        self._raw: dict = requests.get(self.request_uri).json()
        self.data = self.class_obj.DATATYPE(
            Metadata(keys=[ROOT_KEY]), self._raw
        )
        return self.data


class GameRequest(BaseRequest):
    API_PATH: str = "/{VERSION}/game/{game_pk}/feed/live"
    DATATYPE = Game

    def __init__(self, game_pk: int | str) -> None:
        self.game_pk = game_pk
