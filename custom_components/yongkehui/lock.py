"""Lock entities for YongKeHui doors."""

from __future__ import annotations

from homeassistant.components.lock import LockEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import YongKeHuiConfigEntry
from .api import CannotUnlock, YongKeHuiDoor
from .const import AUTO_RELOCK_SECONDS, DOMAIN, NAME
from .coordinator import YongKeHuiDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YongKeHuiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up YongKeHui lock entities."""

    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        YongKeHuiLock(coordinator, door_id)
        for door_id in coordinator.data
    )


class YongKeHuiLock(CoordinatorEntity, LockEntity):
    """A YongKeHui door represented as a lock."""

    _attr_has_entity_name = False

    def __init__(
        self, coordinator: YongKeHuiDataUpdateCoordinator, door_id: str
    ) -> None:
        super().__init__(coordinator)
        self._door_id = door_id
        self._last_door = coordinator.data[door_id]
        self._attr_unique_id = self._last_door.unique_id
        self._attr_is_locked = True
        self._relock_cancel: CALLBACK_TYPE | None = None

    @property
    def _door(self) -> YongKeHuiDoor:
        door = self.coordinator.data.get(self._door_id)
        if door is not None:
            self._last_door = door
        return self._last_door

    @property
    def name(self) -> str:
        return self._door.name

    @property
    def available(self) -> bool:
        return super().available and self._door_id in self.coordinator.data

    @property
    def device_info(self) -> dict:
        door = self._door
        return {
            "identifiers": {(DOMAIN, door.unique_id)},
            "manufacturer": NAME,
            "name": door.name,
        }

    async def async_unlock(self, **kwargs) -> None:
        """Open the door and temporarily mark the lock as unlocked."""

        try:
            await self.coordinator.api.async_unlock(self._door)
        except CannotUnlock as err:
            raise HomeAssistantError(f"永客会开门失败：{err}") from err

        self._attr_is_locked = False
        self.async_write_ha_state()
        self._schedule_relock()

    async def async_lock(self, **kwargs) -> None:
        """Mark the door as locked.

        YongKeHui only exposes an open-door API; the physical door locks itself.
        """

        self._cancel_relock()
        self._attr_is_locked = True
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_relock()

    @callback
    def _schedule_relock(self) -> None:
        self._cancel_relock()
        self._relock_cancel = async_call_later(
            self.hass,
            AUTO_RELOCK_SECONDS,
            self._async_mark_locked,
        )

    @callback
    def _cancel_relock(self) -> None:
        if self._relock_cancel is not None:
            self._relock_cancel()
            self._relock_cancel = None

    @callback
    def _async_mark_locked(self, _now=None) -> None:
        self._relock_cancel = None
        self._attr_is_locked = True
        self.async_write_ha_state()
