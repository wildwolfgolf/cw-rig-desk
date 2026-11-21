"""Regression tests for soundless CAT and actual CW arriving over TCI."""

from contextlib import contextmanager
from queue import SimpleQueue
from threading import Event, Thread
from unittest import TestCase
from unittest.mock import patch

import numpy as np
from websockets.sync.server import serve

from cw_rig_desk.morse import encode_text, waveform
from cw_rig_desk.radio import receive_tci
from cw_rig_desk.tci_audio import HEADER, read_audio


@contextmanager
def fixture(peer):
    with serve(peer, "127.0.0.1", 0) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"ws://127.0.0.1:{server.socket.getsockname()[1]}"
        finally:
            server.shutdown()
            thread.join(2)


def packet(receiver, samples, *, fmt=3, channels=1, stream=1):
    return HEADER.pack(receiver, 8000, fmt, 0, 0, samples.size, stream, channels) + samples.tobytes()


SETTINGS = dict(pitch=700, alphabet="LAT", wpm=18, sensitivity_db=-34, bandwidth_hz=200)


class TciAudioTests(TestCase):
    def test_header_channel_and_receiver_validation(self):
        samples = np.array([8192, 0, -16384, 0], dtype="<i2")
        valid = packet(1, samples, fmt=0, channels=2)
        rate, mono, overflow = read_audio(valid, 1)
        self.assertEqual(rate, 8000)
        self.assertFalse(overflow)
        np.testing.assert_array_equal(mono, [0.25, -0.5])
        self.assertIsNone(read_audio(valid, 0))
        self.assertIsNone(read_audio(valid[:-1], 1))
        self.assertIsNone(read_audio(packet(1, samples, fmt=0, stream=0), 1))
        self.assertIsNone(read_audio(packet(1, np.array([np.nan], dtype="<f4")), 1))

    def test_start_decodes_binary_cw_and_stops_stream(self):
        phrase = "CQ TEST"
        signal = waveform(encode_text(phrase), 8000, 18, 700, 0.25)
        signal = np.pad(signal, (400, 2800)).astype("<f4")
        commands = []
        stopped = Event()
        cancel = Event()
        received = []

        def peer(ws):
            ws.send("protocol:ExpertSDR3,2.0;")
            ws.send("ready;")
            for command in ws:
                commands.append(command)
                if command == "audio_start:1;":
                    ws.send(packet(0, signal[:256]))
                    for i in range(0, len(signal), 256):
                        ws.send(packet(1, signal[i:i + 256]))
                elif command == "audio_stop:1;":
                    stopped.set()
                    return

        def report(name, value):
            received.append((name, value))
            if name == "text" and "".join(text for event, text in received if event == "text").strip() == phrase:
                cancel.set()

        with fixture(peer) as url:
            receive_tci((url, 1), SETTINGS.copy(), cancel, Event(), SimpleQueue(), report)
            self.assertTrue(stopped.wait(2))
        self.assertEqual(commands, ["audio_stream_sample_type:float32;", "audio_stream_channels:1;",
                                    "audio_start:1;", "audio_stop:1;"])
        self.assertEqual(received[0][0], "rx_started")
        self.assertEqual("".join(text for event, text in received if event == "text").strip(), phrase)

    def test_cat_ready_without_audio_is_reported(self):
        def peer(ws):
            ws.send("ready;")
            for _ in ws:
                pass

        with fixture(peer) as url, patch("cw_rig_desk.tci_audio.STREAM_TIMEOUT", 0.3):
            with self.assertRaisesRegex(ConnectionError, "Нет аудио RX по TCI"):
                receive_tci((url, 0), SETTINGS.copy(), Event(), Event(), SimpleQueue(), lambda *_: None)
