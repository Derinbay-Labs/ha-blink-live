"""Blink live-view cameras.

Each entity listens on its own local TCP port and returns it as its stream source,
so asking for the source (HA does on boot and on every provider refresh) never
touches Blink. Only when a viewer (go2rtc) connects does the entity open a Blink
live view and relay its MPEG-TS stream; when the viewer leaves, the relay closes
and blinkpy ends the live view.
"""

import asyncio
import logging

from blinkpy.camera import BlinkCamera
from blinkpy.livestream import BlinkLiveStream

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import CONF_CAMERAS, blink_api, blink_entry

_LOGGER = logging.getLogger(__name__)

_CHUNK = 64 * 1024


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a live-view camera for each selected Blink camera."""
    if (blink := blink_entry(hass)) is None:
        return
    devices = dr.async_get(hass)
    async_add_entities(
        BlinkLiveCamera(serial, device)
        for serial in entry.options[CONF_CAMERAS]
        # The device the core Blink integration created for this camera.
        if (
            device := devices.async_get_device_by_identifier(
                ("blink", serial), blink.entry_id
            )
        )
    )


class BlinkLiveCamera(Camera):
    """A Blink camera whose stream is the app's live view."""

    _attr_has_entity_name = True
    _attr_translation_key = "live"
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, serial: str, device: dr.DeviceEntry) -> None:
        """Initialize the camera."""
        super().__init__()
        self._serial = serial
        self._attr_unique_id = f"{serial}-live"
        # Attach to the Blink device itself; a device info would create our own copy.
        self.device_entry = device
        self._server: asyncio.Server | None = None
        self._url: str | None = None
        self._live: BlinkLiveStream | None = None
        self._feed: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    def _blink_camera(self) -> BlinkCamera | None:
        # Looked up on each use: a reload of the Blink entry replaces its client.
        if api := blink_api(self.hass):
            for camera in api.cameras.values():
                if camera.serial == self._serial:
                    return camera
        return None

    async def async_added_to_hass(self) -> None:
        """Start listening for viewers."""
        await super().async_added_to_hass()
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self._url = f"tcp://127.0.0.1:{port}"
        # The providers were chosen before the source existed; choose again.
        await self.async_refresh_providers()

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening and end any live view."""
        if self._server:
            self._server.close()
        if self._live:
            self._live.stop()
        if self._feed:
            self._feed.cancel()
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        """Return True while the Blink integration knows the camera.

        Every Blink session ends after about 45 s, and the stream worker marks the
        stream down while it waits to reconnect. Camera.available would follow it,
        and the frontend cannot open an unavailable camera to start a new session.
        """
        return self._blink_camera() is not None

    @property
    def extra_state_attributes(self) -> dict[str, bool | None]:
        """Return whether Blink reports the camera online.

        None when Blink sends no status, which blinkpy would read as offline.
        """
        camera = self._blink_camera()
        if camera is None or camera.status is None:
            return {"online": None}
        return {"online": camera.online}

    async def stream_source(self) -> str | None:
        """Return the local relay; this never starts a live view."""
        return self._url

    def camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return Blink's last snapshot; thumbnails never start a live view."""
        camera = self._blink_camera()
        return camera.image_from_cache if camera else None

    async def _join_live(
        self,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Join the running live view, starting one if needed."""
        async with self._lock:
            live = self._live
            if not (live and live.is_serving):
                if (camera := self._blink_camera()) is None:
                    raise RuntimeError("camera not found in the Blink integration")
                live = await camera.init_livestream()
                await live.start()
                self._live = live
                self._feed = None
            host, port = live.socket.getsockname()[:2]
            # Join before the feed starts so the first keyframe is not missed.
            upstream = await asyncio.open_connection(host, port)
            if self._feed is None:
                self._feed = self.hass.async_create_background_task(
                    live.feed(), f"blink_live feed {self._serial}"
                )
                _LOGGER.debug("Live view started for %s", self.entity_id)
            return upstream

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Relay the live view to one connected viewer."""
        upstream_writer = None
        viewer_gone = None
        try:
            upstream_reader, upstream_writer = await self._join_live()
            viewer_gone = asyncio.ensure_future(reader.read())
            while True:
                chunk = asyncio.ensure_future(upstream_reader.read(_CHUNK))
                await asyncio.wait(
                    (chunk, viewer_gone), return_when=asyncio.FIRST_COMPLETED
                )
                if viewer_gone.done() or not (data := chunk.result()):
                    chunk.cancel()
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionError, OSError) as err:
            _LOGGER.debug("Live view relay for %s closed: %s", self.entity_id, err)
        except Exception:
            _LOGGER.exception("Could not start the live view for %s", self.entity_id)
        finally:
            if viewer_gone:
                viewer_gone.cancel()
            # Leaving the blinkpy server as its last client makes it end the live view.
            if upstream_writer:
                upstream_writer.close()
            writer.close()
            _LOGGER.debug("Viewer left %s", self.entity_id)
