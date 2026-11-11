"""Tests for the live-view camera entity and its loopback relay."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.blink_live.camera import BlinkLiveCamera
from custom_components.blink_live.const import DOMAIN
from homeassistant.core import HomeAssistant

from .conftest import make_cameras


@pytest.fixture
def coordinator() -> MagicMock:
    """A coordinator whose Blink client has two cameras."""
    coordinator = MagicMock()
    coordinator.api.cameras = make_cameras()
    return coordinator


@pytest.fixture
def camera(hass: HomeAssistant, coordinator) -> Generator[BlinkLiveCamera]:
    """A live-view camera for the Blink camera G100."""
    entity = BlinkLiveCamera(coordinator, "G100", "Garden")
    entity.hass = hass
    entity.entity_id = "camera.garden_live"
    yield entity


@pytest.fixture
async def listening(camera) -> AsyncGenerator[BlinkLiveCamera]:
    """The camera with its relay listening."""
    with patch.object(BlinkLiveCamera, "async_refresh_providers"):
        await camera.async_added_to_hass()
    yield camera
    await camera.async_will_remove_from_hass()


def _blink_camera(coordinator):
    return coordinator.api.cameras["Garden"]


def test_device_is_our_own(camera) -> None:
    """The entity sits on its own device, named after the camera, no via_device."""
    info = camera.device_info
    assert info["identifiers"] == {(DOMAIN, "G100")}
    assert info["name"] == "Garden Live"
    assert "via_device" not in info
    assert camera.unique_id == "G100-live"


@pytest.mark.parametrize(
    ("status", "online", "expected"),
    [("online", True, True), ("offline", False, False), (None, False, None)],
)
def test_online_attribute(camera, coordinator, status, online, expected) -> None:
    """Blink's status is passed through; a missing status is unknown, not offline."""
    _blink_camera(coordinator).status = status
    _blink_camera(coordinator).online = online
    assert camera.extra_state_attributes == {"online": expected}


def test_unavailable_when_blink_drops_the_camera(camera, coordinator) -> None:
    """The entity stays available between live views and goes away with the camera."""
    assert camera.available
    del coordinator.api.cameras["Garden"]
    assert not camera.available
    assert camera.extra_state_attributes == {"online": None}


def test_thumbnail_uses_the_cached_snapshot(camera, coordinator) -> None:
    """Thumbnails come from Blink's last snapshot and never start a live view."""
    _blink_camera(coordinator).image_from_cache = b"jpeg"
    assert camera.camera_image() == b"jpeg"
    _blink_camera(coordinator).init_livestream.assert_not_called()


@pytest.mark.usefixtures("socket_enabled")
async def test_relay_listens_on_loopback_only(listening) -> None:
    """The stream source is a loopback relay, known before any viewer connects."""
    source = await listening.stream_source()
    assert source.startswith("tcp://127.0.0.1:")
    assert listening._server.sockets[0].getsockname()[0] == "127.0.0.1"


async def _connect(camera: BlinkLiveCamera):
    port = camera._server.sockets[0].getsockname()[1]
    return await asyncio.open_connection("127.0.0.1", port)


async def _until(condition, timeout: float = 2) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.01)


@pytest.mark.usefixtures("socket_enabled")
async def test_one_viewer_at_a_time(listening) -> None:
    """A second viewer is closed while the first one watches."""
    release = asyncio.Event()

    async def join_live():
        await release.wait()
        raise ConnectionError

    with patch.object(listening, "_join_live", join_live):
        _, first = await _connect(listening)
        await _until(lambda: listening._viewer is not None)
        second_reader, second = await _connect(listening)
        async with asyncio.timeout(2):
            assert await second_reader.read() == b""
        second.close()
        release.set()
        await _until(lambda: listening._viewer is None)
        first.close()


@pytest.mark.usefixtures("socket_enabled")
async def test_relay_forwards_and_closes_when_viewer_leaves(
    listening, coordinator
) -> None:
    """Bytes come from blinkpy's address only; leaving closes the upstream side."""
    upstream_closed = asyncio.Event()

    async def blinkpy_side(reader, writer):
        writer.write(b"mpeg-ts")
        await writer.drain()
        await reader.read()
        upstream_closed.set()
        writer.close()

    upstream = await asyncio.start_server(blinkpy_side, "127.0.0.1", 0)
    live = MagicMock(is_serving=False, socket=upstream.sockets[0])
    live.start = AsyncMock()
    live.feed = AsyncMock()
    _blink_camera(coordinator).init_livestream = AsyncMock(return_value=live)
    try:
        reader, writer = await _connect(listening)
        async with asyncio.timeout(2):
            assert await reader.readexactly(7) == b"mpeg-ts"
        writer.close()
        async with asyncio.timeout(2):
            await upstream_closed.wait()
        await _until(lambda: listening._viewer is None)
    finally:
        upstream.close()
        await upstream.wait_closed()


@pytest.mark.usefixtures("socket_enabled")
async def test_removal_closes_listener_and_viewer(camera) -> None:
    """Removing the entity stops listening and drops the viewer."""
    release = asyncio.Event()

    async def join_live():
        await release.wait()
        raise ConnectionError

    with patch.object(BlinkLiveCamera, "async_refresh_providers"):
        await camera.async_added_to_hass()
    with patch.object(camera, "_join_live", join_live):
        reader, writer = await _connect(camera)
        await _until(lambda: camera._viewer is not None)
        await camera.async_will_remove_from_hass()
        assert not camera._server.is_serving()
        async with asyncio.timeout(2):
            assert await reader.read() == b""
        release.set()
        await _until(lambda: camera._viewer is None)
        writer.close()
