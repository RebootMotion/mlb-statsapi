from mlb_statsapi import Game
import pytest
import json
from unittest.mock import patch


@pytest.mark.parametrize("game_pk", [718096, 718263, 718322, 718594])
# @pytest.mark.parametrize("game_pk", [718096])
@patch("mlb_statsapi.datatypes.t", lambda f: f())
def test_game_parsing(game_pk):
    with open(f"tests/game_data/{game_pk}.json", 'r') as f:
        data = json.load(f)
    game = Game(data)
    assert game
    assert game.game_pk == game_pk
    assert game.play_ids
    assert game.pitches_by_play_id
    assert game.swings_by_play_id
    assert game.play_event_by_play_id
    assert game.play_video_by_play_id
    assert game.get_filtered_pitch_metrics_by_play_id()
    assert game.get_filtered_pitch_metrics_by_play_id_as_df() is not None
    assert game.get_filtered_swing_metrics_by_play_id()
    assert game.get_filtered_swing_metrics_by_play_id_as_df() is not None
