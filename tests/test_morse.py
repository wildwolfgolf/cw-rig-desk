import unittest

import numpy as np

from cw_rig_desk.morse import ToneDecoder, encode_text, waveform


class MorseTests(unittest.TestCase):
    def test_filtered_decode_at_48khz(self):
        rate = 48000
        expected = "CQ DE TEST 73"
        data = waveform(encode_text(expected), rate, 18, 700, .18)
        nearby = waveform(encode_text("VVV DE TEST"), rate, 20, 900, .35)
        samples = np.zeros(max(len(data), len(nearby)) + rate, dtype=np.float32)
        samples[:len(data)] += data
        samples[:len(nearby)] += nearby
        decoder = ToneDecoder(rate, 700, "LAT", 18, -34, bandwidth_hz=100)
        result = "".join(decoder.feed(samples[i:i + 1200]) for i in range(0, len(samples), 1200))
        self.assertEqual(result.strip(), expected)
