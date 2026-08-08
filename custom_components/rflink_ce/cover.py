"""Support for RFLink CE cover devices."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from homeassistant.components.cover import (
    ATTR_CURRENT_POSITION,
    ATTR_POSITION,
    CoverEntity,
    CoverState,
)
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_DOWN_TIME,
    CONF_ENTITY_DOMAIN,
    CONF_UP_TIME,
    ENTITY_DOMAIN_COVER,
    SIGNAL_NEW_DEVICE,
    SUBENTRY_TYPE_DEVICE,
)
from .entity import RflinkCeEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigSubentry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .hub import RflinkCeConfigEntry

INVERT_COMMANDS = {"UP": "DOWN", "DOWN": "UP"}
POSITION_UPDATE_INTERVAL = 1.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RflinkCeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up RFLink CE covers from Devices classified as cover."""

    @callback
    def _add_if_cover(subentry: ConfigSubentry) -> None:
        if (
            subentry.subentry_type == SUBENTRY_TYPE_DEVICE
            and subentry.data[CONF_ENTITY_DOMAIN] == ENTITY_DOMAIN_COVER
        ):
            async_add_entities(
                [RflinkCeCover(entry, subentry)],
                config_subentry_id=subentry.subentry_id,
            )

    for subentry in entry.subentries.values():
        _add_if_cover(subentry)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_DEVICE.format(entry.entry_id), _add_if_cover
        )
    )


class RflinkCeCover(RflinkCeEntity, CoverEntity, RestoreEntity):
    """An RFLink CE Device classified as a cover."""

    def __init__(self, entry: RflinkCeConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize, reading the optional Cover Travel Profile from the Device."""
        super().__init__(entry, subentry)
        self._up_time: float | None = subentry.data.get(CONF_UP_TIME)
        self._down_time: float | None = (
            subentry.data.get(CONF_DOWN_TIME) or self._up_time
        )
        self._invert = bool(subentry.data.get("invert_commands"))
        self._state: bool | None = None
        self._position: int | None = None
        self._move_task: asyncio.Task[None] | None = None
        self._move_start = 0.0
        self._move_from = 0
        self._move_to = 0

    async def async_added_to_hass(self) -> None:
        """Restore state and, if tracked, position."""
        await super().async_added_to_hass()
        if (old_state := await self.async_get_last_state()) is not None:
            self._state = old_state.state == CoverState.OPEN
            if self._up_time is not None:
                self._position = old_state.attributes.get(ATTR_CURRENT_POSITION)
        if self._up_time is not None and self._position is None:
            self._position = 100 if self._state else 0

    def _handle_event(self, event: dict[str, Any]) -> None:
        """Track position when the physical remote (not HA) moves this cover."""
        # Never transmit here - that would re-broadcast a command a real remote
        # already sent.
        command = event["command"].lower()
        if command in ("on", "allon", "up"):
            self._state = True
            self.hass.async_create_task(
                self._async_start_move(100, send_stop=False), eager_start=False
            )
        elif command in ("off", "alloff", "down"):
            self._state = False
            self.hass.async_create_task(
                self._async_start_move(0, send_stop=False), eager_start=False
            )
        elif command == "stop":
            self._cancel_move()

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        if self._up_time is not None:
            return self.current_cover_position == 0
        return None if self._state is None else not self._state

    @property
    def current_cover_position(self) -> int | None:
        """Return the current position, estimated from elapsed travel time."""
        if self._up_time is None:
            return None
        if self._move_task is None:
            return self._position
        duration = self._up_time if self._move_to > self._move_from else self._down_time
        fraction = (
            min((time.monotonic() - self._move_start) / duration, 1) if duration else 1
        )
        return round(self._move_from + (self._move_to - self._move_from) * fraction)

    @property
    def assumed_state(self) -> bool:
        """Return True because covers can be stopped midway."""
        return True

    async def _async_send_raw(self, command: str) -> None:
        if self._invert:
            command = INVERT_COMMANDS.get(command, command)
        await self._async_send_command(command)

    async def async_open_cover(self, **_kwargs: Any) -> None:
        """Fully open the cover."""
        self._state = True
        await self._async_send_raw("UP")
        await self._async_start_move(100, send_stop=False)

    async def async_close_cover(self, **_kwargs: Any) -> None:
        """Fully close the cover."""
        self._state = False
        await self._async_send_raw("DOWN")
        await self._async_start_move(0, send_stop=False)

    async def async_stop_cover(self, **_kwargs: Any) -> None:
        """Stop the cover mid-move."""
        self._cancel_move()
        await self._async_send_raw("STOP")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position, timed from the current one."""
        if self._up_time is None:
            return
        target = kwargs[ATTR_POSITION]
        current = self.current_cover_position or 0
        if target == current:
            return
        self._state = target > 0
        await self._async_send_raw("UP" if target > current else "DOWN")
        await self._async_start_move(target, send_stop=True)

    async def _async_start_move(self, target: int, *, send_stop: bool) -> None:
        """Start tracking a move towards target position, stopping on arrival."""
        if self._up_time is None:
            return
        current = self.current_cover_position or 0
        self._cancel_move()
        if target == current:
            return
        self._move_from = current
        self._move_to = target
        self._move_start = time.monotonic()
        duration = (
            (self._up_time if target > current else self._down_time)
            * abs(target - current)
            / 100
        )
        self._move_task = self.hass.async_create_task(
            self._async_finish_move(duration, target, send_stop=send_stop),
            eager_start=False,
        )

    async def _async_finish_move(
        self, duration: float, target: int, *, send_stop: bool
    ) -> None:
        """Wait for the estimated travel time, pushing position updates as it moves."""
        elapsed = 0.0
        while elapsed < duration:
            step = min(POSITION_UPDATE_INTERVAL, duration - elapsed)
            await asyncio.sleep(step)
            elapsed += step
            self.async_write_ha_state()
        self._position = target
        self._move_task = None
        if send_stop:
            await self._async_send_raw("STOP")
        self.async_write_ha_state()

    def _cancel_move(self) -> None:
        """Cancel an in-progress timed move, freezing the estimated position."""
        if self._move_task:
            self._position = self.current_cover_position
            self._move_task.cancel()
            self._move_task = None
