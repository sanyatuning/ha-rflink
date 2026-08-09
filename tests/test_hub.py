"""Tests for RflinkHub's unclassified-device tracking."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rflink_ce.const import (
    DOMAIN,
    EVENT_KEY_ID,
    EVENT_KEY_SENSOR,
    EVENT_KEY_UNIT,
    EVENT_KEY_VALUE,
    ISSUE_ID_UNCLASSIFIED_DEVICE,
    SIGNAL_NEW_SENSOR_FIELD,
    SUBENTRY_TYPE_DEVICE,
)
from custom_components.rflink_ce.hub import RflinkHub

if TYPE_CHECKING:
    from homeassistant.helpers import issue_registry as ir

TEMPERATURE_EVENT = {
    EVENT_KEY_ID: "device_1_temp",
    EVENT_KEY_SENSOR: "temperature",
    EVENT_KEY_VALUE: 21.0,
    EVENT_KEY_UNIT: "C",
}
BATTERY_EVENT = {
    EVENT_KEY_ID: "device_1_bat",
    EVENT_KEY_SENSOR: "battery",
    EVENT_KEY_VALUE: "ok",
}


def _hub(hass: HomeAssistant) -> RflinkHub:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    return RflinkHub(hass, entry)


def _new_subentry() -> ConfigSubentry:
    return ConfigSubentry(
        data=MappingProxyType({}),
        subentry_type=SUBENTRY_TYPE_DEVICE,
        title="device_1",
        unique_id="device_1",
    )


async def test_raise_unclassified_issue_accumulates_history(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """Every distinct field seen before classification is kept, not just the latest."""
    hub = _hub(hass)

    hub._async_raise_unclassified_issue("device_1", TEMPERATURE_EVENT)
    hub._async_raise_unclassified_issue("device_1", BATTERY_EVENT)

    issue = issue_registry.async_get_issue(
        DOMAIN, ISSUE_ID_UNCLASSIFIED_DEVICE.format(hub.entry.entry_id, "device_1")
    )
    assert issue is not None
    assert "temperature" in issue.data["history"]
    assert "battery" in issue.data["history"]
    # The issue payload itself only mirrors the most recent event.
    assert issue.data["sensor"] == "battery"


async def test_clear_unclassified_history_drops_cached_events(
    hass: HomeAssistant,
) -> None:
    """Clearing history drops both the display cache and the cached raw events."""
    hub = _hub(hass)
    hub._async_raise_unclassified_issue("device_1", TEMPERATURE_EVENT)

    hub.clear_unclassified_history("device_1")

    assert "device_1" not in hub._unclassified_history
    assert "device_1" not in hub._unclassified_sensor_events


async def test_seed_sensor_fields_creates_entities_immediately(
    hass: HomeAssistant,
) -> None:
    """Classifying a device seeds entities from signals seen before classification."""
    hub = _hub(hass)
    hub._async_raise_unclassified_issue("device_1", TEMPERATURE_EVENT)
    hub._async_raise_unclassified_issue("device_1", BATTERY_EVENT)
    subentry = _new_subentry()

    seen_fields: list[str] = []

    @callback
    def _on_field(event: dict) -> None:
        seen_fields.append(event[EVENT_KEY_SENSOR])

    async_dispatcher_connect(
        hass, SIGNAL_NEW_SENSOR_FIELD.format(subentry.subentry_id), _on_field
    )

    hub.seed_sensor_fields("device_1", subentry)
    await hass.async_block_till_done()

    assert set(seen_fields) == {"temperature", "battery"}
    assert hub._known_sensor_fields[subentry.subentry_id] == {"temperature", "battery"}


async def test_seed_sensor_fields_without_history_is_a_noop(
    hass: HomeAssistant,
) -> None:
    """A device with no cached signals seeds nothing."""
    hub = _hub(hass)
    subentry = _new_subentry()

    hub.seed_sensor_fields("device_1", subentry)

    assert subentry.subentry_id not in hub._known_sensor_fields
