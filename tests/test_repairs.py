"""Tests for the unclassified-device repair flow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rflink_ce.const import (
    CONF_ENTITY_DOMAIN,
    CONF_IGNORE_PATTERNS,
    DOMAIN,
    ENTITY_DOMAIN_COVER,
    ENTITY_DOMAIN_IGNORE,
    ENTITY_DOMAIN_SENSOR,
    ISSUE_ID_UNCLASSIFIED_DEVICE,
    SUBENTRY_TYPE_DEVICE,
)
from custom_components.rflink_ce.hub import RflinkHub
from custom_components.rflink_ce.repairs import (
    UnclassifiedDeviceRepairFlow,
    _format_debug_info,
    _suggest_domain,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    entry.runtime_data = RflinkHub(hass, entry)
    return entry


def _raise_issue(hass: HomeAssistant, entry: MockConfigEntry, device_id: str) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_ID_UNCLASSIFIED_DEVICE.format(entry.entry_id, device_id),
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="unclassified_device",
        translation_placeholders={"device_id": device_id},
        data={"entry_id": entry.entry_id, "device_id": device_id, "raw_id": device_id},
    )


async def _start_flow(
    hass: HomeAssistant, entry: MockConfigEntry, device_id: str, raw_data: dict
) -> UnclassifiedDeviceRepairFlow:
    _raise_issue(hass, entry, device_id)
    flow = UnclassifiedDeviceRepairFlow(
        entry_id=entry.entry_id, device_id=device_id, raw_data=raw_data
    )
    flow.hass = hass
    return flow


async def test_init_step_shows_form_with_suggested_domain(hass: HomeAssistant) -> None:
    """The form pre-fills a device type guessed from the raw signal."""
    entry = _entry(hass)
    flow = await _start_flow(
        hass, entry, "cover_1", {"raw_id": "motor_cover_1", "device_id": "cover_1"}
    )

    result = await flow.async_step_init()

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    schema_keys = {key.schema: key for key in result["data_schema"].schema}
    assert schema_keys[CONF_ENTITY_DOMAIN].default() == ENTITY_DOMAIN_COVER


async def test_classify_creates_subentry_and_drops_issue(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """Submitting the form with a device type creates the Device and drops the issue."""
    entry = _entry(hass)
    flow = await _start_flow(hass, entry, "device_1", {"device_id": "device_1"})

    result = await flow.async_step_init(
        {"name": "Kitchen Sensor", CONF_ENTITY_DOMAIN: ENTITY_DOMAIN_SENSOR}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentries = list(entry.subentries.values())
    assert len(subentries) == 1
    assert subentries[0].subentry_type == SUBENTRY_TYPE_DEVICE
    assert subentries[0].data[CONF_ENTITY_DOMAIN] == ENTITY_DOMAIN_SENSOR
    assert subentries[0].unique_id == "device_1"
    assert (
        issue_registry.async_get_issue(
            DOMAIN, ISSUE_ID_UNCLASSIFIED_DEVICE.format(entry.entry_id, "device_1")
        )
        is None
    )


async def test_classify_seeds_sensor_fields_seen_before_classification(
    hass: HomeAssistant,
) -> None:
    """Fields already reported before classification become entities immediately."""
    entry = _entry(hass)
    hub: RflinkHub = entry.runtime_data
    hub._async_raise_unclassified_issue(
        "device_1", {"id": "device_1_temp", "sensor": "temperature", "value": 21.0}
    )
    hub._async_raise_unclassified_issue(
        "device_1", {"id": "device_1_bat", "sensor": "battery", "value": "ok"}
    )

    flow = UnclassifiedDeviceRepairFlow(
        entry_id=entry.entry_id,
        device_id="device_1",
        raw_data={"device_id": "device_1"},
    )
    flow.hass = hass

    await flow.async_step_init(
        {"name": "Kitchen Sensor", CONF_ENTITY_DOMAIN: ENTITY_DOMAIN_SENSOR}
    )

    subentry_id = next(iter(entry.subentries))
    assert hub._known_sensor_fields[subentry_id] == {"temperature", "battery"}


async def test_classify_ignore_option_adds_pattern_and_creates_no_device(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """Picking 'ignore' as the device type ignores it instead of creating a Device."""
    entry = _entry(hass)
    flow = await _start_flow(hass, entry, "device_1", {"device_id": "device_1"})

    result = await flow.async_step_init(
        {"name": "device_1", CONF_ENTITY_DOMAIN: ENTITY_DOMAIN_IGNORE}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert not entry.subentries
    assert entry.options[CONF_IGNORE_PATTERNS] == ["device_1"]
    assert (
        issue_registry.async_get_issue(
            DOMAIN, ISSUE_ID_UNCLASSIFIED_DEVICE.format(entry.entry_id, "device_1")
        )
        is None
    )


async def test_init_step_aborts_if_gateway_removed(hass: HomeAssistant) -> None:
    """If the Gateway config entry was removed meanwhile, abort instead of erroring."""
    flow = UnclassifiedDeviceRepairFlow(
        entry_id="missing_entry",
        device_id="device_1",
        raw_data={"device_id": "device_1"},
    )
    flow.hass = hass

    result = await flow.async_step_init()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "gateway_removed"


def test_suggest_domain_from_raw_id_pattern() -> None:
    """A device id that looks like a cover/shutter is suggested as a cover."""
    assert _suggest_domain({"raw_id": "some_shutter_1"}) == ENTITY_DOMAIN_COVER
    assert _suggest_domain({"sensor": "temperature"}) == ENTITY_DOMAIN_SENSOR
    assert _suggest_domain({"raw_id": "unknown_1"}) is None


def test_format_debug_info_includes_history() -> None:
    """The debug block shown on the form includes the accumulated signal history."""
    info = _format_debug_info({"raw_id": "device_1", "history": "sensor: temperature"})
    assert "device_1" in info
    assert "sensor: temperature" in info
