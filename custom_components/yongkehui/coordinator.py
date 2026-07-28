"""Coordinator for YongKeHui data refresh."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import YongKeHuiApiClient, YongKeHuiDoor, YongKeHuiError
from .const import DOMAIN, TOKEN_REFRESH_INTERVAL

_LOGGER = logging.getLogger(__name__)


class YongKeHuiDataUpdateCoordinator(DataUpdateCoordinator):
    """Keep YongKeHui login state alive and hold discovered door data."""

    def __init__(self, hass: HomeAssistant, api: YongKeHuiApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=TOKEN_REFRESH_INTERVAL,
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, YongKeHuiDoor]:
        try:
            return await self.api.async_refresh()
        except YongKeHuiError as err:
            raise UpdateFailed(str(err)) from err
