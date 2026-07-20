"""Synchronous client for the MLB Stats API (``statsapi.mlb.com``).

A small, dependency-light wrapper returning raw JSON dicts. Payload shapes are
not publicly documented, so callers harden access with ``.get()``.

The surface is deliberately split in two:

- **Endpoint methods** (:meth:`~StatsApiClient.get_person`,
  :meth:`~StatsApiClient.get_person_stats`, :meth:`~StatsApiClient.get_schedule`,
  :meth:`~StatsApiClient.get_boxscore`, :meth:`~StatsApiClient.get_game_guids`)
  return what the endpoint returns, so nothing in the payload is lost.
- **Derived helpers** (:meth:`~StatsApiClient.get_person_game_log`,
  :meth:`~StatsApiClient.get_scheduled_games`,
  :meth:`~StatsApiClient.get_game_pitchers`) are conveniences layered on those,
  reshaping a payload into the view callers usually want. They are shortcuts,
  never the only way to reach the data.

Anything not wrapped yet is reachable through :meth:`~StatsApiClient.get`.

Most endpoints are public; the guids endpoint needs an MLB-org Okta bearer
token (see :mod:`mlb_statsapi.auth`). Errors surface as :class:`StatsApiError`
/ :class:`StatsApiAuthError`.
"""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter, Retry

MLB_STATS_BASE_URL = "https://statsapi.mlb.com/api/v1"

# sportId 1 is MLB; the minor-league levels are 11 (AAA), 12 (AA), 13 (High-A),
# 14 (A) and 16 (Rookie). Endpoints that take a sportId default to MLB but let
# callers ask for any level.
MLB_SPORT_ID = 1

_TIMEOUT_S = 30.0
# Transport errors and transient upstream 5xx are retried at the adapter level,
# mirroring request_datatypes.BaseRequest.
_RETRY = Retry(total=3, backoff_factor=2, status_forcelist=[502, 503, 504])


class StatsApiError(Exception):
    """A provider or network failure talking to the MLB Stats API."""


class StatsApiAuthError(StatsApiError):
    """The MLB Stats API rejected the request's access token (HTTP 401)."""


class StatsApiClient:
    """Sync client owning one ``requests.Session``."""

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

    # -- core -----------------------------------------------------------------

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        access_token: str | None = None,
        not_found_ok: bool = False,
    ) -> Any:
        """GET any Stats API path and return the decoded JSON.

        The escape hatch for endpoints this client does not wrap yet — ``path``
        is appended to the base URL, e.g. ``client.get("/teams", params={"sportId": 1})``.

        :param not_found_ok: Return ``None`` on HTTP 404 instead of raising.
        :raises StatsApiAuthError: HTTP 401 (missing/expired token).
        :raises StatsApiError: Any other non-2xx, a transport failure, or a
            non-JSON body.
        """
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

    # -- endpoints ------------------------------------------------------------

    def get_person(self, person_id: int) -> dict[str, Any] | None:
        """Fetch one person by MLBAM id (public, no auth).

        Unwraps the single-element ``people`` envelope — for a by-id lookup it
        carries nothing else. Returns the raw person dict, containing at least
        ``id`` and ``fullName`` and often ``currentTeam.name`` and
        ``primaryPosition.name``, or ``None`` when no person has that id.

        The ``/people/search`` name index omits players without MLB service time
        (many active minor-leaguers), so lookups go through this id endpoint.
        """
        data = self.get(f"/people/{person_id}", not_found_ok=True)
        people = (data or {}).get("people", [])
        if not isinstance(people, list) or not people:
            return None
        first = people[0]
        return first if isinstance(first, dict) else None

    def get_person_stats(
        self,
        person_id: int,
        *,
        stats: str,
        group: str,
        season: int | None = None,
        sport_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch a person's stats (public, no auth).

        Returns the raw ``stats[]`` entries, each with its own ``type``,
        ``group`` and ``splits`` — so callers can tell which group a split came
        from. Use :meth:`get_person_game_log` for the flattened game-log view.

        :param stats: Stats type, e.g. ``"gameLog"``, ``"season"``, ``"career"``.
        :param group: Stat group, e.g. ``"pitching"``, ``"hitting"``, ``"fielding"``.
        :param sport_id: Level to query. This endpoint returns only one level
            per call and defaults to MLB; it rejects comma lists and ignores a
            plural ``sportIds``, so callers wanting several levels must issue
            one call each.
        """
        params: dict[str, Any] = {"stats": stats, "group": group}
        if season is not None:
            params["season"] = season
        if sport_id is not None:
            params["sportId"] = sport_id
        data = self.get(f"/people/{person_id}/stats", params=params)
        entries = (data or {}).get("stats", [])
        return entries if isinstance(entries, list) else []

    def get_schedule(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        sport_id: int = MLB_SPORT_ID,
    ) -> dict[str, Any]:
        """Fetch the schedule payload for a date range (public, no auth).

        Returns the raw payload, whose ``dates[]`` entries each group that day's
        ``games[]`` — keeping the per-date context. Use
        :meth:`get_scheduled_games` for a flat list of games.

        :param sport_id: Level to query; defaults to MLB. Pass e.g. ``11`` for
            Triple-A.
        """
        params: dict[str, Any] = {"sportId": sport_id}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        data = self.get("/schedule", params=params)
        return data if isinstance(data, dict) else {}

    def get_boxscore(self, game_pk: int) -> dict[str, Any]:
        """Fetch one game's boxscore (public, no auth).

        Returns the raw payload — ``teams.{home,away}`` with each side's
        ``team``, ``players``, ``batters``, ``pitchers`` and batting/pitching
        order. Use :meth:`get_game_pitchers` for just the pitchers who appeared.
        """
        data = self.get(f"/game/{game_pk}/boxscore")
        return data if isinstance(data, dict) else {}

    def get_game_guids(
        self,
        game_pk: int,
        *,
        access_token: str,
        hydrate: str = "analytics(metaData)",
    ) -> list[dict[str, Any]]:
        """Fetch one game's play guids (auth required).

        :param hydrate: Hydration expression; the default pulls the analytics
            metadata (pitcher, play details) that :mod:`mlb_statsapi.bucketing`
            reads.
        """
        data = self.get(
            f"/game/{game_pk}/guids",
            params={"hydrate": hydrate},
            access_token=access_token,
        )
        if not isinstance(data, list):
            raise StatsApiError(f"Unexpected guids response for game {game_pk}")
        return data

    # -- derived views --------------------------------------------------------

    def get_person_game_log(
        self,
        person_id: int,
        *,
        season: int,
        group: str,
        sport_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """One person's game log for a season, flattened (derived).

        Convenience over :meth:`get_person_stats`: merges every ``stats[]``
        entry's ``splits`` into one list. Each split contains at least ``date``,
        ``game.gamePk``, ``opponent.name``, ``isHome``, ``team.name`` and
        ``sport.abbreviation``.
        """
        entries = self.get_person_stats(
            person_id, stats="gameLog", group=group, season=season, sport_id=sport_id
        )
        splits: list[dict[str, Any]] = []
        for entry in entries:
            splits.extend(entry.get("splits", []))
        return splits

    def get_scheduled_games(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        sport_id: int = MLB_SPORT_ID,
    ) -> list[dict[str, Any]]:
        """Scheduled games in a date range, flattened across dates (derived).

        Convenience over :meth:`get_schedule`. Each game contains at least
        ``gamePk``, ``officialDate``/``gameDate`` and
        ``teams.{home,away}.team.name``.
        """
        payload = self.get_schedule(start_date=start_date, end_date=end_date, sport_id=sport_id)
        games: list[dict[str, Any]] = []
        for date_entry in payload.get("dates", []):
            games.extend(date_entry.get("games", []))
        return games

    def get_game_pitchers(self, game_pk: int) -> list[dict[str, Any]]:
        """Pitchers who appeared in one game (derived).

        Convenience over :meth:`get_boxscore`, reshaped to
        ``{"pitcher_id": int, "name": str, "team": str}`` per pitcher.
        """
        data = self.get_boxscore(game_pk)
        pitchers: list[dict[str, Any]] = []
        for side in ("away", "home"):
            team_entry = data.get("teams", {}).get(side, {})
            team_name = team_entry.get("team", {}).get("name") or side
            players = team_entry.get("players", {})
            for pid in team_entry.get("pitchers", []):
                player = players.get(f"ID{pid}", {})
                name = player.get("person", {}).get("fullName") or str(pid)
                pitchers.append({"pitcher_id": pid, "name": name, "team": team_name})
        return pitchers
