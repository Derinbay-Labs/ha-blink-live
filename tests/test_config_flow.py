"""Tests for the config and options flows."""

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.blink_live import CONF_CAMERAS, DOMAIN
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


async def test_user_flow(hass: HomeAssistant, loaded_blink) -> None:
    """The form lists the Blink cameras by name and stores the selection."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    selector = result["data_schema"].schema[CONF_CAMERAS]
    assert [option["label"] for option in selector.config["options"]] == [
        "Front door",
        "Garden",
    ]

    with patch("custom_components.blink_live.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_CAMERAS: ["G100"]}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {}
    assert result["options"] == {CONF_CAMERAS: ["G100"]}


async def test_user_flow_without_blink(hass: HomeAssistant) -> None:
    """Setup stops when the core Blink integration is not loaded."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "blink_not_loaded"


async def test_single_instance(hass: HomeAssistant, loaded_blink) -> None:
    """A second entry is refused."""
    MockConfigEntry(domain=DOMAIN, options={CONF_CAMERAS: []}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow(hass: HomeAssistant, loaded_blink) -> None:
    """The options flow starts from the current selection and replaces it."""
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_CAMERAS: ["G100"]})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["data_schema"]({})[CONF_CAMERAS] == ["G100"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CAMERAS: ["G100", "F200"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_CAMERAS: ["G100", "F200"]}
