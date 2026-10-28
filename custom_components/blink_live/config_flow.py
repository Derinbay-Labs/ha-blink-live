"""Config flow for Blink Live View: pick the cameras that get a live stream."""

from typing import Any

from blinkpy.blinkpy import Blink
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from . import CONF_CAMERAS, DOMAIN, blink_api


def _schema(api: Blink, selected: list[str]) -> vol.Schema:
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
    """Create the single Blink Live View entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the cameras."""
        if (api := blink_api(self.hass)) is None:
            return self.async_abort(reason="blink_not_loaded")
        if user_input is not None:
            return self.async_create_entry(
                title="Blink Live View", data={}, options=user_input
            )
        return self.async_show_form(step_id="user", data_schema=_schema(api, []))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return BlinkLiveOptionsFlow()


class BlinkLiveOptionsFlow(OptionsFlow):
    """Change which cameras get a live stream."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the cameras."""
        if (api := blink_api(self.hass)) is None:
            return self.async_abort(reason="blink_not_loaded")
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(api, self.config_entry.options[CONF_CAMERAS]),
        )
