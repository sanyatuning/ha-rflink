"""Switch entity for the RFLink CE Gateway's pairing mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import CONF_PAIRING_MODE, DOMAIN

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .hub import RflinkCeConfigEntry


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: RflinkCeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Gateway's pairing mode switch."""
    async_add_entities([RflinkCePairingSwitch(entry)])


class RflinkCePairingSwitch(SwitchEntity):
    """Pairing mode: while off, newly-heard devices never raise a repair issue."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "pairing_mode"

    def __init__(self, entry: RflinkCeConfigEntry) -> None:
        """Initialize the switch on the Gateway's own Device."""
        self.entry = entry
        self.hub = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_pairing_mode"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def is_on(self) -> bool:
        """Return whether pairing mode is enabled."""
        return self.hub.pairing_enabled

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Enable pairing mode, so unknown devices raise repair issues again."""
        self._set_pairing_mode(enabled=True)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Disable pairing mode, so unknown devices are dropped silently."""
        self._set_pairing_mode(enabled=False)

    @callback
    def _set_pairing_mode(self, *, enabled: bool) -> None:
        """Persist pairing mode on the Gateway entry, so it survives restarts."""
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_PAIRING_MODE: enabled}
        )
        self.async_write_ha_state()
