"""Small helpers shared across RFLink CE modules."""

from __future__ import annotations

from .const import EVENT_KEY_COMMAND, EVENT_KEY_SENSOR


def identify_event_type(event: dict) -> str:
    """Return whether an incoming RFLink event is a command or a sensor reading."""
    if EVENT_KEY_COMMAND in event:
        return EVENT_KEY_COMMAND
    if EVENT_KEY_SENSOR in event:
        return EVENT_KEY_SENSOR
    return "unknown"
