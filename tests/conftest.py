"""Shared fixtures."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load the integration from custom_components."""


@pytest.fixture
def blink_api():
    """A blinkpy client with two cameras, as the core Blink entry would hold."""
    api = MagicMock()
    api.cameras = {
        "Garden": MagicMock(serial="G100"),
        "Front door": MagicMock(serial="F200"),
    }
    return api


@pytest.fixture
def loaded_blink(blink_api):
    """Make the core Blink entry look loaded."""
    with patch(
        "custom_components.blink_live.config_flow.blink_api", return_value=blink_api
    ):
        yield blink_api
