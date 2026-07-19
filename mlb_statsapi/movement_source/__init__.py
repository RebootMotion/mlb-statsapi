"""MLB Stats API movement-source plugin (optional ``[biomech]`` extra).

Sources MLB play GUIDs (the org_movement_ids used by the Reboot cloud) from
the official MLB Stats API and buckets them by pitching comparison types.

This subpackage is loaded by a running biomech_studio process via
``BIOMECH_MOVEMENT_SOURCES`` and imports the movement-source contract from that
host, so it is not importable standalone. Point the dotted path at
``mlb_statsapi.movement_source.MlbStatsMovementSource``. Interactive browser
login also needs the ``[biomech]`` extra's Playwright install (paste-token auth
works without it).
"""

from mlb_statsapi.movement_source.source import MlbStatsMovementSource

__all__ = ["MlbStatsMovementSource"]
