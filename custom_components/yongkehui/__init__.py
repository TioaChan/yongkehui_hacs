"""The YongKeHui integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import YongKeHuiApiClient
from .const import (
    CONF_COMMUNITY_ID,
    CONF_COOKIES,
    CONF_CUST_ID,
    CONF_DEVICE_ID,
    CONF_USER_ID,
    DOMAIN,
    NAME,
)
from .coordinator import YongKeHuiDataUpdateCoordinator
from .notifications import async_notify_api_failure

PLATFORMS = [Platform.LOCK]
DATA_PENDING_APIS = "pending_apis"


@dataclass
class YongKeHuiRuntimeData:
    """Runtime data for a YongKeHui config entry."""

    api: YongKeHuiApiClient
    coordinator: YongKeHuiDataUpdateCoordinator


YongKeHuiConfigEntry = ConfigEntry


async def async_setup_entry(
    hass: HomeAssistant, entry: YongKeHuiConfigEntry
) -> bool:
    """Set up YongKeHui from a config entry."""

    if entry.title.startswith("永客汇"):
        hass.config_entries.async_update_entry(
            entry, title=f"{NAME}{entry.title.removeprefix('永客汇')}"
        )

    pending_apis = hass.data.setdefault(DOMAIN, {}).setdefault(DATA_PENDING_APIS, {})
    api = pending_apis.pop(entry.unique_id, None) if entry.unique_id else None
    if api is None:
        api = YongKeHuiApiClient(
            async_get_clientsession(hass),
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            entry.data[CONF_DEVICE_ID],
            entry.data.get(CONF_COOKIES),
            entry.data.get(CONF_COMMUNITY_ID),
            entry.data.get(CONF_CUST_ID),
            entry.data.get(CONF_USER_ID),
            api_failure_notifier=lambda details: async_notify_api_failure(
                hass, details
            ),
        )
    coordinator = YongKeHuiDataUpdateCoordinator(hass, api)
    if api.doors:
        coordinator.async_set_updated_data(api.doors)
    else:
        await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = YongKeHuiRuntimeData(api=api, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: YongKeHuiConfigEntry
) -> bool:
    """Unload a YongKeHui config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
