"""Pure pitch-bucketing logic over MLB Stats API guid payloads.

Operates on already-fetched guid dicts (no I/O) so it is fully unit-testable,
with ``.get()``-hardened access throughout (live payload shapes are not
publicly documented).

Each guid dict is one entry of ``GET /game/{game_pk}/guids?hydrate=analytics(metaData)``:
``{"guid": str, "metaData": {"pitcher": {"id": int}, "stat": {"play": {...}}}}``.

Part of the optional ``[biomech]`` movement-source plugin: it raises the
generic movement-source exceptions defined by the host so the biomech_studio
router can map them without provider knowledge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from biomech_studio.services.exceptions import (
    DominanceNotDeterminedError,
    NoMatchingMovementsError,
    UnknownComparisonTypeError,
)

RUNNER_ON_BASE_FIELDS = ("runnerOn1b", "runnerOn2b", "runnerOn3b")

# MLB pitchHand code → neutral dominance value used across the app
PITCH_HAND_TO_DOMINANT_HAND = {"R": "right", "L": "left"}

BucketFn = Callable[[dict[str, Any]], str | None]


def _windup_stretch_bucket(play: dict[str, Any]) -> str:
    has_runner_on = any(play.get("count", {}).get(base) for base in RUNNER_ON_BASE_FIELDS)
    return "stretch" if has_runner_on else "windup"


def _pitch_type_bucket(play: dict[str, Any]) -> str | None:
    value = play.get("details", {}).get("type", {}).get("description")
    return value if isinstance(value, str) else None


def _batter_hand_bucket(play: dict[str, Any]) -> str | None:
    value = play.get("details", {}).get("batSide", {}).get("code")
    return value if isinstance(value, str) else None


def _two_strike_count_bucket(play: dict[str, Any]) -> str:
    return "two_strikes" if play.get("count", {}).get("strikes") == 2 else "other_counts"


def _inning_range_bucket(play: dict[str, Any]) -> str | None:
    inning = play.get("count", {}).get("inning")
    if inning is None:
        return None
    if inning <= 3:
        return "innings_1_to_3"
    if inning <= 6:
        return "innings_4_to_6"
    return "innings_7_plus"


@dataclass(frozen=True, slots=True)
class ComparisonType:
    id: str
    label: str
    bucket_fn: BucketFn


COMPARISON_TYPES: dict[str, ComparisonType] = {
    ct.id: ct
    for ct in (
        ComparisonType("windup_stretch", "Windup vs stretch", _windup_stretch_bucket),
        ComparisonType("pitch_type", "Pitch type", _pitch_type_bucket),
        ComparisonType("batter_hand", "Batter hand", _batter_hand_bucket),
        ComparisonType("two_strike_count", "Two-strike count", _two_strike_count_bucket),
        ComparisonType("inning_range", "Inning range", _inning_range_bucket),
    )
}


@dataclass(frozen=True, slots=True)
class GuidSplitResult:
    """Buckets of play GUIDs for one pitcher across the supplied games."""

    buckets: dict[str, list[str]]
    dominant_hand: str  # neutral "left" | "right"
    provider_extra: dict[str, Any] = field(default_factory=dict)


def split_guids(
    games: list[tuple[str, list[dict[str, Any]]]],
    *,
    pitcher_id: int,
    comparison_type: str,
) -> GuidSplitResult:
    """Bucket one pitcher's play GUIDs across games by comparison type.

    :param games: ``(event_id, guid_dicts)`` per game, as fetched from the
        Stats API guids endpoint.
    :param pitcher_id: MLB person id; plays by other pitchers are skipped.
    :param comparison_type: Key into :data:`COMPARISON_TYPES`.
    :raises UnknownComparisonTypeError: Unsupported ``comparison_type``.
    :raises NoMatchingMovementsError: No plays matched the pitcher.
    :raises DominanceNotDeterminedError: Pitch hand missing, unsupported, or
        conflicting across the selected games.
    """
    ct = COMPARISON_TYPES.get(comparison_type)
    if ct is None:
        raise UnknownComparisonTypeError(comparison_type)

    buckets: dict[str, list[str]] = {}
    pitch_hands: set[str] = set()
    matched = 0

    for _event_id, guid_dicts in games:
        for guid_dict in guid_dicts:
            guid = guid_dict.get("guid")
            meta_data = guid_dict.get("metaData") or {}
            play = meta_data.get("stat", {}).get("play") or {}
            if not guid or not play.get("count"):
                continue

            pid = meta_data.get("pitcher", {}).get("id")
            if pid is None or int(pid) != int(pitcher_id):
                continue
            matched += 1

            hand = play.get("details", {}).get("pitchHand", {}).get("code")
            if hand:
                pitch_hands.add(hand)

            bucket = ct.bucket_fn(play)
            if bucket is None:
                continue
            buckets.setdefault(bucket, []).append(guid)

    if matched == 0:
        raise NoMatchingMovementsError(
            f"No pitches found for pitcher {pitcher_id} in the selected games — "
            "verify the pitcher appeared in those games"
        )
    if len(pitch_hands) > 1:
        raise DominanceNotDeterminedError(
            f"Selected games mix pitch hands {sorted(pitch_hands)} for pitcher "
            f"{pitcher_id} — narrow the selection to games with a single hand"
        )
    hand = next(iter(pitch_hands), None)
    dominant_hand = PITCH_HAND_TO_DOMINANT_HAND.get(hand or "")
    if dominant_hand is None:
        raise DominanceNotDeterminedError(
            f"Unsupported or missing pitch hand {hand!r} for pitcher {pitcher_id}"
        )

    return GuidSplitResult(
        buckets=buckets,
        dominant_hand=dominant_hand,
        provider_extra={"pitch_hand": hand},
    )
