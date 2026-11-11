"""Blink live-view cameras.

Each entity listens on its own loopback TCP port and returns it as its stream source,
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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CAMERAS, DOMAIN
from .coordinator import BlinkLiveConfigEntry, BlinkLiveCoordinator

_LOGGER = logging.getLogger(__name__)

_CHUNK = 64 * 1024


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BlinkLiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add a live-view camera for each selected Blink camera."""
    coordinator = entry.runtime_data
    selected = set(entry.options.get(CONF_CAMERAS, []))
    async_add_entities(
        BlinkLiveCamera(coordinator, camera.serial, name)
        for name, camera in coordinator.api.cameras.items()
        if camera.serial in selected
    )


class BlinkLiveCamera(CoordinatorEntity[BlinkLiveCoordinator], Camera):
    """A Blink camera whose stream is the app's live view."""

    _attr_has_entity_name = True
    # The live view is the device's main feature: the entity takes the device name.
    _attr_name = None
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self, coordinator: BlinkLiveCoordinator, serial: str, camera_name: str
    ) -> None:
        """Initialize the camera."""
        super().__init__(coordinator)
        Camera.__init__(self)
        self._serial = serial
        self._attr_unique_id = f"{serial}-live"
        # Our own device, separate from the one core Blink creates for the camera.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            name=f"{camera_name} Live",
            manufacturer="Blink",
        )
        self._server: asyncio.Server | None = None
        self._url: str | None = None
        self._live: BlinkLiveStream | None = None
        self._feed: asyncio.Task | None = None
        self._viewer: asyncio.StreamWriter | None = None
        self._playing = False
        self._lock = asyncio.Lock()

    def _blink_camera(self) -> BlinkCamera | None:
        for camera in self.coordinator.api.cameras.values():
            if camera.serial == self._serial:
                return camera
        return None

    async def async_added_to_hass(self) -> None:
        """Start listening for viewers."""
        await super().async_added_to_hass()
        # Loopback only: the relay must never be reachable from the network.
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        self._url = f"tcp://127.0.0.1:{port}"
        # The providers were chosen before the source existed; choose again.
        await self.async_refresh_providers()

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening, drop the viewer and end any live view."""
        if self._server:
            self._server.close()
        if self._viewer:
            self._viewer.close()
        if self._live:
            self._live.stop()
        if self._feed:
            self._feed.cancel()
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        """Return True while the Blink account has the camera.

        Every Blink session ends after about 45 s, and the stream worker marks the
        stream down while it waits to reconnect. Camera.available would follow it,
        and the frontend cannot open an unavailable camera to start a new session.
        """
        return self._blink_camera() is not None

    @property
    def extra_state_attributes(self) -> dict[str, bool | None]:
        """Return whether Blink reports the camera online, and if video flows.

        online is None when Blink sends no status, which blinkpy would read as
        offline. live is True from the first relayed chunk until the viewer leaves.
        """
        camera = self._blink_camera()
        online = None if camera is None or camera.status is None else camera.online
        return {"online": online, "live": self._playing}

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
                    raise RuntimeError("camera not found on the Blink account")
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
                _LOGGER.info("Live view started for %s", self.entity_id)
            return upstream

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Relay the live view to the viewer; one viewer at a time."""
        if self._viewer is not None:
            _LOGGER.debug("Refused a second viewer for %s", self.entity_id)
            writer.close()
            return
        self._viewer = writer
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
                if not self._playing:
                    self._playing = True
                    self.async_write_ha_state()
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
            self._viewer = None
            if self._playing:
                self._playing = False
                self.async_write_ha_state()
            _LOGGER.info("Viewer left %s", self.entity_id)
