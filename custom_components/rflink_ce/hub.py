"""RFLink CE gateway connection and event dispatch."""

from __future__ import annotations

import asyncio
import logging
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_DEVICE_ID, CONF_HOST, CONF_PORT
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from rflink.parser import PACKET_FIELDS, PACKET_ID_SEP
from rflink.protocol import ProtocolBase, create_rflink_connection
from serial import SerialException

from .const import (
    CONF_ALIASES,
    CONF_IGNORE_PATTERNS,
    CONF_WAIT_FOR_ACK,
    DEFAULT_RECONNECT_INTERVAL,
    DEFAULT_WAIT_FOR_ACK,
    DOMAIN,
    EVENT_KEY_COMMAND,
    EVENT_KEY_ID,
    EVENT_KEY_SENSOR,
    EVENT_KEY_UNIT,
    EVENT_KEY_VALUE,
    ISSUE_ID_UNCLASSIFIED_DEVICE,
    SIGNAL_AVAILABILITY,
    SIGNAL_HANDLE_EVENT,
    SIGNAL_NEW_SENSOR_FIELD,
)
from .utils import identify_event_type

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

type RflinkCeConfigEntry = ConfigEntry["RflinkHub"]

# rflink synthesizes id = packet_id + "_" + field abbreviation per sensor
# field (rflink/parser.py:560,568); strip it so fields group under one Device.
_FIELD_ABBREV = {full: short for short, full in PACKET_FIELDS.items()}
_FIELD_ABBREV["update_time"] = "update_time"


def _base_device_id(event: dict[str, Any]) -> str:
    """Return the physical device's id, stripping the per-field suffix if any."""
    device_id = event[EVENT_KEY_ID]
    if EVENT_KEY_SENSOR not in event:
        return device_id
    abbrev = _FIELD_ABBREV.get(event[EVENT_KEY_SENSOR])
    suffix = f"{PACKET_ID_SEP}{abbrev}"
    if abbrev and device_id.endswith(suffix):
        return device_id[: -len(suffix)]
    return device_id


class RflinkHub:
    """Own the live connection to one RFLink gateway and dispatch RF Signals."""

    def __init__(self, hass: HomeAssistant, entry: RflinkCeConfigEntry) -> None:
        """Set up the hub, not yet connected."""
        self.hass = hass
        self.entry = entry
        self.protocol: ProtocolBase | None = None
        self.available = False
        self._known_sensor_fields: dict[str, set[str]] = {}
        self._transport: asyncio.BaseTransport | None = None
        self._unclassified_history: dict[str, dict[str, str]] = {}
        self._unclassified_sensor_events: dict[str, dict[str, dict[str, Any]]] = {}

    def subentry_for_device_id(self, device_id: str) -> ConfigSubentry | None:
        """Find the Device (subentry) that owns this RFLink device id, if classified."""
        for subentry in self.entry.subentries.values():
            data = subentry.data
            if device_id == data[CONF_DEVICE_ID] or device_id in data.get(
                CONF_ALIASES, []
            ):
                return subentry
        return None

    def is_ignored(self, device_id: str) -> bool:
        """Return True if device_id matches a configured Ignore Pattern."""
        patterns = self.entry.options.get(CONF_IGNORE_PATTERNS, [])
        return any(fnmatchcase(device_id, pattern) for pattern in patterns)

    async def async_connect(self) -> None:
        """Open the connection to the gateway, retrying on failure."""
        host = self.entry.data.get(CONF_HOST)
        port = self.entry.data[CONF_PORT]

        try:
            async with asyncio.timeout(30):
                transport, protocol = await create_rflink_connection(
                    port=port,
                    host=host,
                    event_callback=self._handle_event,
                    disconnect_callback=self._handle_disconnect,
                    loop=self.hass.loop,
                )
        except (SerialException, OSError, TimeoutError):
            _LOGGER.warning(
                "Error connecting to RFLink gateway, reconnecting in %s seconds",
                DEFAULT_RECONNECT_INTERVAL,
            )
            self._set_available(available=False)
            async_call_later(
                self.hass, DEFAULT_RECONNECT_INTERVAL, self._async_reconnect_job
            )
            return

        self._transport = transport
        self.protocol = protocol
        self._set_available(available=True)
        _LOGGER.debug("Connected to RFLink gateway")

    async def _async_reconnect_job(self, _now: Any) -> None:
        await self.async_connect()

    def _handle_disconnect(self, _exc: Exception | None = None) -> None:
        """Handle an unexpected disconnect by scheduling a reconnect."""
        self.protocol = None
        self._set_available(available=False)
        _LOGGER.warning("Disconnected from RFLink gateway, reconnecting")
        self.hass.async_create_task(self.async_connect(), eager_start=False)

    def _set_available(self, *, available: bool) -> None:
        self.available = available
        async_dispatcher_send(
            self.hass, SIGNAL_AVAILABILITY.format(self.entry.entry_id), available
        )

    async def async_shutdown(self) -> None:
        """Close the connection."""
        if self._transport is not None:
            self._transport.close()

    async def async_send_command(
        self, device_id: str, command: str, repetitions: int
    ) -> None:
        """Send a command for device_id, repeating as configured."""
        if self.protocol is None:
            msg = "Cannot send command, not connected"
            raise HomeAssistantError(msg)

        wait_for_ack = self.entry.data.get(CONF_WAIT_FOR_ACK, DEFAULT_WAIT_FOR_ACK)
        for _ in range(max(repetitions, 1)):
            if wait_for_ack:
                await self.protocol.send_command_ack(device_id, command)
            else:
                self.protocol.send_command(device_id, command)

    def _handle_event(self, event: dict[str, Any]) -> None:
        """Handle an incoming RF Signal from the gateway."""
        event_type = identify_event_type(event)
        if event_type == "unknown":
            return

        device_id = _base_device_id(event)
        subentry = self.subentry_for_device_id(device_id)

        if subentry is None:
            if not self.is_ignored(device_id):
                self._async_raise_unclassified_issue(device_id, event)
            return

        if event_type == EVENT_KEY_SENSOR:
            field = event[EVENT_KEY_SENSOR]
            fields = self._known_sensor_fields.setdefault(subentry.subentry_id, set())
            if field not in fields:
                fields.add(field)
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_NEW_SENSOR_FIELD.format(subentry.subentry_id),
                    event,
                )
                return

        async_dispatcher_send(
            self.hass,
            SIGNAL_HANDLE_EVENT.format(subentry.subentry_id, event_type),
            event,
        )

    def clear_unclassified_history(self, device_id: str) -> None:
        """Drop accumulated debug history once device_id is classified or ignored."""
        self._unclassified_history.pop(device_id, None)
        self._unclassified_sensor_events.pop(device_id, None)

    def seed_sensor_fields(self, device_id: str, subentry: ConfigSubentry) -> None:
        """Create entities now for every field already seen before classification."""
        for field, event in self._unclassified_sensor_events.get(device_id, {}).items():
            self._known_sensor_fields.setdefault(subentry.subentry_id, set()).add(field)
            async_dispatcher_send(
                self.hass, SIGNAL_NEW_SENSOR_FIELD.format(subentry.subentry_id), event
            )

    def _async_raise_unclassified_issue(
        self, device_id: str, event: dict[str, Any]
    ) -> None:
        """Raise (or refresh) the repair issue prompting classification of device_id."""
        # async_create_issue replaces data wholesale each call, so accumulate
        # per-field history here or earlier signals would be lost.
        history = self._unclassified_history.setdefault(device_id, {})
        if EVENT_KEY_SENSOR in event:
            field = event[EVENT_KEY_SENSOR]
            value = event.get(EVENT_KEY_VALUE)
            unit = event.get(EVENT_KEY_UNIT) or ""
            history[f"sensor:{field}"] = f"sensor: {field}  value: {value}{unit}"
            self._unclassified_sensor_events.setdefault(device_id, {})[field] = event
        elif EVENT_KEY_COMMAND in event:
            history["command"] = f"command: {event[EVENT_KEY_COMMAND]}"

        data: dict[str, str | int | float | None] = {
            "entry_id": self.entry.entry_id,
            "device_id": device_id,
            "raw_id": event[EVENT_KEY_ID],
            "history": "\n".join(history.values()),
        }
        if EVENT_KEY_COMMAND in event:
            data["command"] = event[EVENT_KEY_COMMAND]
        if EVENT_KEY_SENSOR in event:
            data["sensor"] = event[EVENT_KEY_SENSOR]
            data["value"] = event.get(EVENT_KEY_VALUE)
            data["unit"] = event.get(EVENT_KEY_UNIT)

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_ID_UNCLASSIFIED_DEVICE.format(self.entry.entry_id, device_id),
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="unclassified_device",
            translation_placeholders={"device_id": device_id},
            data=data,
        )
