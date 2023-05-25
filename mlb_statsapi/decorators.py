from __future__ import annotations

from .constants import MetaFields
from typing import Any

# Requires a zero argument callable that we try to run as normal. 
# If f errors, return a special value
def t(f) -> Any:
    try:
        return f()
    except (AttributeError, KeyError) as e:
        print("MISSING ELEMENT")
        # TODO Print stack trace and more metadata
        return MetaFields.NOT_FOUND
