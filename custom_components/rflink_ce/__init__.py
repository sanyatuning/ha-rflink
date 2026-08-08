"""The RFLink CE integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .hub import RflinkHub

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .hub import RflinkCeConfigEntry

PLATFORMS = ["cover", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: RflinkCeConfigEntry) -> bool:
    """Set up an RFLink CE Gateway from a config entry."""
    _async_clear_stale_unclassified_issues(hass, entry.entry_id)

    hub = RflinkHub(hass, entry)
    entry.runtime_data = hub

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="RFLink",
    )

    await hub.async_connect()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def _async_clear_stale_unclassified_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Drop unclassified-device issues from a previous run of this Gateway."""
    registry = ir.async_get(hass)
    prefix = f"unclassified_device_{entry_id}_"
    for issue in list(registry.issues.values()):
        if issue.domain == DOMAIN and issue.issue_id.startswith(prefix):
            ir.async_delete_issue(hass, DOMAIN, issue.issue_id)


async def async_unload_entry(hass: HomeAssistant, entry: RflinkCeConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
