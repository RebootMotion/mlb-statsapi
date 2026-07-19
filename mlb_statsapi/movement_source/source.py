"""``MovementSourceProtocol`` implementation backed by the MLB Stats API.

This is the optional ``[biomech]`` movement-source plugin. It is loaded by a
running biomech_studio process via ``BIOMECH_MOVEMENT_SOURCES`` and therefore
imports the movement-source contract (DTOs + exceptions) directly from the
host. The neutral ``mlb_statsapi.statsapi`` client is synchronous, so every
call is dispatched to a worker thread and its library-local errors are
translated into the host's movement-source exceptions.
"""

from __future__ import annotations

import asyncio
import functools
import importlib.util
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

from biomech_studio.processing.movement_sources.protocols import (
    LoginState,
    MovementSourceInfo,
    MovementSplitResult,
    SourceAuthStatus,
    SourceComparisonType,
    SourceEvent,
    SourceEventPlayer,
    SourcePlayer,
)
from biomech_studio.services.exceptions import (
    InteractiveLoginUnavailableError,
    LoginInProgressError,
    MovementSourceError,
    MovementSourceNotAuthenticatedError,
)

from mlb_statsapi.movement_source import auth, bucketing
from mlb_statsapi.statsapi import (
    MLB_STATS_BASE_URL,
    StatsApiAuthError,
    StatsApiClient,
    StatsApiError,
)

logger = logging.getLogger(__name__)

_INFO = MovementSourceInfo(key="mlb-stats", label="MLB Stats API")

# Affiliated professional levels a pitcher can appear in. The gameLog endpoint
# returns one level per call (MLB by default), so player event search fans out
# across all of these: MLB, Triple-A, Double-A, High-A, Single-A, Rookie.
_PRO_SPORT_IDS: tuple[int, ...] = (1, 11, 12, 13, 14, 16)

_T = TypeVar("_T")


@functools.cache
def _playwright_available() -> bool:
    # Availability cannot change within a process lifetime, and auth_status
    # sits on the frontend's login polling loop.
    return importlib.util.find_spec("playwright") is not None


class MlbStatsMovementSource:
    """Movement source over MLB play GUIDs.

    The access token lives in memory on this instance only: set by browser
    login capture or paste, cleared when the API rejects it, gone on app
    restart. It is never written to disk, logged, or returned to callers.
    """

    def __init__(self, *, config: dict[str, Any]) -> None:
        self._client = StatsApiClient(config.get("base_url") or MLB_STATS_BASE_URL)
        self._token: str | None = None
        self._login_task: asyncio.Task[None] | None = None
        self._login_error: str | None = None
        # Browser-login timeout (seconds). Lower it (e.g. via the source's config
        # entry) to surface a failed capture sooner instead of waiting the full
        # default before the "no token captured" error appears.
        self._login_timeout_s = int(config.get("login_timeout_s") or auth.LOGIN_TIMEOUT_SECONDS)

    @property
    def info(self) -> MovementSourceInfo:
        return _INFO

    async def _call(self, fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
        """Run a sync client call off the event loop, translating its errors.

        The neutral client raises library-local ``StatsApi*`` errors; the router
        only understands the host's movement-source exceptions, so map them here.
        """
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except StatsApiAuthError as err:
            raise MovementSourceNotAuthenticatedError(str(err)) from err
        except StatsApiError as err:
            raise MovementSourceError(str(err)) from err

    # -- auth -----------------------------------------------------------------

    async def auth_status(self) -> SourceAuthStatus:
        exp = auth.decode_jwt_exp(self._token) if self._token else None
        if exp is not None and exp <= time.time():
            self._token = None
            exp = None
        signed_in = self._token is not None

        login_state: LoginState
        if self._login_task is not None and not self._login_task.done():
            login_state = "pending"
        elif signed_in:
            login_state = "signed_in"
        elif self._login_error is not None:
            login_state = "error"
        else:
            login_state = "idle"

        return SourceAuthStatus(
            signed_in=signed_in,
            login_state=login_state,
            login_error=self._login_error,
            token_expires_at=exp,
            interactive_login_available=_playwright_available(),
        )

    async def start_interactive_login(self) -> None:
        if self._login_task is not None and not self._login_task.done():
            raise LoginInProgressError()
        if not _playwright_available():
            # Raise synchronously with the install hint instead of from the task.
            raise InteractiveLoginUnavailableError(auth.PLAYWRIGHT_INSTALL_HINT)
        self._login_error = None
        logger.info("Starting MLB Stats interactive login (timeout=%ss)", self._login_timeout_s)
        self._login_task = asyncio.create_task(self._run_login())

    async def _run_login(self) -> None:
        try:
            token = await asyncio.to_thread(
                auth.login_with_browser, timeout_s=self._login_timeout_s
            )
        except Exception as err:
            self._login_error = str(err)
            logger.warning("MLB Stats browser login failed: %s", err)
        else:
            self._token = token
            self._login_error = None
            logger.info("MLB Stats browser login succeeded")

    async def set_token(self, token: str) -> None:
        self._token = token.strip()
        self._login_error = None

    def _require_token(self) -> str:
        if not self._token:
            raise MovementSourceNotAuthenticatedError(
                "Not signed in to the MLB Stats API — start an interactive login "
                "or paste an access token"
            )
        return self._token

    # -- data -----------------------------------------------------------------

    async def lookup_player(self, *, player_id: str) -> SourcePlayer | None:
        # MLBAM ids are positive integers; anything else can't match a person,
        # so skip the round-trip (and the API's 400 on a non-numeric path).
        cleaned = player_id.strip()
        if not cleaned.isdigit():
            return None
        person = await self._call(self._client.get_person, int(cleaned))
        if person is None:
            return None
        resolved_id = person.get("id")
        if resolved_id is None:
            return None
        return SourcePlayer(
            player_id=str(resolved_id),
            name=person.get("fullName") or str(resolved_id),
            group=(person.get("currentTeam") or {}).get("name"),
            provider_extra={"position": (person.get("primaryPosition") or {}).get("name")},
        )

    async def search_events(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        player_id: str | None = None,
    ) -> list[SourceEvent]:
        if player_id is not None:
            return await self._search_player_events(
                player_id=player_id, start_date=start_date, end_date=end_date
            )
        games = await self._call(
            self._client.get_schedule, start_date=start_date, end_date=end_date
        )
        events: list[SourceEvent] = []
        for game in games:
            game_pk = game.get("gamePk")
            if game_pk is None:
                continue
            away = game.get("teams", {}).get("away", {}).get("team", {}).get("name") or "Away"
            home = game.get("teams", {}).get("home", {}).get("team", {}).get("name") or "Home"
            date = game.get("officialDate") or (game.get("gameDate") or "")[:10] or None
            events.append(
                SourceEvent(
                    event_id=str(game_pk),
                    label=f"{away} @ {home}" + (f" — {date}" if date else ""),
                    date=date,
                    provider_extra={"status": game.get("status", {}).get("detailedState")},
                )
            )
        return events

    async def _search_player_events(
        self,
        *,
        player_id: str,
        start_date: str | None,
        end_date: str | None,
    ) -> list[SourceEvent]:
        """Games one player appeared in, via their per-season game logs (public).

        The gameLog endpoint returns one level per call, so we fan out over
        the affiliated pro ladder (MLB + minors) for every season in range and
        merge — otherwise a player's minor-league starts never appear.
        """
        person_id = _to_person_id(player_id)
        seasons = _seasons_for_range(start_date, end_date, time.localtime().tm_year)
        logs = await asyncio.gather(
            *[
                self._call(
                    self._client.get_person_game_log, person_id, season=season, sport_id=sport_id
                )
                for season in seasons
                for sport_id in _PRO_SPORT_IDS
            ]
        )
        events: list[SourceEvent] = []
        seen_game_pks: set[int] = set()
        for split in (s for log in logs for s in log):
            game_pk = split.get("game", {}).get("gamePk")
            if game_pk is None or game_pk in seen_game_pks:
                continue
            date = split.get("date")
            if start_date and (date is None or date < start_date):
                continue
            if end_date and (date is None or date > end_date):
                continue
            seen_game_pks.add(game_pk)
            opponent = split.get("opponent", {}).get("name") or "Opponent"
            prefix = "vs" if split.get("isHome", True) else "@"
            level = split.get("sport", {}).get("abbreviation")
            level_suffix = f" ({level})" if level else ""
            events.append(
                SourceEvent(
                    event_id=str(game_pk),
                    label=f"{prefix} {opponent}{level_suffix}" + (f" — {date}" if date else ""),
                    date=date,
                    provider_extra={
                        "is_home": split.get("isHome"),
                        "team": split.get("team", {}).get("name"),
                        "level": level,
                    },
                )
            )
        events.sort(key=lambda e: e.date or "")
        return events

    async def list_event_players(self, event_id: str) -> list[SourceEventPlayer]:
        pitchers = await self._call(self._client.get_game_pitchers, _to_game_pk(event_id))
        return [
            SourceEventPlayer(
                player_id=str(p["pitcher_id"]),
                name=p["name"],
                group=p["team"],
            )
            for p in pitchers
        ]

    async def list_comparison_types(self) -> list[SourceComparisonType]:
        return [
            SourceComparisonType(id=ct.id, label=ct.label)
            for ct in bucketing.COMPARISON_TYPES.values()
        ]

    async def split_movements(
        self,
        *,
        event_ids: list[str],
        player_id: str,
        comparison_type: str,
    ) -> MovementSplitResult:
        token = self._require_token()
        pitcher_id = _to_person_id(player_id)

        async def _fetch(event_id: str) -> tuple[str, list[dict[str, Any]]]:
            guids = await self._call(
                self._client.get_game_guids, _to_game_pk(event_id), access_token=token
            )
            return event_id, guids

        try:
            games = await asyncio.gather(*[_fetch(eid) for eid in event_ids])
        except MovementSourceNotAuthenticatedError:
            self._token = None  # stale token — force a clean re-login
            raise

        result = bucketing.split_guids(
            list(games), pitcher_id=pitcher_id, comparison_type=comparison_type
        )
        return MovementSplitResult(
            buckets=result.buckets,
            dominant_hand=result.dominant_hand,
            movement_type="baseball-pitching",
            provider_extra=result.provider_extra,
        )

    async def close(self) -> None:
        if self._login_task is not None and not self._login_task.done():
            self._login_task.cancel()
        self._client.close()


def _to_game_pk(event_id: str) -> int:
    try:
        return int(event_id)
    except ValueError:
        raise MovementSourceError(f"Invalid MLB game id: {event_id!r}") from None


def _to_person_id(player_id: str) -> int:
    try:
        return int(player_id)
    except ValueError:
        raise MovementSourceError(f"Invalid MLB player id: {player_id!r}") from None


def _seasons_for_range(
    start_date: str | None, end_date: str | None, current_year: int
) -> list[int]:
    """Season years spanned by an ISO date range; current season when unbounded."""
    try:
        start_year = int(start_date[:4]) if start_date else None
        end_year = int(end_date[:4]) if end_date else None
    except ValueError:
        raise MovementSourceError(
            f"Invalid date range: {start_date!r} to {end_date!r} (expected YYYY-MM-DD)"
        ) from None
    if start_year is None:
        return [end_year if end_year is not None else current_year]
    if end_year is None:
        end_year = max(start_year, current_year)
    return list(range(start_year, end_year + 1))
