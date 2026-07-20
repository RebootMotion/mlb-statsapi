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
    strikes: int = 0,
    inning: int = 1,
    runners: bool = False,
    pitch_type: str | None = "Four-Seam Fastball",
    bat_side: str | None = "L",
) -> dict[str, Any]:
    play: dict[str, Any] = {
        "count": {
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

    def test_two_strike_count(self) -> None:
        result = split_guids(
            [("g1", [make_guid("a", strikes=2), make_guid("b", strikes=1)])],
            pitcher_id=PITCHER_ID,
            comparison_type="two_strike_count",
        )
        assert result.buckets == {"two_strikes": ["a"], "other_counts": ["b"]}

    @pytest.mark.parametrize(
        ("inning", "bucket"),
        [
            (1, "innings_1_to_3"),
            (3, "innings_1_to_3"),
            (4, "innings_4_to_6"),
            (6, "innings_4_to_6"),
            (7, "innings_7_plus"),
            (9, "innings_7_plus"),
        ],
    )
    def test_inning_range_boundaries(self, inning: int, bucket: str) -> None:
        result = split_guids(
            [("g1", [make_guid("a", inning=inning)])],
            pitcher_id=PITCHER_ID,
            comparison_type="inning_range",
        )
        assert result.buckets == {bucket: ["a"]}


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
            "two_strike_count",
            "inning_range",
        }
        assert all(ct.label for ct in COMPARISON_TYPES.values())
