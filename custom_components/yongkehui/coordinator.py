"""Coordinator for YongKeHui data refresh."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import InvalidAuth, YongKeHuiApiClient, YongKeHuiDoor, YongKeHuiError
from .const import CONF_COOKIES, DOMAIN, TOKEN_REFRESH_INTERVAL

_LOGGER = logging.getLogger(__name__)


class YongKeHuiDataUpdateCoordinator(DataUpdateCoordinator):
    """Keep YongKeHui login state alive and hold discovered door data."""

    def __init__(
        self, hass: HomeAssistant, api: YongKeHuiApiClient, entry: ConfigEntry
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=TOKEN_REFRESH_INTERVAL,
        )
        self.api = api
        self.entry = entry

    async def _async_update_data(self) -> dict[str, YongKeHuiDoor]:
        try:
            doors = await self.api.async_refresh()
        except InvalidAuth as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except YongKeHuiError as err:
            raise UpdateFailed(str(err)) from err

        cookies = self.api.cookies
        if cookies != self.entry.data.get(CONF_COOKIES):
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_COOKIES: cookies}
            )
        return doors
