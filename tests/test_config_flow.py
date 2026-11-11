"""Tests for the config, reauth and options flows."""

from collections.abc import Callable
import json
import logging
from typing import Any
from unittest.mock import AsyncMock, patch
import uuid

from aiohttp import ClientError
from blinkpy.auth import BlinkTwoFARequiredError
from blinkpy.blinkpy import Blink
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blink_live.const import CONF_CAMERAS, DOMAIN, ENTRY_DATA_KEYS
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import (
    CORE_HARDWARE_ID,
    HARDWARE_ID,
    PASSWORD,
    PIN,
    SECRETS,
    TOKEN,
    USERNAME,
    logged_in,
)

LOGIN = {"username": USERNAME, "password": PASSWORD}


def _start(result: Any = True, seen: list | None = None) -> Callable:
    """A Blink.start replacement: log in, fail, or ask for a PIN."""

    async def start(self: Blink) -> bool:
        if seen is not None:
            seen.append(dict(self.auth.data, hardware_id=self.auth.hardware_id))
        if isinstance(result, BaseException):
            raise result
        if result is True:
            logged_in(self)
        return result

    return start


def _send_pin(expected: str = PIN) -> Callable:
    async def send_2fa_code(self: Blink, code: str) -> bool:
        if code != expected:
            return False
        logged_in(self)
        return True

    return send_2fa_code


def _patch_start(**kwargs):
    return patch.object(Blink, "start", autospec=True, side_effect=_start(**kwargs))


def _patch_pin():
    return patch.object(Blink, "send_2fa_code", autospec=True, side_effect=_send_pin())


def _no_setup():
    return patch("custom_components.blink_live.async_setup_entry", return_value=True)


def _suggested(result: dict, key: str) -> Any:
    for marker in result["data_schema"].schema:
        if marker == key:
            return (marker.description or {}).get("suggested_value")
    raise KeyError(key)


async def _user_flow(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


def _assert_clean_entry_data(data: dict) -> None:
    assert set(data) <= set(ENTRY_DATA_KEYS)
    assert "password" not in data
    assert "pin" not in data
    dumped = json.dumps(dict(data))
    assert PASSWORD not in dumped
    assert PIN not in dumped


async def test_login_without_pin(hass: HomeAssistant) -> None:
    """Email and password, then cameras; only tokens are stored."""
    result = await _user_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    with _patch_start():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
    assert result["step_id"] == "cameras"
    selector = result["data_schema"].schema[CONF_CAMERAS]
    assert [option["label"] for option in selector.config["options"]] == [
        "Front door",
        "Garden",
    ]

    with _no_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CAMERAS: ["G100"]}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.unique_id == USERNAME.lower()
    assert entry.title == "Blink Live View"
    assert entry.options == {CONF_CAMERAS: ["G100"]}
    assert entry.data["token"] == TOKEN
    assert entry.data["username"] == USERNAME
    _assert_clean_entry_data(entry.data)


async def test_login_with_pin(hass: HomeAssistant) -> None:
    """Blink asks for a PIN; a wrong PIN shows invalid_pin; the right one goes on."""
    result = await _user_flow(hass)
    with _patch_start(result=BlinkTwoFARequiredError()), _patch_pin():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
        assert result["step_id"] == "2fa"
        flow = hass.config_entries.flow._progress[result["flow_id"]]
        # The password is gone as soon as the sign-in has run.
        assert "password" not in flow._blink.auth.data

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"pin": "000000"}
        )
        assert result["step_id"] == "2fa"
        assert result["errors"] == {"base": "invalid_pin"}

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"pin": PIN}
        )
    assert result["step_id"] == "cameras"
    with _no_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CAMERAS: ["G100", "F200"]}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    _assert_clean_entry_data(result["result"].data)
    # Nothing of the login is left on the finished flow.
    assert flow._blink is None


@pytest.mark.parametrize(
    ("start_result", "error"),
    [
        (False, "invalid_auth"),
        (ClientError(), "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
        (RuntimeError(), "unknown"),
    ],
)
async def test_login_errors(hass: HomeAssistant, start_result, error: str) -> None:
    """Errors re-show the form with the email, never the password."""
    result = await _user_flow(hass)
    with _patch_start(result=start_result):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": error}
    assert _suggested(result, "username") == USERNAME
    assert _suggested(result, "password") is None
    assert PASSWORD not in repr(result)


async def test_pin_cannot_connect(hass: HomeAssistant) -> None:
    """A connection error while sending the PIN keeps the PIN step."""
    result = await _user_flow(hass)
    with (
        _patch_start(result=BlinkTwoFARequiredError()),
        patch.object(Blink, "send_2fa_code", AsyncMock(side_effect=ClientError())),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"pin": PIN}
        )
    assert result["step_id"] == "2fa"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_password_field_is_a_password_selector(hass: HomeAssistant) -> None:
    """The password is typed into a password field; the PIN is a one-time code."""
    result = await _user_flow(hass)
    schema = {str(key): value for key, value in result["data_schema"].schema.items()}
    assert schema["password"].config["type"] == "password"
    assert schema["username"].config["type"] == "email"

    with _patch_start(result=BlinkTwoFARequiredError()):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
    schema = {str(key): value for key, value in result["data_schema"].schema.items()}
    assert schema["pin"].config["autocomplete"] == "one-time-code"


async def test_own_hardware_id(hass: HomeAssistant) -> None:
    """A new login gets its own hardware id, never core Blink's."""
    MockConfigEntry(
        domain="blink", data={"username": USERNAME, "hardware_id": CORE_HARDWARE_ID}
    ).add_to_hass(hass)
    seen: list = []
    result = await _user_flow(hass)
    with _patch_start(seen=seen):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
    with _no_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CAMERAS: ["G100"]}
        )
    hardware_id = result["result"].data["hardware_id"]
    assert hardware_id == seen[0]["hardware_id"]
    assert hardware_id != CORE_HARDWARE_ID
    uuid.UUID(hardware_id)


async def test_duplicate_account(hass: HomeAssistant, config_entry) -> None:
    """The same account, in any case, aborts before signing in."""
    result = await _user_flow(hass)
    with _patch_start() as start:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": USERNAME.upper(), "password": PASSWORD}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    start.assert_not_called()


async def test_account_without_cameras(hass: HomeAssistant) -> None:
    """An account with no cameras ends the flow."""

    async def start(self: Blink) -> bool:
        logged_in(self)
        self.cameras = {}
        return True

    result = await _user_flow(hass)
    with patch.object(Blink, "start", autospec=True, side_effect=start):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_cameras"


async def test_reauth(hass: HomeAssistant, config_entry) -> None:
    """Reauth logs in again with our stored hardware id and keeps the cameras."""
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    assert _suggested(result, "username") == USERNAME
    assert _suggested(result, "password") is None

    seen: list = []
    with (
        _patch_start(result=BlinkTwoFARequiredError(), seen=seen),
        _patch_pin(),
        _no_setup(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": USERNAME.lower(), "password": PASSWORD}
        )
        assert result["step_id"] == "2fa"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"pin": PIN}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert seen[0]["hardware_id"] == HARDWARE_ID
    assert config_entry.data["hardware_id"] == HARDWARE_ID
    assert config_entry.options == {CONF_CAMERAS: ["G100"]}
    _assert_clean_entry_data(config_entry.data)


async def test_reauth_wrong_account(hass: HomeAssistant, config_entry) -> None:
    """Reauth with another account aborts and leaves the entry untouched."""
    before = dict(config_entry.data)
    result = await config_entry.start_reauth_flow(hass)
    with _patch_start() as start:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "other@example.com", "password": PASSWORD}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    start.assert_not_called()
    assert dict(config_entry.data) == before


async def test_reauth_invalid_auth(hass: HomeAssistant, config_entry) -> None:
    """A wrong password on reauth shows invalid_auth."""
    result = await config_entry.start_reauth_flow(hass)
    with _patch_start(result=False):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_gives_a_0_1_0_entry_its_account(hass: HomeAssistant) -> None:
    """An entry from 0.1.0, with no account, takes the one that logs in."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={CONF_CAMERAS: ["G100"]})
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    with _patch_start(), _no_setup():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
    assert result["reason"] == "reauth_successful"
    assert entry.unique_id == USERNAME.lower()
    assert entry.data["token"] == TOKEN
    _assert_clean_entry_data(entry.data)


async def test_no_secret_in_logs(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    token_endpoint,
    blink_setup,
) -> None:
    """Login, PIN, setup and token refreshes log no password, PIN or token."""
    caplog.set_level(logging.DEBUG)
    result = await _user_flow(hass)
    with _patch_start(result=False):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
    with _patch_start(result=BlinkTwoFARequiredError()), _patch_pin():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], LOGIN
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"pin": "000000"}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"pin": PIN}
        )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CAMERAS: ["G100"]}
    )
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    # A refresh on blinkpy's request path, stored through its callback.
    entry.runtime_data.api.auth.callback()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert "Blink Live View set up" in caplog.text
    logged = caplog.text + "".join(repr(record.args) for record in caplog.records)
    for secret in SECRETS:
        assert secret not in logged


async def test_options_flow(
    hass: HomeAssistant, config_entry, token_endpoint, blink_setup
) -> None:
    """The options flow starts from the current selection and replaces it."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"]({})[CONF_CAMERAS] == ["G100"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CAMERAS: ["G100", "F200"]}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_CAMERAS: ["G100", "F200"]}
    assert config_entry.state is ConfigEntryState.LOADED


async def test_options_flow_not_loaded(hass: HomeAssistant, config_entry) -> None:
    """The options flow needs the entry's Blink client."""
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"
