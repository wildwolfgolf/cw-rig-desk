"""Receive-only TCI audio on its own WebSocket, independently of CAT."""

from contextlib import suppress
from struct import Struct
from time import monotonic

import numpy as np
import websocket

from .localization import Message

# TCI 2.0 section 3.4. Stream.length counts individual samples, not frames.
HEADER = Struct("<8I32x")
RX_AUDIO = 1
STREAM_TIMEOUT = 5.0


def read_audio(packet, receiver):
    if len(packet) < HEADER.size:
        return None
    source, rate, fmt, codec, _, length, stream, channels = HEADER.unpack_from(packet)
    # TCI 1.8 used stereo and left the channel field reserved.
    channels = channels or 2
    if (source != receiver or stream != RX_AUDIO or codec != 0 or not 8000 <= rate <= 192000
            or channels not in (1, 2) or not 0 < length <= 8192 or length % channels):
        return None
    data = memoryview(packet)[HEADER.size:]
    if fmt == 1:  # signed packed 24-bit little-endian PCM
        if len(data) < length * 3:
            return None
        octets = np.frombuffer(data, np.uint8, length * 3).reshape(-1, 3).astype(np.int32)
        values = octets[:, 0] | (octets[:, 1] << 8) | (octets[:, 2] << 16)
        samples = ((values ^ 0x800000) - 0x800000).astype(np.float32) / 8388608
    elif fmt in (0, 2, 3):
        dtype, scale = {0: ("<i2", 32768), 2: ("<i4", 2147483648), 3: ("<f4", 1)}[fmt]
        if len(data) < length * np.dtype(dtype).itemsize:
            return None
        samples = np.frombuffer(data, dtype, length).astype(np.float32) / scale
    else:
        return None
    # Match the sound-device path by taking the first channel.
    mono = samples[::channels]
    if not np.isfinite(mono).all():
        return None
    return rate, mono, False


def audio_blocks(url, receiver, stop, tx_active, report):
    ws = None
    requested = False
    received = False
    try:
        ws = websocket.create_connection(url, timeout=2, suppress_origin=True)
        ws.settimeout(0.15)
        deadline = monotonic() + STREAM_TIMEOUT
        while not stop.is_set():
            if requested and tx_active.is_set():
                deadline = monotonic() + STREAM_TIMEOUT
            if monotonic() >= deadline:
                raise ConnectionError("Нет аудио RX по TCI. Проверьте, что приёмник SDR запущен и сервер поддерживает аудио TCI.")
            try:
                packet = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if packet == "":
                raise ConnectionError("Сервер TCI закрыл соединение.")
            if not requested and isinstance(packet, str):
                if any(command.strip().lower() == "ready" for command in packet.split(";")):
                    ws.send("audio_stream_sample_type:float32;")
                    ws.send("audio_stream_channels:1;")
                    ws.send(f"audio_start:{receiver};")
                    requested = True
                    deadline = monotonic() + STREAM_TIMEOUT
            if requested and isinstance(packet, bytes):
                block = read_audio(packet, receiver)
                if block is None:
                    continue
                deadline = monotonic() + STREAM_TIMEOUT
                if not received:
                    report("rx_started", "")
                    received = True
                yield block
    except (websocket.WebSocketException, OSError) as error:
        if not stop.is_set():
            if isinstance(error, ConnectionError):
                raise
            raise ConnectionError(Message("Ошибка аудио TCI: {detail}", detail=str(error))) from error
    finally:
        if ws is not None:
            if requested:
                with suppress(websocket.WebSocketException, OSError):
                    ws.send(f"audio_stop:{receiver};")
            with suppress(websocket.WebSocketException, OSError):
                ws.close(timeout=0.2)
