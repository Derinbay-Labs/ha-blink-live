"""blinkpy's live view with whole-frame reads.

blinkpy 0.25.9 reads each IMMI frame with StreamReader.read(n), which returns what
has arrived so far. When Blink's TLS stream splits a frame, recv() takes the short
read for the end of the stream and ends the live view after a few seconds, logging
"Insufficient data for payload". blinkpy's dev branch reads with readexactly
(fronzbot/blinkpy#1232, #1304); this module carries that recv() until a blinkpy
release has it. Remove it then and call BlinkCamera.init_livestream again.
"""

import asyncio
import logging
import ssl

from blinkpy import api
from blinkpy.camera import BlinkCamera
from blinkpy.livestream import BlinkLiveStream

_LOGGER = logging.getLogger(__name__)


class LiveStream(BlinkLiveStream):
    """A blinkpy live view that waits for each frame to arrive whole."""

    async def recv(self) -> None:
        """Copy video frames from Blink to the clients; upstream dev's recv()."""
        try:
            while not self.target_reader.at_eof():
                try:
                    header = await self.target_reader.readexactly(9)
                except asyncio.IncompleteReadError as err:
                    _LOGGER.debug(
                        "Live view ended mid-header: %d of 9 bytes", len(err.partial)
                    )
                    break
                msgtype = header[0]
                payload_length = int.from_bytes(header[5:9], byteorder="big")
                if payload_length <= 0:
                    continue
                try:
                    data = await self.target_reader.readexactly(payload_length)
                except asyncio.IncompleteReadError as err:
                    _LOGGER.debug(
                        "Live view ended mid-frame: %d of %d bytes",
                        len(err.partial),
                        payload_length,
                    )
                    break
                # Only msgtype 0 carries video, as MPEG-TS packets (0x47).
                if msgtype != 0x00 or data[0] != 0x47:
                    continue
                for writer in self.clients:
                    if not writer.is_closing():
                        writer.write(data)
                        await writer.drain()
                await asyncio.sleep(0)
        except ssl.SSLError as err:
            if err.reason != "APPLICATION_DATA_AFTER_CLOSE_NOTIFY":
                _LOGGER.exception("TLS error while receiving the live view")
        except Exception:
            _LOGGER.exception("Error while receiving the live view")
        finally:
            # Closing the target ends send() and so the whole feed, as in blinkpy.
            self.target_writer.close()


async def init_livestream(camera: BlinkCamera) -> LiveStream:
    """Ask Blink for a live view of the camera; BlinkCamera.init_livestream's body."""
    response = await api.request_camera_liveview(
        camera.sync.blink,
        camera.sync.network_id,
        camera.camera_id,
        camera_type=camera.camera_type,
    )
    if not response["server"].startswith("immis://"):
        raise NotImplementedError(f"Unsupported: {response['server']}")
    return LiveStream(camera, response)
