from __future__ import annotations

from typing import Any
from dotenv import dotenv_values

from .constants import MetaFields


# Requires a zero argument callable that we try to run as normal.
# If f errors, return a special value
def t(f) -> Any:
    config = dotenv_values(".env")

    if 'DEBUG' in config:
        return f()

    try:
        return f()
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        print("MISSING ELEMENT")
        # TODO Print stack trace and more metadata
        return MetaFields.NOT_FOUND
