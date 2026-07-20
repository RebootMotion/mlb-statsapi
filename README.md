# mlb-statsapi
Python library for working with the MLB Stats API


## Examples
Please look in the examples folder for usage. For available attributes on the data objects, please look in the docs folder.
To see all fields available on the raw game feed data, please view docs/game_data.txt. This is still a WIP so may contain errors or omissions.


## Stats API client (`StatsApiClient`)

`mlb_statsapi.StatsApiClient` is a small synchronous wrapper over the Stats API
returning raw JSON dicts, with `requests`-level retries and errors surfaced as
`StatsApiError` / `StatsApiAuthError`:

```python
from mlb_statsapi import StatsApiClient

client = StatsApiClient()
person = client.get_person(660271)              # public
games = client.get_schedule(start_date="2026-06-01", end_date="2026-06-02")
guids = client.get_game_guids(745123, access_token="<okta bearer>")  # auth required
```


## Okta login (`mlb_statsapi.auth`)

Endpoints like the play-guids endpoint need an MLB-org bearer token.
`login_with_browser()` opens a browser for Okta sign-in and returns the captured
token (held in memory by the caller — not written to disk). It needs the `[auth]`
extra's Playwright:

```bash
pip install '.[auth]'
playwright install chromium
```

```python
from mlb_statsapi.auth import login_with_browser
token = login_with_browser()   # blocking; run off the event loop in async code
```


## Pitch bucketing (`mlb_statsapi.bucketing`)

`split_guids()` groups a pitcher's play GUIDs (from `get_game_guids`) into named
buckets by a comparison type — windup vs stretch, pitch type, batter hand,
two-strike count, or inning range:

```python
from mlb_statsapi.bucketing import split_guids, COMPARISON_TYPES

result = split_guids(games, pitcher_id=660271, comparison_type="windup_stretch")
result.buckets          # {"windup": [...guids], "stretch": [...guids]}
result.dominant_hand    # "left" | "right"
```


## License
Please see LICENSE and LICENSE.mlb file for usage