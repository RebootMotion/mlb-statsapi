"""Tests for StatsApiClient.

Self-contained: they mock ``requests`` and never touch the network, so they
pass with only ``mlb-statsapi[dev]`` installed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
import requests

from mlb_statsapi.statsapi import StatsApiAuthError, StatsApiClient, StatsApiError


class FakeResponse:
    def __init__(
        self, status_code: int, payload: Any = None, *, json_raises: bool = False, content: bytes = b""
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self._json_raises = json_raises
        self.content = content

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


def sent_params(client: StatsApiClient) -> dict[str, Any]:
    """The query params of the last request the client issued."""
    return client._session.get.call_args.kwargs["params"]


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


class TestGetEscapeHatch:
    def test_get_reaches_an_unwrapped_endpoint(self) -> None:
        client = client_with_response(FakeResponse(200, {"teams": [{"id": 147}]}))
        assert client.get("/teams", params={"sportId": 1}) == {"teams": [{"id": 147}]}
        assert client._session.get.call_args.args[0].endswith("/teams")
        assert sent_params(client) == {"sportId": 1}

    def test_get_sends_bearer_when_token_given(self) -> None:
        client = client_with_response(FakeResponse(200, {}))
        client.get("/anything", access_token="tok")
        assert client._session.get.call_args.kwargs["headers"] == {"Authorization": "Bearer tok"}

    def test_get_no_auth_header_without_token(self) -> None:
        client = client_with_response(FakeResponse(200, {}))
        client.get("/anything")
        assert client._session.get.call_args.kwargs["headers"] is None


class TestEndpointMethods:
    def test_get_person_unwraps_single_person_envelope(self) -> None:
        client = client_with_response(FakeResponse(200, {"people": [{"id": 1}]}))
        assert client.get_person(1) == {"id": 1}

    def test_get_person_empty_body(self) -> None:
        assert client_with_response(FakeResponse(200, {})).get_person(1) is None
        assert client_with_response(FakeResponse(200, {"people": []})).get_person(1) is None
        assert client_with_response(FakeResponse(200, None)).get_person(1) is None

    def test_get_person_stats_returns_raw_entries(self) -> None:
        payload = {
            "stats": [
                {"group": {"displayName": "pitching"}, "splits": [{"date": "2026-06-01"}]},
                {"group": {"displayName": "hitting"}, "splits": [{"date": "2026-06-02"}]},
            ]
        }
        client = client_with_response(FakeResponse(200, payload))
        entries = client.get_person_stats(660271, stats="gameLog", group="pitching")
        # Groups stay distinguishable — nothing is merged away.
        assert [e["group"]["displayName"] for e in entries] == ["pitching", "hitting"]

    def test_get_person_stats_sends_optional_params_only_when_given(self) -> None:
        client = client_with_response(FakeResponse(200, {"stats": []}))
        client.get_person_stats(1, stats="season", group="hitting")
        assert sent_params(client) == {"stats": "season", "group": "hitting"}

        client = client_with_response(FakeResponse(200, {"stats": []}))
        client.get_person_stats(1, stats="gameLog", group="pitching", season=2026, sport_id=11)
        assert sent_params(client) == {
            "stats": "gameLog",
            "group": "pitching",
            "season": 2026,
            "sportId": 11,
        }

    def test_get_person_stats_empty_body(self) -> None:
        client = client_with_response(FakeResponse(200, {}))
        assert client.get_person_stats(1, stats="gameLog", group="pitching") == []

    def test_get_schedule_returns_raw_payload_with_dates(self) -> None:
        payload = {"dates": [{"date": "2026-06-01", "games": [{"gamePk": 1}]}]}
        client = client_with_response(FakeResponse(200, payload))
        # Per-date grouping is preserved, unlike get_scheduled_games.
        assert client.get_schedule(start_date="2026-06-01") == payload

    def test_get_schedule_defaults_to_mlb_but_accepts_a_level(self) -> None:
        client = client_with_response(FakeResponse(200, {}))
        client.get_schedule()
        assert sent_params(client) == {"sportId": 1}

        client = client_with_response(FakeResponse(200, {}))
        client.get_schedule(start_date="2026-06-01", end_date="2026-06-02", sport_id=11)
        assert sent_params(client) == {
            "sportId": 11,
            "startDate": "2026-06-01",
            "endDate": "2026-06-02",
        }

    def test_get_boxscore_returns_raw_payload(self) -> None:
        payload = {"teams": {"away": {"batters": [1]}, "home": {}}}
        client = client_with_response(FakeResponse(200, payload))
        assert client.get_boxscore(745123) == payload

    def test_guids_non_list_raises(self) -> None:
        client = client_with_response(FakeResponse(200, {"unexpected": True}))
        with pytest.raises(StatsApiError):
            client.get_game_guids(1, access_token="tok")

    def test_guids_hydrate_is_overridable(self) -> None:
        client = client_with_response(FakeResponse(200, []))
        client.get_game_guids(1, access_token="tok")
        assert sent_params(client) == {"hydrate": "analytics(metaData)"}

        client = client_with_response(FakeResponse(200, []))
        client.get_game_guids(1, access_token="tok", hydrate="none")
        assert sent_params(client) == {"hydrate": "none"}


class TestDerivedViews:
    def test_game_log_flattens_splits(self) -> None:
        payload = {
            "stats": [
                {"splits": [{"date": "2026-06-01"}, {"date": "2026-06-05"}]},
                {"splits": [{"date": "2026-06-09"}]},
                {},  # entry without splits tolerated
            ]
        }
        client = client_with_response(FakeResponse(200, payload))
        splits = client.get_person_game_log(660271, season=2026, group="pitching")
        assert [s["date"] for s in splits] == ["2026-06-01", "2026-06-05", "2026-06-09"]

    def test_game_log_empty_body(self) -> None:
        client = client_with_response(FakeResponse(200, {}))
        assert client.get_person_game_log(660271, season=2026, group="pitching") == []

    def test_scheduled_games_flattens_dates(self) -> None:
        payload = {
            "dates": [
                {"games": [{"gamePk": 1}, {"gamePk": 2}]},
                {"games": [{"gamePk": 3}]},
            ]
        }
        client = client_with_response(FakeResponse(200, payload))
        games = client.get_scheduled_games(start_date="2026-06-01", end_date="2026-06-02")
        assert [g["gamePk"] for g in games] == [1, 2, 3]

    def test_scheduled_games_empty_body(self) -> None:
        client = client_with_response(FakeResponse(200, {}))
        assert client.get_scheduled_games() == []

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

    def test_get_game_pitchers_empty_body(self) -> None:
        client = client_with_response(FakeResponse(200, {}))
        assert client.get_game_pitchers(745123) == []


class TestLfrSkeletalEndpoints:
    """The Hawk-Eye LFR pull endpoints (used by scripts/download_hawkeye_lfr_from_statsapi.py)."""

    def test_get_play_parsed_returns_raw_bytes(self) -> None:
        # Parsed lands in bronze verbatim, so the client must return the undecoded body bytes.
        client = client_with_response(FakeResponse(200, content=b'{"Play":{"playId":"g"}}'))
        assert client.get_play_parsed(823850, "g", access_token="tok") == b'{"Play":{"playId":"g"}}'
        assert client._session.get.call_args.args[0].endswith("/game/823850/g/analytics/parsed")

    def test_get_skeletal_file_names_returns_list(self) -> None:
        urls = ["http://statsapi.mlb.com/api/v1/game/1/g/analytics/skeletalData/chunked?fileName=file_1"]
        client = client_with_response(FakeResponse(200, {"fileNames": urls}))
        assert client.get_skeletal_file_names(1, "g", access_token="tok") == urls

    def test_get_skeletal_file_names_empty_when_no_pose(self) -> None:
        # ~40% of plays have no skeletal pose — the files endpoint 404s, treated as an empty list.
        client = client_with_response(FakeResponse(404))
        assert client.get_skeletal_file_names(1, "g", access_token="tok") == []

    def test_get_skeletal_chunk_upgrades_http_to_https_and_returns_bytes(self) -> None:
        # Regression: the vendor emits http:// chunk URLs; the client must accept them (host match)
        # and fetch over https so the bearer token is never sent in plaintext.
        client = client_with_response(FakeResponse(200, content=b"chunkbytes"))
        http_url = "http://statsapi.mlb.com/api/v1/game/1/g/analytics/skeletalData/chunked?fileName=file_1"
        assert client.get_skeletal_chunk(http_url, access_token="tok") == b"chunkbytes"
        fetched = client._session.get.call_args.args[0]
        assert fetched.startswith("https://statsapi.mlb.com/")
        assert "fileName=file_1" in fetched

    def test_get_skeletal_chunk_rejects_foreign_host(self) -> None:
        client = client_with_response(FakeResponse(200, content=b"x"))
        with pytest.raises(StatsApiError):
            client.get_skeletal_chunk("http://evil.example.com/steal?fileName=file_1", access_token="tok")
        client._session.get.assert_not_called()
