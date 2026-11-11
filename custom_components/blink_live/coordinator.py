"""The Blink client of a Blink Live View entry and its token handling.

blinkpy's own startup swallows a failed token refresh and falls back to a full
sign-in with the password, which this integration never stores. So the entry
refreshes its tokens itself and tells a token Blink rejects (reauth) from an
outage (retry later), and then runs the rest of blinkpy's setup.
"""

from datetime import timedelta
import logging
import time
from typing import Any
from urllib.parse import urlencode

from aiohttp import ClientError, ClientTimeout
from blinkpy.auth import (
    Auth,
    BlinkTwoFARequiredError,
    TokenRefreshFailed,
    UnauthorizedError,
)
from blinkpy.blinkpy import Blink, BlinkSetupError
from blinkpy.helpers.constants import (
    OAUTH_SCOPE,
    OAUTH_TOKEN_URL,
    OAUTH_TOKEN_USER_AGENT,
    OAUTH_V2_CLIENT_ID,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, ENTRY_DATA_KEYS

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=300)
# Refresh well before expiry, so blinkpy's request path never has to.
_REFRESH_MARGIN = 2 * SCAN_INTERVAL.total_seconds()
_TIMEOUT = ClientTimeout(total=30)

type BlinkLiveConfigEntry = ConfigEntry[BlinkLiveCoordinator]


class TokenRejected(Exception):
    """Blink rejected the refresh token; only a new login helps."""


class BlinkUnreachable(Exception):
    """Blink could not be reached or answered with a server error."""


def stored_login_data(auth: Auth) -> dict[str, Any]:
    """Return the allow-listed login state to keep in the config entry."""
    attributes = auth.login_attributes
    return {key: attributes[key] for key in ENTRY_DATA_KEYS if key in attributes}


async def async_refresh_tokens(auth: Auth) -> None:
    """Swap the refresh token for new tokens; never signs in with a password.

    Raises TokenRejected when Blink refuses the token (400/401) and
    BlinkUnreachable on a connection error, timeout or any other answer.
    """
    if not (auth.refresh_token and auth.hardware_id):
        raise TokenRejected
    form = {
        "grant_type": "refresh_token",
        "refresh_token": auth.refresh_token,
        "client_id": OAUTH_V2_CLIENT_ID,
        "scope": OAUTH_SCOPE,
        "hardware_id": auth.hardware_id,
    }
    headers = {
        "User-Agent": OAUTH_TOKEN_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
    }
    try:
        async with auth.session.post(
            OAUTH_TOKEN_URL, headers=headers, data=urlencode(form), timeout=_TIMEOUT
        ) as response:
            if response.status in (400, 401):
                raise TokenRejected
            if response.status != 200:
                raise BlinkUnreachable(f"HTTP {response.status}")
            token_data = await response.json()
        token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        expires_in = int(token_data.get("expires_in", 3600))
    except (ClientError, TimeoutError, ValueError, KeyError, TypeError) as err:
        # Only the class: a response body can carry tokens.
        raise BlinkUnreachable(type(err).__name__) from None
    auth.token = token
    auth.refresh_token = refresh_token
    auth.expires_in = expires_in
    auth.expiration_date = time.time() + expires_in


class BlinkLiveCoordinator(DataUpdateCoordinator[None]):
    """Keep the entry's own blinkpy client logged in and its cameras current."""

    config_entry: BlinkLiveConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: BlinkLiveConfigEntry, api: Blink
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.api = api

    def _store_tokens(self) -> None:
        # Writing data does not reload the entry: only an options change does.
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=stored_login_data(self.api.auth)
        )

    async def _async_setup(self) -> None:
        """Refresh the tokens, then run blinkpy's setup after its login step."""
        try:
            await async_refresh_tokens(self.api.auth)
        except TokenRejected as err:
            raise ConfigEntryAuthFailed("Blink rejected the stored token") from err
        except BlinkUnreachable as err:
            raise ConfigEntryNotReady("Blink cannot be reached") from err
        self._store_tokens()

        api = self.api
        try:
            api.setup_urls()
            await api.get_homescreen()
            if not api.last_refresh:
                # As Blink.start does: let the first refresh run straight away.
                api.last_refresh = int(time.time() - api.refresh_rate * 1.05)
            ready = await api.setup_post_verify()
        except (UnauthorizedError, BlinkTwoFARequiredError) as err:
            raise ConfigEntryAuthFailed("Blink rejected the token") from err
        except (BlinkSetupError, TokenRefreshFailed, ClientError, TimeoutError) as err:
            raise ConfigEntryNotReady("Blink setup failed") from err
        if not ready:
            raise ConfigEntryNotReady("Blink setup failed")

    async def _async_update_data(self) -> None:
        """Refresh tokens when they near expiry, then the camera data."""
        auth = self.api.auth
        expires = auth.expiration_date
        if expires is None or expires - time.time() < _REFRESH_MARGIN:
            try:
                await async_refresh_tokens(auth)
            except TokenRejected as err:
                raise ConfigEntryAuthFailed("Blink rejected the stored token") from err
            except BlinkUnreachable as err:
                raise UpdateFailed("Blink cannot be reached") from err
            self._store_tokens()
        try:
            await self.api.refresh()
        except (UnauthorizedError, BlinkTwoFARequiredError) as err:
            raise ConfigEntryAuthFailed("Blink rejected the token") from err
        except (TokenRefreshFailed, ClientError, TimeoutError) as err:
            raise UpdateFailed(type(err).__name__) from err
