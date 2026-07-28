"""Home Assistant notifications for YongKeHui."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN, NAME


def async_notify_api_failure(
    hass: HomeAssistant, details: dict[str, Any]
) -> None:
    """Create or update a persistent notification for an API failure."""

    method = str(details.get("method") or "-")
    endpoint = str(details.get("endpoint") or "-")
    notification_id = f"{DOMAIN}_api_failure_{_slug(method)}_{_slug(endpoint)}"

    lines = [
        f"- 时间: `{dt_util.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        f"- 接口: `{method} {endpoint}`",
        f"- HTTP 状态: `{details.get('status') or '-'}`",
        f"- 业务 code: `{details.get('code') or '-'}`",
        f"- 信息: `{details.get('message') or details.get('error') or '-'}`",
        f"- 耗时: `{details.get('elapsed_ms') or '-'} ms`",
        f"- community_id: `{details.get('community_id') or '-'}`",
    ]
    persistent_notification.async_create(
        hass,
        "\n".join(lines),
        title=f"{NAME} API 调用失败",
        notification_id=notification_id,
    )


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower() or "unknown"
