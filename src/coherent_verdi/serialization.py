"""Consistent JSON for CLI and integration clients."""

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any


def _default(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def to_json(value: object, *, indent: int | None = 2) -> str:
    return json.dumps(value, default=_default, indent=indent, allow_nan=False)
