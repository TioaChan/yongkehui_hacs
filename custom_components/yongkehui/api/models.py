"""Data models for YongKeHui API payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class YongKeHuiContext:
    """A YongKeHui account/community context."""

    community_id: str
    cust_id: str
    user_id: str | None = None


@dataclass(frozen=True)
class YongKeHuiHouse(YongKeHuiContext):
    """A selectable YongKeHui house/community."""

    name: str = ""


@dataclass(frozen=True)
class YongKeHuiDoor:
    """A discovered YongKeHui door."""

    unique_id: str
    door_id: str
    door_id_str: str
    name: str
    community_id: str
    cust_id: str
    user_id: str | None
    raw: dict[str, Any]
