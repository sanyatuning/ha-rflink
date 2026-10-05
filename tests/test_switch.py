"""Tests for the Gateway's pairing mode switch."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import ATTR_ENTITY_ID, CONF_PORT
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rflink_ce.const import (
    CONF_IGNORE_PATTERNS,
    CONF_PAIRING_MODE,
    DOMAIN,
    EVENT_KEY_COMMAND,
    EVENT_KEY_ID,
    ISSUE_ID_UNCLASSIFIED_DEVICE,
)
from custom_components.rflink_ce.hub import RflinkHub

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

COMMAND_EVENT = {EVENT_KEY_ID: "device_1", EVENT_KEY_COMMAND: "on"}


async def _setup_gateway(
    hass: HomeAssistant, options: dict | None = None
) -> MockConfigEntry:
    """Set up a Gateway without opening a connection to it."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_PORT: "/dev/ttyUSB0"}, options=options or {}
    )
    entry.add_to_hass(hass)
    with patch.object(RflinkHub, "async_connect", new=AsyncMock()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _switch_entity_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Return the entity id of the Gateway's pairing mode switch."""
    entity_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_pairing_mode"
    )
    assert entity_id is not None
    return entity_id


def _issue_id(entry: MockConfigEntry, device_id: str) -> str:
    """Return the repair issue id used for an unclassified device."""
    return ISSUE_ID_UNCLASSIFIED_DEVICE.format(entry.entry_id, device_id)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_pairing_switch_sits_on_the_gateway_device_and_is_on_by_default(
    hass: HomeAssistant,
) -> None:
    """The switch belongs to the main Gateway device and starts enabled."""
    entry = await _setup_gateway(hass)

    state = hass.states.get(_switch_entity_id(hass, entry))
    assert state is not None
    assert state.state == "on"
    assert state.name == "Mock Title Pairing mode"

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    entity = er.async_get(hass).async_get(_switch_entity_id(hass, entry))
    assert device is not None
    assert entity is not None
    assert entity.device_id == device.id


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_turning_pairing_off_stops_new_repair_issues(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """While off, unknown devices raise no new issue and old ones are kept."""
    entry = await _setup_gateway(hass)
    hub: RflinkHub = entry.runtime_data
    switch_id = _switch_entity_id(hass, entry)

    # Detected while pairing mode is still on.
    hub._handle_event(COMMAND_EVENT)
    assert issue_registry.async_get_issue(DOMAIN, _issue_id(entry, "device_1"))

    await hass.services.async_call(
        "switch",
        "turn_off",
        {ATTR_ENTITY_ID: switch_id},
        blocking=True,
    )

    assert entry.options[CONF_PAIRING_MODE] is False
    assert hass.states.get(switch_id).state == "off"

    hub._handle_event({EVENT_KEY_ID: "device_2", EVENT_KEY_COMMAND: "on"})

    assert issue_registry.async_get_issue(DOMAIN, _issue_id(entry, "device_2")) is None
    # The issue raised earlier is untouched.
    assert issue_registry.async_get_issue(DOMAIN, _issue_id(entry, "device_1"))


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_turning_pairing_on_resumes_repair_issues(
    hass: HomeAssistant, issue_registry: ir.IssueRegistry
) -> None:
    """Turning the switch back on lets unknown devices raise issues again."""
    entry = await _setup_gateway(hass, options={CONF_PAIRING_MODE: False})
    hub: RflinkHub = entry.runtime_data
    switch_id = _switch_entity_id(hass, entry)

    assert hass.states.get(switch_id).state == "off"
    hub._handle_event(COMMAND_EVENT)
    assert issue_registry.async_get_issue(DOMAIN, _issue_id(entry, "device_1")) is None

    await hass.services.async_call(
        "switch",
        "turn_on",
        {ATTR_ENTITY_ID: switch_id},
        blocking=True,
    )

    assert entry.options[CONF_PAIRING_MODE] is True
    assert hass.states.get(switch_id).state == "on"
    hub._handle_event(COMMAND_EVENT)
    assert issue_registry.async_get_issue(DOMAIN, _issue_id(entry, "device_1"))


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_editing_ignore_patterns_keeps_pairing_mode(hass: HomeAssistant) -> None:
    """Saving Ignore Patterns must not reset the pairing mode switch."""
    entry = await _setup_gateway(hass, options={CONF_PAIRING_MODE: False})

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_IGNORE_PATTERNS: ["neighbor_*"]}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_IGNORE_PATTERNS] == ["neighbor_*"]
    assert entry.options[CONF_PAIRING_MODE] is False
