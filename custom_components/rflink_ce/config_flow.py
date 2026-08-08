"""Config flow for RFLink CE."""

from __future__ import annotations

import asyncio
from typing import Any

from serial import SerialException
import voluptuous as vol

from homeassistant.components import usb
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_DEVICE_ID, CONF_HOST, CONF_NAME, CONF_PORT, CONF_TYPE
from homeassistant.core import callback
from homeassistant.helpers.selector import TextSelector

from .const import (
    CONF_ALIASES,
    CONF_DOWN_TIME,
    CONF_FIRE_EVENT,
    CONF_GROUP_ALIASES,
    CONF_IGNORE_PATTERNS,
    CONF_NOGROUP_ALIASES,
    CONF_SIGNAL_REPETITIONS,
    CONF_UP_TIME,
    DOMAIN,
    SUBENTRY_TYPE_DEVICE,
)

CONF_MANUAL_PATH = "Enter Manually"
CONNECTION_TIMEOUT = 30


class CannotConnect(Exception):
    """Error indicating a connection couldn't be established."""


async def _async_validate_connection(
    hass, *, host: str | None = None, port: str | int | None = None
) -> None:
    """Try connecting to the gateway, raising CannotConnect on failure."""
    from rflink.protocol import create_rflink_connection  # noqa: PLC0415

    try:
        async with asyncio.timeout(CONNECTION_TIMEOUT):
            transport, _protocol = await create_rflink_connection(
                port=port, host=host, loop=hass.loop
            )
    except (SerialException, OSError, TimeoutError) as err:
        raise CannotConnect from err
    transport.close()


class RflinkCeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for RFLink CE."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose between a serial or network connection."""
        if user_input is not None:
            if user_input[CONF_TYPE] == "Serial":
                return await self.async_step_setup_serial()
            return await self.async_step_setup_network()

        schema = vol.Schema({vol.Required(CONF_TYPE): vol.In(["Serial", "Network"])})
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_setup_network(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure a TCP connection to the gateway."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _async_validate_connection(
                    self.hass, host=user_input[CONF_HOST], port=user_input[CONF_PORT]
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_finish(
                    {CONF_HOST: user_input[CONF_HOST], CONF_PORT: user_input[CONF_PORT]}
                )

        schema = vol.Schema(
            {vol.Required(CONF_HOST): str, vol.Required(CONF_PORT): int}
        )
        return self.async_show_form(
            step_id="setup_network", data_schema=schema, errors=errors
        )

    async def async_step_setup_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a serial port from a scanned list, or enter one manually."""
        errors: dict[str, str] = {}
        if user_input is not None:
            device = user_input[CONF_PORT]
            if device == CONF_MANUAL_PATH:
                return await self.async_step_setup_serial_manual_path()
            try:
                await _async_validate_connection(self.hass, port=device)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_finish({CONF_PORT: device})

        ports = await usb.async_scan_serial_ports(self.hass)
        options = {
            port.device: f"{port.device} - {port.description or 'n/a'}" for port in ports
        }
        options[CONF_MANUAL_PATH] = CONF_MANUAL_PATH
        schema = vol.Schema({vol.Required(CONF_PORT): vol.In(options)})
        return self.async_show_form(
            step_id="setup_serial", data_schema=schema, errors=errors
        )

    async def async_step_setup_serial_manual_path(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter a serial device path by hand."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _async_validate_connection(self.hass, port=user_input[CONF_PORT])
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return await self._async_finish({CONF_PORT: user_input[CONF_PORT]})

        schema = vol.Schema({vol.Required(CONF_PORT): str})
        return self.async_show_form(
            step_id="setup_serial_manual_path", data_schema=schema, errors=errors
        )

    async def _async_finish(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Create or update the config entry with validated connection data."""
        if self.source == "reconfigure":
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data=data
            )
        await self.async_set_unique_id(data.get(CONF_HOST) or data[CONF_PORT])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="RFLink CE", data=data)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure an existing Gateway's connection."""
        return await self.async_step_user(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow for Ignore Patterns."""
        return RflinkCeOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentry types supported by this integration."""
        return {SUBENTRY_TYPE_DEVICE: DeviceSubentryFlowHandler}


class RflinkCeOptionsFlow(OptionsFlow):
    """Manage the Gateway's Ignore Pattern list."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the Ignore Pattern list."""
        if user_input is not None:
            patterns = [p.strip() for p in user_input[CONF_IGNORE_PATTERNS] if p.strip()]
            return self.async_create_entry(data={CONF_IGNORE_PATTERNS: patterns})

        current = self.config_entry.options.get(CONF_IGNORE_PATTERNS, [])
        schema = vol.Schema(
            {
                vol.Optional(CONF_IGNORE_PATTERNS, default=current): TextSelector(
                    config={"multiple": True}
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)


class DeviceSubentryFlowHandler(ConfigSubentryFlow):
    """Edit an already-classified Device's name/aliases/options."""

    # Devices are created via repairs.py's classify flow, not async_step_user -
    # there's nothing to add before a device has transmitted at least once.
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing Device's name/aliases/options."""
        subentry = self._get_reconfigure_subentry()
        self._device_id = subentry.data[CONF_DEVICE_ID]
        if user_input is not None:
            data = dict(subentry.data)
            data.update(
                {
                    CONF_ALIASES: _split(user_input.get(CONF_ALIASES)),
                    CONF_GROUP_ALIASES: _split(user_input.get(CONF_GROUP_ALIASES)),
                    CONF_NOGROUP_ALIASES: _split(user_input.get(CONF_NOGROUP_ALIASES)),
                    CONF_FIRE_EVENT: user_input.get(CONF_FIRE_EVENT, False),
                    CONF_SIGNAL_REPETITIONS: user_input.get(CONF_SIGNAL_REPETITIONS),
                    CONF_UP_TIME: user_input.get(CONF_UP_TIME),
                    CONF_DOWN_TIME: user_input.get(CONF_DOWN_TIME),
                }
            )
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_NAME],
                data=data,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=subentry.title): str,
                vol.Optional(
                    CONF_ALIASES, default=", ".join(subentry.data.get(CONF_ALIASES, []))
                ): str,
                vol.Optional(
                    CONF_GROUP_ALIASES,
                    default=", ".join(subentry.data.get(CONF_GROUP_ALIASES, [])),
                ): str,
                vol.Optional(
                    CONF_NOGROUP_ALIASES,
                    default=", ".join(subentry.data.get(CONF_NOGROUP_ALIASES, [])),
                ): str,
                vol.Optional(
                    CONF_FIRE_EVENT, default=subentry.data.get(CONF_FIRE_EVENT, False)
                ): bool,
                vol.Optional(
                    CONF_SIGNAL_REPETITIONS,
                    default=_or_undefined(subentry.data.get(CONF_SIGNAL_REPETITIONS)),
                ): int,
                vol.Optional(
                    CONF_UP_TIME, default=_or_undefined(subentry.data.get(CONF_UP_TIME))
                ): vol.Coerce(float),
                vol.Optional(
                    CONF_DOWN_TIME,
                    default=_or_undefined(subentry.data.get(CONF_DOWN_TIME)),
                ): vol.Coerce(float),
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)


def _split(value: str | None) -> list[str]:
    """Split a comma-separated alias string into a clean list."""
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _or_undefined(value: Any) -> Any:
    """Map None to vol.UNDEFINED so an optional field has no stored default."""
    return vol.UNDEFINED if value is None else value
