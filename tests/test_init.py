"""Tests for setup, token handling and devices."""

import json
from pathlib import Path
import time
from unittest.mock import patch
from urllib.parse import parse_qs

from aiohttp import ClientError
from blinkpy.helpers.constants import OAUTH_TOKEN_URL
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.blink_live.const import CONF_CAMERAS, DOMAIN, ENTRY_DATA_KEYS
import homeassistant.components.blink as core_blink
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import (
    CORE_HARDWARE_ID,
    HARDWARE_ID,
    NEW_REFRESH_TOKEN,
    NEW_TOKEN,
    PASSWORD,
    REFRESH_TOKEN,
)

MANIFEST = Path(__file__).parents[1] / "custom_components" / DOMAIN / "manifest.json"


def _reauth_flows(hass: HomeAssistant, entry: MockConfigEntry) -> list:
    return list(entry.async_get_active_flows(hass, {SOURCE_REAUTH}))


async def test_setup_refreshes_and_stores_tokens(
    hass: HomeAssistant, config_entry, token_endpoint, blink_setup
) -> None:
    """Setup swaps the stored refresh token for new tokens and keeps them."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.LOADED

    assert token_endpoint.call_count == 1
    form = parse_qs(token_endpoint.mock_calls[0][2])
    assert form["refresh_token"] == [REFRESH_TOKEN]
    assert form["hardware_id"] == [HARDWARE_ID]
    assert "password" not in form

    assert config_entry.data["token"] == NEW_TOKEN
    assert config_entry.data["refresh_token"] == NEW_REFRESH_TOKEN
    assert config_entry.data["hardware_id"] == HARDWARE_ID
    assert set(config_entry.data) <= set(ENTRY_DATA_KEYS)
    blink_setup["startup"].assert_not_called()
    blink_setup["sign_in"].assert_not_called()


async def test_setup_ignores_core_blink(
    hass: HomeAssistant, config_entry, token_endpoint, blink_setup
) -> None:
    """A core Blink entry is never read; its hardware id is never used."""
    MockConfigEntry(
        domain="blink",
        data={"username": "x", "hardware_id": CORE_HARDWARE_ID},
    ).add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    form = parse_qs(token_endpoint.mock_calls[0][2])
    assert form["hardware_id"] == [HARDWARE_ID]
    assert config_entry.data["hardware_id"] != CORE_HARDWARE_ID


@pytest.mark.parametrize("status", [400, 401])
async def test_rejected_token_starts_reauth(
    hass: HomeAssistant,
    config_entry,
    aioclient_mock: AiohttpClientMocker,
    blink_setup,
    status: int,
) -> None:
    """A token Blink rejects starts one reauth and never signs in again."""
    aioclient_mock.post(OAUTH_TOKEN_URL, status=status)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert len(_reauth_flows(hass, config_entry)) == 1
    assert aioclient_mock.call_count == 1
    blink_setup["startup"].assert_not_called()
    blink_setup["sign_in"].assert_not_called()


@pytest.mark.parametrize(
    "answer",
    [{"status": 500}, {"status": 503}, {"exc": ClientError()}, {"exc": TimeoutError()}],
)
async def test_outage_retries_without_reauth(
    hass: HomeAssistant,
    config_entry,
    aioclient_mock: AiohttpClientMocker,
    blink_setup,
    answer: dict,
) -> None:
    """A connection error, timeout or 5xx retries setup later and keeps the login."""
    aioclient_mock.post(OAUTH_TOKEN_URL, **answer)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    assert _reauth_flows(hass, config_entry) == []
    assert config_entry.data["refresh_token"] == REFRESH_TOKEN
    blink_setup["sign_in"].assert_not_called()


async def test_entry_from_0_1_0_asks_for_login(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, blink_setup
) -> None:
    """An entry without tokens asks for a login instead of calling Blink."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_CAMERAS: ["G100"]})
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert len(_reauth_flows(hass, entry)) == 1
    assert aioclient_mock.call_count == 0


async def _loaded(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_runtime_refresh_rejected_starts_reauth(
    hass: HomeAssistant,
    config_entry,
    token_endpoint: AiohttpClientMocker,
    blink_setup,
) -> None:
    """At runtime, a rejected token starts reauth once and never signs in."""
    await _loaded(hass, config_entry)
    coordinator = config_entry.runtime_data
    coordinator.api.auth.expiration_date = time.time() + 30
    token_endpoint.clear_requests()
    token_endpoint.post(OAUTH_TOKEN_URL, status=401)

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert token_endpoint.call_count == 1
    assert len(_reauth_flows(hass, config_entry)) == 1
    blink_setup["sign_in"].assert_not_called()


async def test_runtime_outage_does_not_reauth(
    hass: HomeAssistant,
    config_entry,
    token_endpoint: AiohttpClientMocker,
    blink_setup,
) -> None:
    """At runtime, a 5xx on the refresh is retried at the next update."""
    await _loaded(hass, config_entry)
    coordinator = config_entry.runtime_data
    coordinator.api.auth.expiration_date = time.time() + 30
    token_endpoint.clear_requests()
    token_endpoint.post(OAUTH_TOKEN_URL, status=502)

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert not coordinator.last_update_success
    assert _reauth_flows(hass, config_entry) == []
    assert config_entry.state is ConfigEntryState.LOADED


async def test_runtime_refresh_stores_tokens_without_reload(
    hass: HomeAssistant,
    config_entry,
    token_endpoint: AiohttpClientMocker,
    blink_setup,
) -> None:
    """Tokens near expiry are refreshed and stored; the entry is not reloaded."""
    await _loaded(hass, config_entry)
    coordinator = config_entry.runtime_data
    coordinator.api.auth.expiration_date = time.time() + 30
    token_endpoint.clear_requests()
    token_endpoint.post(
        OAUTH_TOKEN_URL,
        json={"access_token": "t2", "refresh_token": "r2", "expires_in": 14400},
    )
    with patch.object(hass.config_entries, "async_reload") as reload:
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert config_entry.data["refresh_token"] == "r2"
    reload.assert_not_called()
    assert config_entry.runtime_data is coordinator


async def test_blinkpy_callback_stores_tokens_without_reload(
    hass: HomeAssistant, config_entry, token_endpoint, blink_setup
) -> None:
    """A refresh on blinkpy's request path is stored through its callback."""
    await _loaded(hass, config_entry)
    auth = config_entry.runtime_data.api.auth
    auth.token = "cb-token"
    auth.refresh_token = "cb-refresh"
    # Auth.data can hold a password; it must never be copied to the entry.
    auth.data["password"] = PASSWORD
    with patch.object(hass.config_entries, "async_reload") as reload:
        auth.callback()
        await hass.async_block_till_done()

    assert config_entry.data["refresh_token"] == "cb-refresh"
    assert "password" not in config_entry.data
    assert PASSWORD not in json.dumps(dict(config_entry.data))
    reload.assert_not_called()


async def test_devices_are_our_own(
    hass: HomeAssistant, config_entry, token_endpoint, blink_setup
) -> None:
    """Each selected camera gets its own device, with no link to core Blink."""
    await _loaded(hass, config_entry)
    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), config_entry.entry_id
    )
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, "G100")}
    assert device.name == "Garden Live"
    assert device.via_device_id is None

    entities = er.async_entries_for_device(er.async_get(hass), device.id)
    assert [entity.unique_id for entity in entities] == ["G100-live"]
    assert hass.states.get(entities[0].entity_id) is not None


async def test_unload(
    hass: HomeAssistant, config_entry, token_endpoint, blink_setup
) -> None:
    """The entry unloads cleanly."""
    await _loaded(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


def test_manifest_requires_core_blinkpy() -> None:
    """The blinkpy minimum is core Blink's pin, and core Blink is no dependency."""
    ours = json.loads(MANIFEST.read_text(encoding="utf-8"))
    core = json.loads(
        (Path(core_blink.__file__).parent / "manifest.json").read_text(encoding="utf-8")
    )
    blinkpy = [req for req in core["requirements"] if req.startswith("blinkpy==")]
    assert ours["requirements"] == [req.replace("==", ">=") for req in blinkpy]
    assert "blink" not in ours["dependencies"]
    assert ours["version"] == "0.2.0"
