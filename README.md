# mlb-statsapi
Python library for working with the MLB Stats API


## Examples
Please look in the examples folder for usage. For available attributes on the data objects, please look in the docs folder.
To see all fields available on the raw game feed data, please view docs/game_data.txt. This is still a WIP so may contain errors or omissions.


## Stats API client (`StatsApiClient`)

`mlb_statsapi.StatsApiClient` is a small synchronous wrapper over the Stats API
returning raw JSON dicts, with `requests`-level retries and library-local
errors (`StatsApiError` / `StatsApiAuthError`):

```python
from mlb_statsapi import StatsApiClient

client = StatsApiClient()
person = client.get_person(660271)              # public
games = client.get_schedule(start_date="2026-06-01", end_date="2026-06-02")
guids = client.get_game_guids(745123, access_token="<okta bearer>")  # auth required
```


## Biomech Studio movement-source plugin (optional)

The `[biomech]` extra ships `mlb_statsapi.movement_source.MlbStatsMovementSource`,
a movement-source plugin for [Biomech Studio](https://github.com/RebootMotion/reboot-motion-capture).
It is loaded by a running Biomech Studio process via `BIOMECH_MOVEMENT_SOURCES`
and imports the movement-source contract from that host, so it is **not**
importable standalone. Install it alongside the app and run
`playwright install chromium` for interactive Okta login:

```bash
pip install -e '.[biomech]'
playwright install chromium
```


## License
Please see LICENSE and LICENSE.mlb file for usage