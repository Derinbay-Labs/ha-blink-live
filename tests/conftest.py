"""Shared fixtures: a mocked Blink account with sentinel secrets."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

from blinkpy.auth import Auth
from blinkpy.blinkpy import Blink
from blinkpy.helpers.constants import OAUTH_TOKEN_URL
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blink_live.const import CONF_CAMERAS, DOMAIN

USERNAME = "Owner@Example.com"
# Sentinels: none of these may ever reach a log record or the entry data.
PASSWORD = "sentinel-password-5f1c"
PIN = "731905"
TOKEN = "sentinel-token-a07e"
REFRESH_TOKEN = "sentinel-refresh-93bd"
NEW_TOKEN = "sentinel-new-token-41c2"
NEW_REFRESH_TOKEN = "sentinel-new-refresh-c88a"
HARDWARE_ID = "5B0A3C1E-6F7D-4E2A-9B8C-1D2E3F4A5B6C"
CORE_HARDWARE_ID = "0F1E2D3C-4B5A-4978-8695-A4B3C2D1E0F9"
SECRETS = (PASSWORD, PIN, TOKEN, REFRESH_TOKEN, NEW_TOKEN, NEW_REFRESH_TOKEN)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the integration from custom_components."""


@pytest.fixture(autouse=True)
def mock_http(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Never let a test reach the network; Blink answers only what a test mocks."""
    return aioclient_mock


def make_cameras() -> dict[str, MagicMock]:
    """Two Blink cameras, keyed by name as blinkpy does."""
    garden = MagicMock(serial="G100", status="online", online=True)
    garden.name = "Garden"
    front = MagicMock(serial="F200", status="online", online=True)
    front.name = "Front door"
    return {"Garden": garden, "Front door": front}


def logged_in(blink: Blink) -> None:
    """Set the state a successful blinkpy login leaves behind."""
    blink.auth.token = TOKEN
    blink.auth.refresh_token = REFRESH_TOKEN
    blink.auth.expires_in = 3600
    blink.auth.expiration_date = 4102444800.0
    blink.auth.host = "u011.immedia-semi.com"
    blink.auth.region_id = "u011"
    blink.auth.account_id = 1234
    blink.cameras = make_cameras()


@pytest.fixture
def entry_data() -> dict:
    """Entry data as a finished login stores it."""
    return {
        "username": USERNAME,
        "token": TOKEN,
        "expires_in": 3600,
        "expiration_date": 4102444800.0,
        "refresh_token": REFRESH_TOKEN,
        "host": "u011.immedia-semi.com",
        "region_id": "u011",
        "client_id": None,
        "account_id": 1234,
        "user_id": None,
        "hardware_id": HARDWARE_ID,
        "uid": "BlinkCamera_abc",
        "device_id": "Blinkpy",
    }


@pytest.fixture
def config_entry(hass, entry_data) -> MockConfigEntry:
    """A Blink Live View entry with the garden camera selected."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Blink Live View",
        unique_id=USERNAME.lower(),
        data=entry_data,
        options={CONF_CAMERAS: ["G100"]},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def token_endpoint(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Blink's token endpoint answering a refresh with new tokens."""
    aioclient_mock.post(
        OAUTH_TOKEN_URL,
        json={
            "access_token": NEW_TOKEN,
            "refresh_token": NEW_REFRESH_TOKEN,
            "expires_in": 14400,
        },
    )
    return aioclient_mock


@pytest.fixture
def blink_setup() -> Generator[dict[str, MagicMock]]:
    """blinkpy's setup after login, its sign-in and the relay listener, mocked out."""

    async def setup_post_verify(self: Blink) -> bool:
        self.cameras = make_cameras()
        self.available = True
        return True

    # The relay's loopback listener; the relay itself is tested in test_camera.
    relay = MagicMock(sockets=[MagicMock()])
    relay.sockets[0].getsockname.return_value = ("127.0.0.1", 40000)
    with (
        patch.object(Blink, "setup_urls") as setup_urls,
        patch.object(Blink, "get_homescreen", AsyncMock()) as homescreen,
        patch.object(
            Blink, "setup_post_verify", autospec=True, side_effect=setup_post_verify
        ) as post_verify,
        patch.object(Blink, "refresh", AsyncMock(return_value=True)) as refresh,
        patch.object(Auth, "startup", AsyncMock()) as startup,
        patch(
            "blinkpy.auth.Auth._oauth_login_flow", AsyncMock(return_value=False)
        ) as sign_in,
        patch(
            "custom_components.blink_live.camera.asyncio.start_server",
            AsyncMock(return_value=relay),
        ),
    ):
        yield {
            "setup_urls": setup_urls,
            "homescreen": homescreen,
            "post_verify": post_verify,
            "refresh": refresh,
            "startup": startup,
            "sign_in": sign_in,
        }
