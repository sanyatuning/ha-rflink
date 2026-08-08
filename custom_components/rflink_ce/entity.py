"""Base entity for RFLink CE devices."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import (
    CONF_FIRE_EVENT,
    CONF_SIGNAL_REPETITIONS,
    DEFAULT_SIGNAL_REPETITIONS,
    DOMAIN,
    EVENT_KEY_COMMAND,
    SIGNAL_AVAILABILITY,
    SIGNAL_HANDLE_EVENT,
)
from .hub import RflinkCeConfigEntry

EVENT_BUTTON_PRESSED = "rflink_ce_button_pressed"


class RflinkCeEntity(Entity):
    """Common logic for entities backed by a classified RFLink CE Device."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_available = False

    def __init__(
        self,
        entry: RflinkCeConfigEntry,
        subentry: ConfigSubentry,
        unique_id_suffix: str = "",
    ) -> None:
        """Initialize the entity for a given Device (subentry)."""
        self.entry = entry
        self.hub = entry.runtime_data
        self.subentry = subentry
        self._device_id: str = subentry.data[CONF_DEVICE_ID]
        self._attr_unique_id = f"{subentry.subentry_id}{unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            via_device=(DOMAIN, entry.entry_id),
        )

    @property
    def event_type(self) -> str:
        """Return the RFLink event type this entity reacts to."""
        return EVENT_KEY_COMMAND

    async def async_added_to_hass(self) -> None:
        """Register dispatcher callbacks once added."""
        self._attr_available = self.hub.available
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_AVAILABILITY.format(self.entry.entry_id),
                self._async_availability_changed,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_HANDLE_EVENT.format(self.subentry.subentry_id, self.event_type),
                self._async_handle_event_callback,
            )
        )

    @callback
    def _async_availability_changed(self, available: bool) -> None:
        self._attr_available = available
        self.async_write_ha_state()

    @callback
    def _async_handle_event_callback(self, event: dict[str, Any]) -> None:
        """Adjust state if RFLink reports a remote command for this Device."""
        self._handle_event(event)
        self.async_write_ha_state()

        if self.subentry.data.get(CONF_FIRE_EVENT):
            self.hass.bus.async_fire(
                EVENT_BUTTON_PRESSED,
                {"state": event.get(EVENT_KEY_COMMAND), "entity_id": self.entity_id},
            )

    def _handle_event(self, event: dict[str, Any]) -> None:
        """Domain-specific event handling, overridden by platforms."""
        raise NotImplementedError

    async def _async_send_command(self, command: str) -> None:
        """Send a command for this Device to the gateway."""
        repetitions = (
            self.subentry.data.get(CONF_SIGNAL_REPETITIONS) or DEFAULT_SIGNAL_REPETITIONS
        )
        await self.hub.async_send_command(self._device_id, command, repetitions)
