"""Tests for the cover's opening/closing state."""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

from homeassistant.components.cover import CoverState
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_DEVICE_ID
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rflink_ce.const import (
    CONF_UP_TIME,
    DOMAIN,
    ENTITY_DOMAIN_COVER,
    SUBENTRY_TYPE_DEVICE,
)
from custom_components.rflink_ce.cover import RflinkCeCover

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


class _Hub:
    available = True

    def __init__(self) -> None:
        self.commands: list[str] = []

    async def async_send_command(
        self, _device_id: str, command: str, _repetitions: int
    ) -> None:
        self.commands.append(command)


def _cover(hass: HomeAssistant, position: int = 0) -> RflinkCeCover:
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    entry.runtime_data = _Hub()
    subentry = ConfigSubentry(
        data=MappingProxyType(
            {
                CONF_DEVICE_ID: "device_1",
                "entity_domain": ENTITY_DOMAIN_COVER,
                CONF_UP_TIME: 10,
            }
        ),
        subentry_type=SUBENTRY_TYPE_DEVICE,
        title="device_1",
        unique_id="device_1",
    )
    cover = RflinkCeCover(entry, subentry)
    cover.hass = hass
    cover.entity_id = "cover.device_1"
    cover._attr_available = True
    cover._position = position
    return cover


async def test_toggle_stops_a_moving_cover(hass: HomeAssistant) -> None:
    """Toggle stops a moving cover, and the reported state follows the move."""
    cover = _cover(hass, position=50)
    await cover.async_open_cover()
    assert cover.is_opening
    assert not cover.is_closing
    assert hass.states.get("cover.device_1").state == CoverState.OPENING

    await cover.async_toggle()
    assert not cover.is_opening
    assert cover.entry.runtime_data.commands == ["UP", "STOP"]
    assert hass.states.get("cover.device_1").state == CoverState.OPEN

    open_cover = _cover(hass, position=100)
    await open_cover.async_close_cover()
    assert open_cover.is_closing
    assert not open_cover.is_opening
    assert hass.states.get("cover.device_1").state == CoverState.CLOSING
    open_cover._cancel_move()
