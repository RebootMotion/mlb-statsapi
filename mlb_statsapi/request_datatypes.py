from __future__ import annotations

import inspect
import json
from abc import ABC, abstractmethod
from typing import Any, Type

import requests
from requests.adapters import HTTPAdapter, Retry

from .constants import ROOT_KEY
from .datatypes import Base, Game, Metadata, PlayVideos





class BaseRequest(ABC):
    BASE_URI = "https://statsapi.mlb.com/api"
    VERSION: str = "v1.1"
    API_PATH: str = (
        ""  # TODO Make this prevent creating an instance of this class
    )
    DATA: str = "{{}}"
    DATATYPE: Type[Base]

    retries = Retry(total=3, backoff_factor=2, status_forcelist=[502, 503, 504])

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

    @property
    def data_payload(self) -> str:
        return f"{self.DATA}".format(**self.params)

    def decorators(self) -> dict[str, Any]:
        return {}

    # TODO Cache result
    def make_request(self) -> Any:
        session = requests.Session()
        session.mount("http://", HTTPAdapter(max_retries=self.retries))
        session.mount("https://", HTTPAdapter(max_retries=self.retries))
        self._raw: dict = session.get(self.request_uri).json()

        self.data = self.class_obj.DATATYPE(
            self._raw, Metadata(keys=[ROOT_KEY]), self.decorators()
        )
        return self.data


class GameRequest(BaseRequest):
    API_PATH: str = "/{VERSION}/game/{game_pk}/feed/live"
    DATATYPE = Game

    def __init__(self, game_pk: int | str) -> None:
        self.game_pk = game_pk

    def decorators(self) -> dict[str, Any]:
        self._play_video_request = PlayVideoRequest(game_pk=self.game_pk)
        return {"play_videos": self._play_video_request.make_request()}


class PlayVideoRequest(BaseRequest):
    BASE_URI = "https://fastball-gateway.mlb.com/graphql"
    DATA = '{{"query":"query Search($query: String!, $page: Int, $limit: Int, $feedPreference: FeedPreference, $languagePreference: LanguagePreference, $contentPreference: ContentPreference, $queryType: QueryType = STRUCTURED, $withPlaybacksSegments: Boolean = false) {{\\r\\n  search(query: $query, limit: $limit, page: $page, feedPreference: $feedPreference, languagePreference: $languagePreference, contentPreference: $contentPreference, queryType: $queryType) {{\\r\\n    plays {{\\r\\n      mediaPlayback {{\\r\\n        ...MediaPlaybackFields\\r\\n        __typename\\r\\n      }}\\r\\n      __typename\\r\\n    }}\\r\\n    total\\r\\n    __typename\\r\\n  }}\\r\\n}}\\r\\n\\r\\nfragment MediaPlaybackFields on MediaPlayback {{\\r\\n  id\\r\\n  slug\\r\\n  feeds {{\\r\\n    playbacks {{\\r\\n      segments @include(if: $withPlaybacksSegments)\\r\\n    }}\\r\\n  }}\\r\\n}}","variables":{{"withPlaybacksSegments":false,"query":"gamePk = {game_pk} Order By Timestamp ASC","limit":{max_videos},"page":0,"languagePreference":"EN","contentPreference":"MIXED"}}}}'
    DATATYPE = PlayVideos

    def __init__(self, game_pk: int | str, max_videos: int = 1000) -> None:
        self.game_pk = game_pk
        self.max_videos = max_videos

    # TODO Abstract away HTTP method type
    def make_request(self) -> Any:
        session = requests.Session()
        session.mount("http://", HTTPAdapter(max_retries=self.retries))
        session.mount("https://", HTTPAdapter(max_retries=self.retries))
        self._raw: dict = session.post(
            self.request_uri, data=self.data_payload
        ).json()
        self.data = self.class_obj.DATATYPE(
            self._raw, Metadata(keys=[ROOT_KEY])
        )
        return self.data
