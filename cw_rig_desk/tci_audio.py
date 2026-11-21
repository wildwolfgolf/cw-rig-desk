"""Receive-only TCI audio on its own WebSocket, independently of CAT."""

from contextlib import suppress
from struct import Struct
from time import monotonic

import numpy as np
import websocket

from .diagnostics import note
from .localization import Message

# 64-byte TCI stream header: receiver, rate, format, codec, crc, length,
# stream type, channels, then eight reserved words.
HEADER = Struct("<8I32x")
RX_AUDIO = 1
STREAM_TIMEOUT = 5.0
MAX_LENGTH = 16384
FORMATS = {0: ("<i2", 32768), 2: ("<i4", 2147483648), 3: ("<f4", 1)}


def read_audio(packet, receiver):
    if len(packet) < HEADER.size:
        return None
    source, rate, fmt, codec, _, length, stream, channels = HEADER.unpack_from(packet)
    # TCI 1.8 used stereo and left the channel field reserved.
    channels = channels or 2
    if (source != receiver or stream != RX_AUDIO or codec != 0 or not 8000 <= rate <= 192000
            or channels not in (1, 2) or not 0 < length <= MAX_LENGTH):
        return None
    data = memoryview(packet)[HEADER.size:]
    width = 3 if fmt == 1 else (2 if fmt == 0 else 4 if fmt in (2, 3) else 0)
    if not width:
        return None
    available = len(data) // width
    # TCI 1.4-1.8 (ExpertSDR2) stores the frame count in Stream.length, while
    # TCI 1.9+ counts every scalar sample across all channels. The payload size
    # distinguishes the two; misreading it drops every other half-packet and
    # makes CW timing impossible to decode.
    if available >= length * channels:
        total = length * channels
    elif available >= length:
        total = length
    else:
        return None
    if total % channels:
        return None
    if fmt == 1:  # signed packed 24-bit little-endian PCM
        octets = np.frombuffer(data, np.uint8, total * 3).reshape(-1, 3).astype(np.int32)
        values = octets[:, 0] | (octets[:, 1] << 8) | (octets[:, 2] << 16)
        samples = ((values ^ 0x800000) - 0x800000).astype(np.float32) / 8388608
    else:
        dtype, scale = FORMATS[fmt]
        samples = np.frombuffer(data, dtype, total).astype(np.float32) / scale
    # Match the sound-device path by taking the first channel.
    mono = samples[::channels]
    if not np.isfinite(mono).all():
        return None
    return rate, mono, False


def request_audio(ws, receiver):
    commands = ("audio_stream_sample_type:float32;", "audio_stream_channels:1;",
                f"audio_start:{receiver};")
    for command in commands:
        ws.send(command)
    note(f"sent {''.join(commands)}")


def audio_blocks(url, receiver, stop, tx_active, report):
    ws = None
    requested = False
    received = False
    packets = 0
    texts = 0
    last_note = 0.0
    try:
        ws = websocket.create_connection(url, timeout=2, suppress_origin=True)
        ws.settimeout(0.15)
        note(f"connected {url}, receiver {receiver}")
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
            if isinstance(packet, str):
                commands = {command.strip().lower() for command in packet.split(";")}
                if texts < 30:
                    note(f"server: {packet[:400]}")
                    texts += 1
                # A later "start" means the server restarted its DSP and dropped
                # the per-client audio subscription, so it has to be renewed.
                if "ready" in commands or (requested and "start" in commands):
                    request_audio(ws, receiver)
                    requested = True
                    deadline = monotonic() + STREAM_TIMEOUT
            if requested and isinstance(packet, bytes):
                if packets < 3:
                    source, rate, fmt, codec, _, length, stream, channels = HEADER.unpack_from(packet)
                    note("packet receiver={} rate={} format={} codec={} length={} type={} "
                         "channels={} payload={}".format(source, rate, fmt, codec, length, stream,
                                                        channels, len(packet) - HEADER.size))
                packets += 1
                block = read_audio(packet, receiver)
                if block is None:
                    if packets <= 3:
                        note("packet rejected by the validator")
                    continue
                now = monotonic()
                if now - last_note >= 5:
                    note(f"stream: {packets} packets, {block[0]} Hz, {len(block[1])} samples/packet")
                    last_note = now
                deadline = monotonic() + STREAM_TIMEOUT
                if not received:
                    report("rx_started", "")
                    received = True
                yield block
    except (websocket.WebSocketException, OSError) as error:
        if not stop.is_set():
            note(f"transport error: {error!r}")
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
            note("closed")
