"""Config flow for Blink Live View: its own Blink login, then the cameras.

The password is used for the sign-in only and dropped right after it; the PIN is
sent once and never kept. The entry stores the allow-listed tokens, never either.
"""

from collections.abc import Mapping
import logging
from typing import Any

from aiohttp import ClientError, ClientSession
from blinkpy.auth import Auth, BlinkTwoFARequiredError
from blinkpy.blinkpy import Blink
import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_PASSWORD, CONF_PIN, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import CONF_CAMERAS, DOMAIN
from .coordinator import BlinkLiveConfigEntry, stored_login_data

_LOGGER = logging.getLogger(__name__)

TITLE = "Blink Live View"

_LOGIN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)

_PIN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PIN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="one-time-code")
        )
    }
)


def _cameras_schema(api: Blink, selected: list[str]) -> vol.Schema:
    options = [
        SelectOptionDict(value=camera.serial, label=name)
        for name, camera in sorted(api.cameras.items())
    ]
    return vol.Schema(
        {
            vol.Required(CONF_CAMERAS, default=selected): SelectSelector(
                SelectSelectorConfig(options=options, multiple=True)
            )
        }
    )


class BlinkLiveConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in to Blink and choose the cameras."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._session: ClientSession | None = None
        self._blink: Blink | None = None

    async def _async_login(self, user_input: dict[str, Any]) -> ConfigFlowResult | str:
        """Sign in; return the next step, or an error key for the form."""
        login_data: dict[str, Any] = {
            CONF_USERNAME: user_input[CONF_USERNAME].strip(),
            CONF_PASSWORD: user_input[CONF_PASSWORD],
        }
        if self.source == SOURCE_REAUTH and (
            hardware_id := self._get_reauth_entry().data.get("hardware_id")
        ):
            # Our own id from the first login; blinkpy mints one otherwise.
            login_data["hardware_id"] = hardware_id
        if self._session is None:
            # Our own session, so our OAuth cookies never mix with core Blink's.
            self._session = async_create_clientsession(self.hass)
        auth = Auth(login_data, no_prompt=True, session=self._session)
        blink = Blink(session=self._session)
        blink.auth = auth
        self._blink = blink
        try:
            started = await blink.start()
        except BlinkTwoFARequiredError:
            return await self.async_step_2fa()
        except ClientError, TimeoutError:
            return "cannot_connect"
        finally:
            # The password is needed for this sign-in only.
            auth.data.pop(CONF_PASSWORD, None)
        if not started:
            return "invalid_auth"
        return await self._async_logged_in()

    async def _async_login_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        suggested: dict[str, Any] = {}
        if self.source == SOURCE_REAUTH and (
            username := self._get_reauth_entry().data.get(CONF_USERNAME)
        ):
            suggested[CONF_USERNAME] = username
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].strip().lower())
            if self.source == SOURCE_REAUTH:
                # An entry from 0.1.0 has no account yet; reauth gives it one.
                if self._get_reauth_entry().unique_id is not None:
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
            else:
                self._abort_if_unique_id_configured()
            try:
                result = await self._async_login(user_input)
            except Exception:
                _LOGGER.exception("Unexpected error during the Blink login")
                result = "unknown"
            if not isinstance(result, str):
                return result
            errors["base"] = result
            # Echo the username back, never the password.
            suggested[CONF_USERNAME] = user_input[CONF_USERNAME]
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(_LOGIN_SCHEMA, suggested),
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the Blink email and password."""
        return await self._async_login_step("user", user_input)

    async def async_step_2fa(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the PIN Blink sent by email or text."""
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._blink
            try:
                verified = await self._blink.send_2fa_code(user_input[CONF_PIN].strip())
            except BlinkTwoFARequiredError:
                verified = False
            except ClientError, TimeoutError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error while sending the Blink PIN")
                errors["base"] = "unknown"
            else:
                if verified:
                    return await self._async_logged_in()
            if not errors:
                errors["base"] = "invalid_pin"
        return self.async_show_form(
            step_id="2fa", data_schema=_PIN_SCHEMA, errors=errors
        )

    async def _async_logged_in(self) -> ConfigFlowResult:
        """Store the tokens on reauth, or go on to the cameras."""
        if self.source == SOURCE_REAUTH:
            assert self._blink
            data = stored_login_data(self._blink.auth)
            self._blink = None
            # Tokens only: the camera selection stays as it is.
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), unique_id=self.unique_id, data=data
            )
        return await self.async_step_cameras()

    async def async_step_cameras(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the cameras that get a live view."""
        assert self._blink
        if not self._blink.cameras:
            self._blink = None
            return self.async_abort(reason="no_cameras")
        if user_input is not None:
            data = stored_login_data(self._blink.auth)
            self._blink = None
            return self.async_create_entry(title=TITLE, data=data, options=user_input)
        return self.async_show_form(
            step_id="cameras", data_schema=_cameras_schema(self._blink, [])
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start a new login when Blink rejects the stored token."""
        _LOGGER.info("Blink rejected the stored token; reauthentication started")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password, and then the PIN, again."""
        return await self._async_login_step("reauth_confirm", user_input)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: BlinkLiveConfigEntry,
    ) -> OptionsFlowWithReload:
        """Return the options flow."""
        return BlinkLiveOptionsFlow()


class BlinkLiveOptionsFlow(OptionsFlowWithReload):
    """Change which cameras get a live stream; a change reloads the entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the cameras."""
        entry: BlinkLiveConfigEntry = self.config_entry
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_cameras_schema(
                entry.runtime_data.api, entry.options.get(CONF_CAMERAS, [])
            ),
        )
