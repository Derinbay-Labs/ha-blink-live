"""Tests for the live-view camera entity."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from custom_components.blink_live.camera import BlinkLiveCamera
from homeassistant.core import HomeAssistant


@pytest.fixture
def camera(hass: HomeAssistant, blink_api) -> Generator[BlinkLiveCamera]:
    """A live-view camera for the Blink camera G100."""
    entity = BlinkLiveCamera("G100", MagicMock())
    entity.hass = hass
    with patch("custom_components.blink_live.camera.blink_api", return_value=blink_api):
        yield entity


def _blink_camera(blink_api):
    return blink_api.cameras["Garden"]


@pytest.mark.parametrize(
    ("status", "online", "expected"),
    [("online", True, True), ("offline", False, False), (None, False, None)],
)
def test_online_attribute(camera, blink_api, status, online, expected) -> None:
    """Blink's status is passed through; a missing status is unknown, not offline."""
    _blink_camera(blink_api).status = status
    _blink_camera(blink_api).online = online
    assert camera.extra_state_attributes == {"online": expected}


def test_unavailable_when_blink_drops_the_camera(camera, blink_api) -> None:
    """The entity stays available between live views and goes away with the camera."""
    assert camera.available
    del blink_api.cameras["Garden"]
    assert not camera.available
    assert camera.extra_state_attributes == {"online": None}


def test_thumbnail_uses_the_cached_snapshot(camera, blink_api) -> None:
    """Thumbnails come from Blink's last snapshot and never start a live view."""
    _blink_camera(blink_api).image_from_cache = b"jpeg"
    assert camera.camera_image() == b"jpeg"
    _blink_camera(blink_api).init_livestream.assert_not_called()


async def test_stream_source_is_local(hass: HomeAssistant, camera) -> None:
    """The stream source is a loopback relay, known before any viewer connects."""
    with patch.object(BlinkLiveCamera, "async_refresh_providers"):
        await camera.async_added_to_hass()
    try:
        source = await camera.stream_source()
        assert source.startswith("tcp://127.0.0.1:")
    finally:
        await camera.async_will_remove_from_hass()
