"""Tests for the neutral StatsApiClient.

Self-contained: they mock ``requests`` and never touch the network or
biomech_studio, so they pass with only ``mlb-statsapi[dev]`` installed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
import requests

from mlb_statsapi.statsapi import StatsApiAuthError, StatsApiClient, StatsApiError


class FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, *, json_raises: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload
        self._json_raises = json_raises

    def json(self) -> Any:
        if self._json_raises:
            raise ValueError("No JSON object could be decoded")
        return self._payload


def client_with_response(response: FakeResponse | Exception) -> StatsApiClient:
    """A client whose single HTTP call yields ``response`` (value or raises)."""
    client = StatsApiClient()
    session = Mock()
    if isinstance(response, Exception):
        session.get.side_effect = response
    else:
        session.get.return_value = response
    client._session = session
    return client


class TestStatusHandling:
    def test_401_raises_auth_error(self) -> None:
        client = client_with_response(FakeResponse(401))
        with pytest.raises(StatsApiAuthError):
            client.get_game_guids(1, access_token="bad")

    def test_404_not_found_ok_returns_none(self) -> None:
        client = client_with_response(FakeResponse(404))
        assert client.get_person(999999999) is None

    def test_404_without_not_found_ok_raises(self) -> None:
        client = client_with_response(FakeResponse(404))
        with pytest.raises(StatsApiError):
            client.get_schedule()

    def test_500_raises_error(self) -> None:
        client = client_with_response(FakeResponse(503))
        with pytest.raises(StatsApiError):
            client.get_schedule()

    def test_transport_error_raises_error(self) -> None:
        client = client_with_response(requests.ConnectionError("boom"))
        with pytest.raises(StatsApiError):
            client.get_schedule()

    def test_non_json_2xx_raises_error(self) -> None:
        client = client_with_response(FakeResponse(200, json_raises=True))
        with pytest.raises(StatsApiError):
            client.get_schedule()


class TestResponseShapes:
    def test_get_person_unwraps_first(self) -> None:
        client = client_with_response(FakeResponse(200, {"people": [{"id": 1}]}))
        assert client.get_person(1) == {"id": 1}

    def test_get_person_empty_body(self) -> None:
        assert client_with_response(FakeResponse(200, {})).get_person(1) is None
        assert client_with_response(FakeResponse(200, {"people": []})).get_person(1) is None
        assert client_with_response(FakeResponse(200, None)).get_person(1) is None

    def test_game_log_flattens_splits(self) -> None:
        payload = {
            "stats": [
                {"splits": [{"date": "2026-06-01"}, {"date": "2026-06-05"}]},
                {"splits": [{"date": "2026-06-09"}]},
                {},  # entry without splits tolerated
            ]
        }
        client = client_with_response(FakeResponse(200, payload))
        splits = client.get_person_game_log(660271, season=2026)
        assert [s["date"] for s in splits] == ["2026-06-01", "2026-06-05", "2026-06-09"]

    def test_game_log_empty_body(self) -> None:
        client = client_with_response(FakeResponse(200, {}))
        assert client.get_person_game_log(660271, season=2026) == []

    def test_schedule_flattens_dates(self) -> None:
        payload = {
            "dates": [
                {"games": [{"gamePk": 1}, {"gamePk": 2}]},
                {"games": [{"gamePk": 3}]},
            ]
        }
        client = client_with_response(FakeResponse(200, payload))
        games = client.get_schedule(start_date="2026-06-01", end_date="2026-06-02")
        assert [g["gamePk"] for g in games] == [1, 2, 3]

    def test_guids_non_list_raises(self) -> None:
        client = client_with_response(FakeResponse(200, {"unexpected": True}))
        with pytest.raises(StatsApiError):
            client.get_game_guids(1, access_token="tok")

    def test_get_game_pitchers_shapes_boxscore(self) -> None:
        payload = {
            "teams": {
                "away": {
                    "team": {"name": "Mets"},
                    "pitchers": [660271],
                    "players": {"ID660271": {"person": {"fullName": "Shohei Ohtani"}}},
                },
                "home": {"team": {"name": "Braves"}, "pitchers": [], "players": {}},
            }
        }
        client = client_with_response(FakeResponse(200, payload))
        pitchers = client.get_game_pitchers(745123)
        assert pitchers == [{"pitcher_id": 660271, "name": "Shohei Ohtani", "team": "Mets"}]
