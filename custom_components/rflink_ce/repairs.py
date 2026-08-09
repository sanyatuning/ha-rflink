"""Repair flow that classifies a newly-heard, Unclassified Device."""

from __future__ import annotations

from fnmatch import fnmatch
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_DEVICE_ID, CONF_NAME
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .config_flow import _split
from .const import (
    CONF_ALIASES,
    CONF_DOWN_TIME,
    CONF_ENTITY_DOMAIN,
    CONF_FIRE_EVENT,
    CONF_GROUP_ALIASES,
    CONF_IGNORE_PATTERNS,
    CONF_NOGROUP_ALIASES,
    CONF_SIGNAL_REPETITIONS,
    CONF_UP_TIME,
    DOMAIN,
    ENTITY_DOMAIN_COVER,
    ENTITY_DOMAIN_IGNORE,
    ENTITY_DOMAIN_SENSOR,
    ISSUE_ID_UNCLASSIFIED_DEVICE,
    REPAIR_ENTITY_DOMAINS,
    SIGNAL_NEW_DEVICE,
    SUBENTRY_TYPE_DEVICE,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

COVER_ID_PATTERNS = ("*motor*", "*cover*", "*shutter*", "*blind*", "*roll*")


def _suggest_domain(data: dict[str, Any]) -> str | None:
    """Guess an entity domain from the raw signal, for the user to confirm or change."""
    if "sensor" in data:
        return ENTITY_DOMAIN_SENSOR
    raw_id = str(data.get("raw_id", data.get("device_id", "")))
    if any(fnmatch(raw_id, pattern) for pattern in COVER_ID_PATTERNS):
        return ENTITY_DOMAIN_COVER
    return None


def _format_debug_info(data: dict[str, Any]) -> str:
    """Render every distinct RF Signal seen from this device, for the classify form."""
    lines = [f"id: {data.get('raw_id', data.get('device_id'))}"]
    history = data.get("history")
    if history:
        lines.append(str(history))
    return "\n".join(lines)


class UnclassifiedDeviceRepairFlow(RepairsFlow):
    """Classify a newly-heard device, or ignore it, from its repair issue."""

    def __init__(self, entry_id: str, device_id: str, raw_data: dict[str, Any]) -> None:
        """Store which Gateway and Device ID this issue is about."""
        self._entry_id = entry_id
        self._device_id = device_id
        self._suggested_domain = _suggest_domain(raw_data)
        self._debug_info = _format_debug_info(raw_data)

    def _ignore(self, hass: HomeAssistant, entry: Any) -> None:
        """Add this device_id to the Gateway's Ignore Patterns."""
        patterns = list(entry.options.get(CONF_IGNORE_PATTERNS, []))
        if self._device_id not in patterns:
            patterns.append(self._device_id)
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_IGNORE_PATTERNS: patterns}
            )

    def _drop_issue(self, hass: HomeAssistant, entry: Any) -> None:
        """Forget this device's history and dismiss its repair issue."""
        entry.runtime_data.clear_unclassified_history(self._device_id)
        ir.async_delete_issue(
            hass,
            DOMAIN,
            ISSUE_ID_UNCLASSIFIED_DEVICE.format(self._entry_id, self._device_id),
        )

    def _classify(
        self, hass: HomeAssistant, entry: Any, user_input: dict[str, Any]
    ) -> None:
        """Create the Device (subentry) from the submitted classification."""
        data = {
            CONF_DEVICE_ID: self._device_id,
            CONF_ENTITY_DOMAIN: user_input[CONF_ENTITY_DOMAIN],
            CONF_ALIASES: _split(user_input.get(CONF_ALIASES)),
            CONF_GROUP_ALIASES: _split(user_input.get(CONF_GROUP_ALIASES)),
            CONF_NOGROUP_ALIASES: _split(user_input.get(CONF_NOGROUP_ALIASES)),
            CONF_FIRE_EVENT: user_input.get(CONF_FIRE_EVENT, False),
            CONF_SIGNAL_REPETITIONS: user_input.get(CONF_SIGNAL_REPETITIONS),
            CONF_UP_TIME: user_input.get(CONF_UP_TIME),
            CONF_DOWN_TIME: user_input.get(CONF_DOWN_TIME),
        }
        subentry = ConfigSubentry(
            data=MappingProxyType(data),
            subentry_type=SUBENTRY_TYPE_DEVICE,
            title=user_input[CONF_NAME],
            unique_id=self._device_id,
        )
        hass.config_entries.async_add_subentry(entry, subentry)
        async_dispatcher_send(hass, SIGNAL_NEW_DEVICE.format(entry.entry_id), subentry)
        if data[CONF_ENTITY_DOMAIN] == ENTITY_DOMAIN_SENSOR:
            entry.runtime_data.seed_sensor_fields(self._device_id, subentry)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        """Classify the device, or ignore it, in a single form."""
        hass: HomeAssistant = self.hass
        entry = hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="gateway_removed")

        if user_input is not None:
            if user_input[CONF_ENTITY_DOMAIN] == ENTITY_DOMAIN_IGNORE:
                self._ignore(hass, entry)
            else:
                self._classify(hass, entry, user_input)
            self._drop_issue(hass, entry)
            return self.async_create_entry(data={})

        entity_domain_key: Any = (
            vol.Optional(CONF_ENTITY_DOMAIN, default=self._suggested_domain)
            if self._suggested_domain
            else vol.Required(CONF_ENTITY_DOMAIN)
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=self._device_id): str,
                entity_domain_key: SelectSelector(
                    SelectSelectorConfig(options=REPAIR_ENTITY_DOMAINS)
                ),
                vol.Optional(CONF_ALIASES): str,
                vol.Optional(CONF_GROUP_ALIASES): str,
                vol.Optional(CONF_NOGROUP_ALIASES): str,
                vol.Optional(CONF_FIRE_EVENT, default=False): bool,
                vol.Optional(CONF_SIGNAL_REPETITIONS): int,
                vol.Optional(CONF_UP_TIME): vol.Coerce(float),
                vol.Optional(CONF_DOWN_TIME): vol.Coerce(float),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "device_id": self._device_id,
                "debug_info": self._debug_info,
            },
        )


async def async_create_fix_flow(
    _hass: HomeAssistant,
    _issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create the classification flow for an unclassified_device issue."""
    if data is None:
        msg = "Repair issue data missing for unclassified_device flow"
        raise HomeAssistantError(msg)
    return UnclassifiedDeviceRepairFlow(
        entry_id=str(data["entry_id"]),
        device_id=str(data["device_id"]),
        raw_data=data,
    )
