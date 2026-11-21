"""Tests for the live view's frame reads."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.blink_live import livestream
from custom_components.blink_live.livestream import LiveStream, init_livestream

# Seven MPEG-TS packets, the size Blink sends.
PAYLOAD = b"\x47" + b"\x00" * 1315


def _frame(msgtype: int, payload: bytes) -> bytes:
    return bytes([msgtype]) + (1).to_bytes(4, "big") + len(payload).to_bytes(4, "big")


class _Client:
    """A stand-in for a client connected to blinkpy's server."""

    def __init__(self) -> None:
        self.data: list[bytes] = []

    def is_closing(self) -> bool:
        return False

    def write(self, data: bytes) -> None:
        self.data.append(data)

    async def drain(self) -> None:
        pass


async def _relay(chunks: list[bytes]) -> list[bytes]:
    """Feed the chunks to recv() one TCP write at a time; return what it relays."""

    async def blink(reader, writer):
        for chunk in chunks:
            writer.write(chunk)
            await writer.drain()
            await asyncio.sleep(0.05)
        writer.close()

    server = await asyncio.start_server(blink, "127.0.0.1", 0)
    live = LiveStream(
        MagicMock(),
        {"command_id": 1, "polling_interval": 15, "server": "immis://blink:443"},
    )
    client = _Client()
    live.clients.append(client)
    try:
        port = server.sockets[0].getsockname()[1]
        live.target_reader, live.target_writer = await asyncio.open_connection(
            "127.0.0.1", port
        )
        async with asyncio.timeout(5):
            await live.recv()
    finally:
        server.close()
        await server.wait_closed()
    return client.data


@pytest.mark.usefixtures("socket_enabled")
@pytest.mark.parametrize("split", [4, 9 + 114], ids=["header", "payload"])
async def test_a_split_frame_does_not_end_the_live_view(split) -> None:
    """A frame that arrives in two parts is relayed whole, and the next one too."""
    frame = _frame(0, PAYLOAD) + PAYLOAD
    data = await _relay([frame, frame[:split], frame[split:], frame])
    assert data == [PAYLOAD] * 3


@pytest.mark.usefixtures("socket_enabled")
async def test_only_video_frames_are_relayed_and_a_cut_frame_ends_it() -> None:
    """Non-video frames are skipped; a frame cut off by the end is not relayed."""
    video = _frame(0, PAYLOAD) + PAYLOAD
    other = _frame(0x12, b"\x00" * 24) + b"\x00" * 24
    data = await _relay([other, video, video[:100]])
    assert data == [PAYLOAD]


async def test_init_livestream_refuses_a_non_immis_server() -> None:
    """Only Blink's immis live view is supported, as in blinkpy."""
    with (
        patch.object(
            livestream.api,
            "request_camera_liveview",
            AsyncMock(return_value={"server": "rtsps://blink"}),
        ),
        pytest.raises(NotImplementedError),
    ):
        await init_livestream(MagicMock())


async def test_init_livestream_returns_the_live_stream() -> None:
    """The live view uses the whole-frame reader."""
    response = {"command_id": 7, "polling_interval": 15, "server": "immis://b:443"}
    camera = MagicMock()
    with patch.object(
        livestream.api, "request_camera_liveview", AsyncMock(return_value=response)
    ) as request:
        live = await init_livestream(camera)
    assert isinstance(live, LiveStream)
    assert live.command_id == 7
    request.assert_awaited_once_with(
        camera.sync.blink,
        camera.sync.network_id,
        camera.camera_id,
        camera_type=camera.camera_type,
    )
