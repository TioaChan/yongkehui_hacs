"""Payload parsing helpers for YongKeHui API responses."""

from __future__ import annotations

from typing import Any

from .models import YongKeHuiContext, YongKeHuiHouse


def api_code(payload: Any) -> int | None:
    """Return the numeric API code if present."""

    if not isinstance(payload, dict) or "code" not in payload:
        return None
    try:
        return int(payload["code"])
    except (TypeError, ValueError):
        return None


def api_message(payload: Any) -> str:
    """Return a human-readable API message."""

    if isinstance(payload, dict):
        for key in ("message", "msg", "desc", "error"):
            value = payload.get(key)
            if value:
                return str(value)
    return "永客会 API 返回失败"


def coerce_str(value: Any) -> str | None:
    """Coerce an arbitrary payload value to a non-empty string."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def value_for_keys(mapping: dict[str, Any], *keys: str) -> str | None:
    """Find a value by case-insensitive key names."""

    wanted = {key.lower() for key in keys}
    for key, value in mapping.items():
        if key.lower() in wanted:
            return coerce_str(value)
    return None


def iter_door_dicts(payload: Any) -> list[dict[str, Any]]:
    """Return payload dictionaries that look like door records."""

    return [
        mapping
        for mapping in _iter_dicts(payload)
        if value_for_keys(mapping, "doorId", "id")
        and value_for_keys(mapping, "doorIdStr", "doorIdString")
    ]


def extract_contexts(*payloads: Any) -> list[YongKeHuiContext]:
    """Extract account/community contexts from one or more payloads."""

    contexts: list[YongKeHuiContext] = []
    seen: set[tuple[str, str, str | None]] = set()
    fallback_user_id = None

    for payload in payloads:
        fallback_user_id = fallback_user_id or _find_first(payload, "userId", "user_id")

    for payload in payloads:
        for mapping in _iter_dicts(payload):
            community_id = value_for_keys(mapping, "communityId", "community_id")
            cust_id = value_for_keys(mapping, "custId", "cust_id")
            if not community_id or not cust_id:
                continue

            user_id = value_for_keys(mapping, "userId", "user_id") or fallback_user_id
            key = (community_id, cust_id, user_id)
            if key in seen:
                continue
            seen.add(key)
            contexts.append(YongKeHuiContext(community_id, cust_id, user_id))

    if contexts:
        return contexts

    community_id = None
    cust_id = None
    for payload in payloads:
        community_id = community_id or _find_first(
            payload, "communityId", "community_id"
        )
        cust_id = cust_id or _find_first(payload, "custId", "cust_id")

    if community_id and cust_id:
        return [YongKeHuiContext(community_id, cust_id, fallback_user_id)]
    return []


def extract_houses(payload: Any) -> list[YongKeHuiHouse]:
    """Extract selectable houses from a profile payload."""

    data = payload.get("data") if isinstance(payload, dict) else None
    fallback_user_id = _find_first(payload, "userId", "user_id")
    raw_houses = data.get("houseList") if isinstance(data, dict) else None
    houses: list[YongKeHuiHouse] = []
    seen: set[tuple[str, str, str | None]] = set()

    if isinstance(raw_houses, list):
        for raw_house in raw_houses:
            if not isinstance(raw_house, dict):
                continue

            community_id = value_for_keys(raw_house, "communityId", "community_id")
            cust_id = value_for_keys(raw_house, "custId", "cust_id")
            if not community_id or not cust_id:
                continue

            user_id = value_for_keys(raw_house, "userId", "user_id") or fallback_user_id
            key = (community_id, cust_id, user_id)
            if key in seen:
                continue
            seen.add(key)
            houses.append(
                YongKeHuiHouse(
                    community_id=community_id,
                    cust_id=cust_id,
                    user_id=user_id,
                    name=_house_name(raw_house, community_id),
                )
            )

    if houses:
        return houses

    return [
        YongKeHuiHouse(
            community_id=context.community_id,
            cust_id=context.cust_id,
            user_id=context.user_id,
            name=f"小区 {context.community_id}",
        )
        for context in extract_contexts(payload)
    ]


def door_name(raw: dict[str, Any], door_id: str) -> str:
    """Build the HA entity name for a door record."""

    name = value_for_keys(raw, "name")
    flag_name = value_for_keys(raw, "flagName", "flag_name")
    if name and flag_name:
        return f"{name}_{flag_name}"

    for key in (
        "doorName",
        "door_name",
        "name",
        "deviceName",
        "positionName",
        "address",
        "doorAddress",
    ):
        value = value_for_keys(raw, key)
        if value:
            return value
    return f"门禁 {door_id}"


def door_unique_id(community_id: str, door_id: str) -> str:
    """Return the stable unique id for a door."""

    return f"{community_id}.{door_id}"


def _iter_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_iter_dicts(child))
    elif isinstance(value, list):
        for item in value:
            found.extend(_iter_dicts(item))
    return found


def _find_first(value: Any, *keys: str) -> str | None:
    for mapping in _iter_dicts(value):
        result = value_for_keys(mapping, *keys)
        if result:
            return result
    return None


def _house_name(raw: dict[str, Any], community_id: str) -> str:
    house_name = value_for_keys(raw, "houseName", "house_name")
    community_name = value_for_keys(raw, "communityName", "community_name")
    room_no = value_for_keys(raw, "roomNo", "room_no")
    if house_name and community_name and not house_name.startswith(community_name):
        return f"{community_name} {house_name}"
    if house_name:
        return house_name
    if community_name and room_no:
        return f"{community_name} {room_no}"
    if community_name:
        return community_name
    return f"小区 {community_id}"
