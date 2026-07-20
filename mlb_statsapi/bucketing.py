"""Group a pitcher's play GUIDs into named buckets.

Pure, I/O-free logic over already-fetched guid dicts (so it is fully
unit-testable), with ``.get()``-hardened access throughout — live payload
shapes are not publicly documented.

Each guid dict is one entry of
``StatsApiClient.get_game_guids`` / ``GET /game/{game_pk}/guids?hydrate=analytics(metaData)``:
``{"guid": str, "metaData": {"pitcher": {"id": int}, "stat": {"play": {...}}}}``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class UnknownComparisonTypeError(ValueError):
    """The requested comparison_type is not a key in :data:`COMPARISON_TYPES`."""


class NoMatchingPitchesError(Exception):
    """No plays in the supplied games matched the requested pitcher."""


class PitchHandNotDeterminedError(Exception):
    """Pitch hand is missing, unsupported, or conflicting across the games."""


RUNNER_ON_BASE_FIELDS = ("runnerOn1b", "runnerOn2b", "runnerOn3b")

# MLB pitchHand code → neutral handedness value
PITCH_HAND_TO_DOMINANT_HAND = {"R": "right", "L": "left"}

BucketFn = Callable[[dict[str, Any]], str | None]


def _windup_stretch_bucket(play: dict[str, Any]) -> str:
    has_runner_on = any(play.get("count", {}).get(base) for base in RUNNER_ON_BASE_FIELDS)
    return "stretch" if has_runner_on else "windup"


def _pitch_type_bucket(play: dict[str, Any]) -> str | None:
    """MLB's short pitch code ("FF", "SL", "CH").

    The code is the standard identifier and keeps labels compact; the long
    ``description`` ("Four-Seam Fastball") is the fallback for a payload that
    omits it.
    """
    pitch_type = play.get("details", {}).get("type", {})
    for key in ("code", "description"):
        value = pitch_type.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _batter_hand_bucket(play: dict[str, Any]) -> str | None:
    value = play.get("details", {}).get("batSide", {}).get("code")
    return value if isinstance(value, str) else None


def _count_bucket(play: dict[str, Any]) -> str | None:
    count = play.get("count", {})
    balls, strikes = count.get("balls"), count.get("strikes")
    if balls is None or strikes is None:
        return None
    return f"{balls}-{strikes}"


def _inning_bucket(play: dict[str, Any]) -> str | None:
    inning = play.get("count", {}).get("inning")
    return None if inning is None else str(inning)


def _count_sort_key(label: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in label.split("-"))
    except ValueError:  # unexpected label shape sorts last, rather than raising
        return (99, 99)


def _inning_sort_key(label: str) -> tuple[int, ...]:
    try:
        return (int(label),)
    except ValueError:
        return (99,)


@dataclass(frozen=True, slots=True)
class ComparisonType:
    id: str
    label: str
    bucket_fn: BucketFn
    # Orders buckets for display. Labels are strings, so numeric dimensions need
    # their own key ("10" would otherwise sort before "2"). Defaults to
    # alphabetical, which suits the categorical dimensions.
    sort_key: Callable[[str], Any] | None = None


# Dimensions are deliberately fine-grained: callers group the values they want
# (e.g. several pitch types into one segment) rather than being handed fixed
# bands.
COMPARISON_TYPES: dict[str, ComparisonType] = {
    ct.id: ct
    for ct in (
        ComparisonType("windup_stretch", "Windup vs stretch", _windup_stretch_bucket),
        ComparisonType("pitch_type", "Pitch type", _pitch_type_bucket),
        ComparisonType("batter_hand", "Batter hand", _batter_hand_bucket),
        ComparisonType("count", "Count (balls-strikes)", _count_bucket, _count_sort_key),
        ComparisonType("inning", "Inning", _inning_bucket, _inning_sort_key),
    )
}


@dataclass(frozen=True, slots=True)
class GuidSplitResult:
    """Buckets of play GUIDs for one pitcher across the supplied games."""

    buckets: dict[str, list[str]]  # bucket label → play GUIDs
    dominant_hand: str  # neutral "left" | "right"
    pitch_hand: str  # raw MLB pitchHand code ("R" | "L")


def split_guids(
    games: list[tuple[str, list[dict[str, Any]]]],
    *,
    pitcher_id: int,
    comparison_type: str,
) -> GuidSplitResult:
    """Bucket one pitcher's play GUIDs across games by comparison type.

    :param games: ``(game_id, guid_dicts)`` per game, as fetched from the
        Stats API guids endpoint.
    :param pitcher_id: MLB person id; plays by other pitchers are skipped.
    :param comparison_type: Key into :data:`COMPARISON_TYPES`.
    :raises UnknownComparisonTypeError: Unsupported ``comparison_type``.
    :raises NoMatchingPitchesError: No plays matched the pitcher.
    :raises PitchHandNotDeterminedError: Pitch hand missing, unsupported, or
        conflicting across the selected games.
    """
    ct = COMPARISON_TYPES.get(comparison_type)
    if ct is None:
        raise UnknownComparisonTypeError(
            f"Unknown comparison type '{comparison_type}'; expected one of "
            f"{sorted(COMPARISON_TYPES)}"
        )

    buckets: dict[str, list[str]] = {}
    pitch_hands: set[str] = set()
    matched = 0
    target_pid = int(pitcher_id)

    for _game_id, guid_dicts in games:
        for guid_dict in guid_dicts:
            guid = guid_dict.get("guid")
            meta_data = guid_dict.get("metaData") or {}
            play = meta_data.get("stat", {}).get("play") or {}
            if not guid or not play.get("count"):
                continue

            pid = meta_data.get("pitcher", {}).get("id")
            if pid is None:
                continue
            try:
                if int(pid) != target_pid:
                    continue
            except (TypeError, ValueError):
                # Non-numeric pitcher id in an undocumented payload — skip it
                # rather than crash the whole split.
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
        raise NoMatchingPitchesError(
            f"No pitches found for pitcher {pitcher_id} in the selected games — "
            "verify the pitcher appeared in those games"
        )
    if len(pitch_hands) > 1:
        raise PitchHandNotDeterminedError(
            f"Selected games mix pitch hands {sorted(pitch_hands)} for pitcher "
            f"{pitcher_id} — narrow the selection to games with a single hand"
        )
    hand = next(iter(pitch_hands), None)
    dominant_hand = PITCH_HAND_TO_DOMINANT_HAND.get(hand or "")
    if dominant_hand is None:
        raise PitchHandNotDeterminedError(
            f"Unsupported or missing pitch hand {hand!r} for pitcher {pitcher_id}"
        )

    # Buckets accumulate in play order, which is meaningless to a reader picking
    # values to group. Order them by the dimension's own sense of sequence.
    ordered = sorted(buckets, key=ct.sort_key) if ct.sort_key else sorted(buckets)
    return GuidSplitResult(
        buckets={label: buckets[label] for label in ordered},
        dominant_hand=dominant_hand,
        pitch_hand=hand,
    )
