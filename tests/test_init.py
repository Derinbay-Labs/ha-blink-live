"""Tests for setting up the integration."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blink_live import CONF_CAMERAS, DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant


async def test_retries_until_blink_is_loaded(hass: HomeAssistant) -> None:
    """The entry waits for the core Blink integration instead of failing."""
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_CAMERAS: ["G100"]})
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
