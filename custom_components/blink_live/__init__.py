"""Live view for Blink cameras.

The core Blink integration only shows the last snapshot. blinkpy can open the app's
live view; this integration logs in to Blink on its own, with its own blinkpy client,
and exposes that live view as a camera stream on its own devices.
"""

from copy import deepcopy
import logging

from blinkpy.auth import Auth
from blinkpy.blinkpy import Blink

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import PLATFORMS
from .coordinator import BlinkLiveConfigEntry, BlinkLiveCoordinator, stored_login_data

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: BlinkLiveConfigEntry) -> bool:
    """Log in with the stored tokens and set up the live-view cameras."""
    # Our own session, so our OAuth cookies never mix with core Blink's.
    session = async_create_clientsession(hass)
    blink = Blink(session=session)

    @callback
    def _tokens_refreshed() -> None:
        # blinkpy calls this after a token refresh on its request path.
        hass.config_entries.async_update_entry(
            entry, data=stored_login_data(blink.auth)
        )

    blink.auth = Auth(
        deepcopy(dict(entry.data)),
        no_prompt=True,
        session=session,
        callback=_tokens_refreshed,
    )
    coordinator = BlinkLiveCoordinator(hass, entry, blink)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.info("Blink Live View set up with %d cameras", len(blink.cameras))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BlinkLiveConfigEntry) -> bool:
    """Unload the live-view cameras."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
