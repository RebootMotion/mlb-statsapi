"""Synchronous client for the MLB Stats API (``statsapi.mlb.com``).

A small, dependency-light wrapper returning raw JSON dicts. The guids endpoint
requires an MLB-org Okta bearer token; schedule, boxscore, person, and gameLog
are public. Payload shapes are not publicly documented, so callers harden
access with ``.get()``.

Errors are surfaced as :class:`StatsApiError` / :class:`StatsApiAuthError`.
"""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter, Retry

MLB_STATS_BASE_URL = "https://statsapi.mlb.com/api/v1"

_TIMEOUT_S = 30.0
# Transport errors and transient upstream 5xx are retried at the adapter level,
# mirroring request_datatypes.BaseRequest.
_RETRY = Retry(total=3, backoff_factor=2, status_forcelist=[502, 503, 504])


class StatsApiError(Exception):
    """A provider or network failure talking to the MLB Stats API."""


class StatsApiAuthError(StatsApiError):
    """The MLB Stats API rejected the request's access token (HTTP 401)."""


class StatsApiClient:
    """Sync client owning one lazily-created ``requests.Session``."""

    def __init__(self, base_url: str = MLB_STATS_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")
        # A Session opens no connections until first use, so eager creation is
        # cheap even for a client that is constructed but never queried.
        self._session = requests.Session()
        adapter = HTTPAdapter(max_retries=_RETRY)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def close(self) -> None:
        self._session.close()

    def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        access_token: str | None = None,
        not_found_ok: bool = False,
    ) -> Any:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {access_token}"} if access_token else None
        try:
            response = self._session.get(url, params=params, headers=headers, timeout=_TIMEOUT_S)
        except requests.RequestException as err:
            raise StatsApiError(f"MLB Stats API request failed for {path}: {err}") from err
        if response.status_code == 401:
            raise StatsApiAuthError("MLB Stats API rejected the access token — sign in again")
        if response.status_code == 404 and not_found_ok:
            # Caller treats a missing resource as an empty result, not an error.
            return None
        if response.status_code >= 400:
            raise StatsApiError(f"MLB Stats API returned {response.status_code} for {path}")
        try:
            return response.json()
        except ValueError as err:
            # A 2xx with a non-JSON body (e.g. an HTML error/interstitial) still
            # counts as a provider failure, not a raw decode error to the caller.
            raise StatsApiError(f"MLB Stats API returned a non-JSON body for {path}") from err

    def get_person(self, person_id: int) -> dict[str, Any] | None:
        """Fetch one person by MLBAM id (public, no auth).

        The ``/people/search`` name index omits players without MLB service time
        (many active minor-leaguers), so lookups go through this id endpoint
        instead. Returns the raw person dict — containing at least ``id`` and
        ``fullName``, often ``currentTeam.name`` and ``primaryPosition.name`` —
        or ``None`` when no person has that id.
        """
        data = self._get(f"/people/{person_id}", not_found_ok=True)
        people = (data or {}).get("people", [])
        if not isinstance(people, list) or not people:
            return None
        first = people[0]
        return first if isinstance(first, dict) else None

    def get_person_game_log(
        self,
        person_id: int,
        *,
        season: int,
        group: str = "pitching",
        sport_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch one person's game log for a season (public, no auth).

        The gameLog endpoint returns only one level per call and defaults to
        MLB (``sportId`` 1); pass ``sport_id`` to fetch a minor-league level
        (e.g. 11 = Triple-A). The API rejects comma lists and ignores plural
        ``sportIds``, so callers wanting several levels must issue one call each.

        Returns flattened ``stats[].splits[]`` dicts, each containing at least
        ``date``, ``game.gamePk``, ``opponent.name``, ``isHome``, ``team.name``,
        and ``sport.abbreviation``.
        """
        params: dict[str, Any] = {"stats": "gameLog", "group": group, "season": season}
        if sport_id is not None:
            params["sportId"] = sport_id
        data = self._get(f"/people/{person_id}/stats", params=params)
        splits: list[dict[str, Any]] = []
        for entry in (data or {}).get("stats", []):
            splits.extend(entry.get("splits", []))
        return splits

    def get_game_guids(self, game_pk: int, *, access_token: str) -> list[dict[str, Any]]:
        """Fetch play guids with analytics metadata for one game (auth required)."""
        data = self._get(
            f"/game/{game_pk}/guids",
            params={"hydrate": "analytics(metaData)"},
            access_token=access_token,
        )
        if not isinstance(data, list):
            raise StatsApiError(f"Unexpected guids response for game {game_pk}")
        return data

    def get_schedule(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch scheduled MLB games in a date range (public, no auth).

        Returns flattened game dicts, each containing at least ``gamePk``,
        ``officialDate``/``gameDate``, and ``teams.{home,away}.team.name``.
        """
        params: dict[str, Any] = {"sportId": 1}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        data = self._get("/schedule", params=params)
        games: list[dict[str, Any]] = []
        for date_entry in (data or {}).get("dates", []):
            games.extend(date_entry.get("games", []))
        return games

    def get_game_pitchers(self, game_pk: int) -> list[dict[str, Any]]:
        """List pitchers who appeared in one game via its boxscore (public).

        Returns ``{"pitcher_id": int, "name": str, "team": str}`` dicts.
        """
        data = self._get(f"/game/{game_pk}/boxscore")
        pitchers: list[dict[str, Any]] = []
        for side in ("away", "home"):
            team_entry = (data or {}).get("teams", {}).get(side, {})
            team_name = team_entry.get("team", {}).get("name") or side
            players = team_entry.get("players", {})
            for pid in team_entry.get("pitchers", []):
                player = players.get(f"ID{pid}", {})
                name = player.get("person", {}).get("fullName") or str(pid)
                pitchers.append({"pitcher_id": pid, "name": name, "team": team_name})
        return pitchers
