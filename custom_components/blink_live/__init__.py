"""Live view for Blink cameras, on top of the core Blink integration.

The core integration only shows the last snapshot. blinkpy, which it already ships,
can open the app's live view; this integration borrows the core entry's client and
exposes that live view as a camera stream.
"""

from blinkpy.blinkpy import Blink

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

DOMAIN = "blink_live"
CONF_CAMERAS = "cameras"
PLATFORMS = [Platform.CAMERA]


def blink_entry(hass: HomeAssistant) -> ConfigEntry | None:
    """Return the loaded core Blink entry."""
    for entry in hass.config_entries.async_entries("blink"):
        if entry.state is ConfigEntryState.LOADED:
            return entry
    return None


def blink_api(hass: HomeAssistant) -> Blink | None:
    """Return the blinkpy client of the loaded core Blink entry."""
    entry = blink_entry(hass)
    return entry.runtime_data.api if entry else None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the live-view cameras once the core Blink entry is loaded."""
    if blink_api(hass) is None:
        raise ConfigEntryNotReady("The Blink integration is not loaded")
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the live-view cameras."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
