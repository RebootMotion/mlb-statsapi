"""Tests for the pure pitch-bucketing logic."""

from __future__ import annotations

from typing import Any

import pytest

from mlb_statsapi.bucketing import (
    COMPARISON_TYPES,
    NoMatchingPitchesError,
    PitchHandNotDeterminedError,
    UnknownComparisonTypeError,
    split_guids,
)

PITCHER_ID = 660271
OTHER_PITCHER_ID = 543037


def make_guid(
    guid: str,
    *,
    pitcher_id: int = PITCHER_ID,
    pitch_hand: str | None = "R",
    balls: int = 0,
    strikes: int = 0,
    inning: int = 1,
    runners: bool = False,
    pitch_type: str | None = "Four-Seam Fastball",
    bat_side: str | None = "L",
) -> dict[str, Any]:
    play: dict[str, Any] = {
        "count": {
            "balls": balls,
            "strikes": strikes,
            "inning": inning,
            "runnerOn1b": runners,
            "runnerOn2b": False,
            "runnerOn3b": False,
        },
        "details": {},
    }
    if pitch_hand is not None:
        play["details"]["pitchHand"] = {"code": pitch_hand}
    if pitch_type is not None:
        play["details"]["type"] = {"description": pitch_type}
    if bat_side is not None:
        play["details"]["batSide"] = {"code": bat_side}
    return {
        "guid": guid,
        "metaData": {"pitcher": {"id": pitcher_id}, "stat": {"play": play}},
    }


class TestBucketFunctions:
    def test_windup_stretch(self) -> None:
        result = split_guids(
            [("g1", [make_guid("a", runners=False), make_guid("b", runners=True)])],
            pitcher_id=PITCHER_ID,
            comparison_type="windup_stretch",
        )
        assert result.buckets == {"windup": ["a"], "stretch": ["b"]}

    def test_pitch_type(self) -> None:
        result = split_guids(
            [
                (
                    "g1",
                    [
                        make_guid("a", pitch_type="Four-Seam Fastball"),
                        make_guid("b", pitch_type="Curveball"),
                        make_guid("c", pitch_type=None),  # untyped play skipped, not crashed
                    ],
                )
            ],
            pitcher_id=PITCHER_ID,
            comparison_type="pitch_type",
        )
        assert result.buckets == {"Four-Seam Fastball": ["a"], "Curveball": ["b"]}

    def test_batter_hand(self) -> None:
        result = split_guids(
            [("g1", [make_guid("a", bat_side="L"), make_guid("b", bat_side="R")])],
            pitcher_id=PITCHER_ID,
            comparison_type="batter_hand",
        )
        assert result.buckets == {"L": ["a"], "R": ["b"]}

    def test_count_uses_balls_strikes(self) -> None:
        result = split_guids(
            [
                (
                    "g1",
                    [
                        make_guid("a", balls=1, strikes=2),
                        make_guid("b", balls=0, strikes=0),
                        make_guid("c", balls=1, strikes=2),
                    ],
                )
            ],
            pitcher_id=PITCHER_ID,
            comparison_type="count",
        )
        assert result.buckets == {"0-0": ["b"], "1-2": ["a", "c"]}

    def test_count_ordered_by_balls_then_strikes(self) -> None:
        result = split_guids(
            [
                (
                    "g1",
                    [
                        make_guid("a", balls=3, strikes=2),
                        make_guid("b", balls=0, strikes=1),
                        make_guid("c", balls=1, strikes=0),
                    ],
                )
            ],
            pitcher_id=PITCHER_ID,
            comparison_type="count",
        )
        assert list(result.buckets) == ["0-1", "1-0", "3-2"]

    @pytest.mark.parametrize("inning", [1, 4, 7, 12])
    def test_inning_uses_exact_inning(self, inning: int) -> None:
        result = split_guids(
            [("g1", [make_guid("a", inning=inning)])],
            pitcher_id=PITCHER_ID,
            comparison_type="inning",
        )
        assert result.buckets == {str(inning): ["a"]}

    def test_innings_sort_numerically_not_lexically(self) -> None:
        result = split_guids(
            [
                (
                    "g1",
                    [
                        make_guid("a", inning=10),
                        make_guid("b", inning=2),
                        make_guid("c", inning=9),
                    ],
                )
            ],
            pitcher_id=PITCHER_ID,
            comparison_type="inning",
        )
        # "10" must not sort before "2".
        assert list(result.buckets) == ["2", "9", "10"]


class TestSplitGuids:
    def test_filters_other_pitchers(self) -> None:
        result = split_guids(
            [("g1", [make_guid("a"), make_guid("b", pitcher_id=OTHER_PITCHER_ID)])],
            pitcher_id=PITCHER_ID,
            comparison_type="windup_stretch",
        )
        assert result.buckets == {"windup": ["a"]}

    def test_multi_game_aggregation(self) -> None:
        result = split_guids(
            [
                ("g1", [make_guid("a", runners=True)]),
                ("g2", [make_guid("b", runners=True), make_guid("c")]),
            ],
            pitcher_id=PITCHER_ID,
            comparison_type="windup_stretch",
        )
        assert result.buckets == {"stretch": ["a", "b"], "windup": ["c"]}

    def test_dominant_hand_inference(self) -> None:
        result = split_guids(
            [("g1", [make_guid("a", pitch_hand="L")])],
            pitcher_id=PITCHER_ID,
            comparison_type="windup_stretch",
        )
        assert result.dominant_hand == "left"
        assert result.pitch_hand == "L"

    def test_unknown_comparison_type(self) -> None:
        with pytest.raises(UnknownComparisonTypeError):
            split_guids([("g1", [make_guid("a")])], pitcher_id=PITCHER_ID, comparison_type="nope")

    def test_no_matching_pitches(self) -> None:
        with pytest.raises(NoMatchingPitchesError):
            split_guids(
                [("g1", [make_guid("a", pitcher_id=OTHER_PITCHER_ID)])],
                pitcher_id=PITCHER_ID,
                comparison_type="windup_stretch",
            )

    def test_conflicting_hands_across_games(self) -> None:
        with pytest.raises(PitchHandNotDeterminedError):
            split_guids(
                [
                    ("g1", [make_guid("a", pitch_hand="R")]),
                    ("g2", [make_guid("b", pitch_hand="L")]),
                ],
                pitcher_id=PITCHER_ID,
                comparison_type="windup_stretch",
            )

    def test_missing_pitch_hand(self) -> None:
        with pytest.raises(PitchHandNotDeterminedError):
            split_guids(
                [("g1", [make_guid("a", pitch_hand=None)])],
                pitcher_id=PITCHER_ID,
                comparison_type="windup_stretch",
            )

    def test_malformed_plays_skipped(self) -> None:
        malformed = [
            {"guid": "x"},  # no metaData
            {"metaData": {"pitcher": {"id": PITCHER_ID}}},  # no guid, no play
            {"guid": "y", "metaData": {"pitcher": {"id": PITCHER_ID}, "stat": {"play": {}}}},
        ]
        result = split_guids(
            [("g1", [*malformed, make_guid("a")])],
            pitcher_id=PITCHER_ID,
            comparison_type="windup_stretch",
        )
        assert result.buckets == {"windup": ["a"]}

    def test_non_numeric_pitcher_id_skipped(self) -> None:
        bad = {
            "guid": "x",
            "metaData": {"pitcher": {"id": "not-a-number"}, "stat": {"play": {"count": {}}}},
        }
        result = split_guids(
            [("g1", [bad, make_guid("a")])],
            pitcher_id=PITCHER_ID,
            comparison_type="windup_stretch",
        )
        assert result.buckets == {"windup": ["a"]}

    def test_comparison_types_registry(self) -> None:
        assert set(COMPARISON_TYPES) == {
            "windup_stretch",
            "pitch_type",
            "batter_hand",
            "count",
            "inning",
        }
        assert all(ct.label for ct in COMPARISON_TYPES.values())
