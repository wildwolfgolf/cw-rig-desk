import unittest

import numpy as np

from cw_rig_desk.morse import AudioSpectrum, CwBandpass, PitchTracker, ToneDecoder, encode_text, waveform


class MorseTests(unittest.TestCase):
    def test_short_fades_do_not_split_cw_marks(self):
        rate = 8000
        expected = "CQ CQ DE SO5CW SO5CW 5NN 73"
        data = waveform(encode_text(expected), rate, 18, 700, 0.17)
        samples = np.pad(data, (3200, 6400))
        for start in range(4370, len(samples) - 200, 1073):
            samples[start:start + 144] *= 0.06  # 18 ms, shorter than an element gap
        decoder = ToneDecoder(rate, 700, "LAT", 18, -34)
        result = "".join(decoder.feed(samples[i:i + 193]) for i in range(0, len(samples), 193))
        self.assertEqual(result.strip(), expected)

    def test_tci_gain_and_decoding_are_independent_of_packet_size(self):
        rate = 8000
        expected = "CQ TEST"
        data = waveform(encode_text(expected), rate, 22, 700, 0.004)
        samples = np.pad(data, (400, rate // 2))
        samples[2035] += 0.8  # An impulse should not hold down gain for subsequent marks.
        for size in (173, 512, 2048):
            with self.subTest(size=size):
                decoder = ToneDecoder(rate, 700, "LAT", 22, -34, auto_gain=True)
                result = "".join(decoder.feed(samples[i:i + size]) for i in range(0, len(samples), size))
                self.assertEqual(result.strip(), expected)

    def test_auto_gain_rejects_noise_shaped_by_the_receiver(self):
        rate = 8000
        noise = np.random.default_rng(96).normal(0, 0.06, rate * 15).astype(np.float32)
        samples = CwBandpass(rate, 700, 220).feed(noise)
        decoder = ToneDecoder(rate, 700, "LAT", 18, -34, auto_gain=True)
        result = "".join(decoder.feed(samples[i:i + 193]) for i in range(0, len(samples), 193))
        self.assertEqual(result, "")

    def test_speed_tracking_accepts_cw_faster_than_initial_setting(self):
        rate = 8000
        expected = "CQ CQ DE SO5CW SO5CW 5NN 73"
        data = waveform(encode_text(expected), rate, 27, 700, 0.17)
        samples = np.pad(data, (3200, 6400))
        decoder = ToneDecoder(rate, 700, "LAT", 18, -34)
        result = "".join(decoder.feed(samples[i:i + 193]) for i in range(0, len(samples), 193))
        self.assertEqual(result.strip(), expected)

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

    def test_pitch_tracker_finds_the_keyed_tone(self):
        rate = 48000
        samples = waveform(encode_text("CQ TEST CQ TEST"), rate, 20, 600, 0.1).astype(np.float32)
        samples += np.random.default_rng(5).normal(0, 0.01, samples.size).astype(np.float32)
        tracker = PitchTracker(rate)
        for i in range(0, samples.size, 960):
            tracker.feed(samples[i:i + 960])
        self.assertAlmostEqual(tracker.pitch, 600, delta=5)

    def test_pitch_tracker_ignores_noise(self):
        tracker = PitchTracker(48000)
        samples = np.random.default_rng(9).normal(0, 0.05, 48000 * 5).astype(np.float32)
        for i in range(0, samples.size, 960):
            tracker.feed(samples[i:i + 960])
        self.assertEqual(tracker.pitch, 0)

    def test_auto_gain_decodes_a_quiet_stream(self):
        rate = 48000
        expected = "CQ TEST"
        data = waveform(encode_text(expected), rate, 18, 700, 0.004)
        noise = np.random.default_rng(2).normal(0, 0.001, data.size).astype(np.float32)
        samples = np.concatenate((data + noise, np.zeros(rate // 2, dtype=np.float32))).astype(np.float32)
        decoder = ToneDecoder(rate, 700, "LAT", 18, -34, auto_gain=True)
        result = "".join(decoder.feed(samples[i:i + 960]) for i in range(0, samples.size, 960))
        self.assertEqual(result.strip(), expected)
        self.assertLess(decoder.level, -30)

    def test_spectrum_reports_the_tone_frequency(self):
        rate = 48000
        time = np.arange(4096) / rate
        samples = (0.4 * np.sin(2 * np.pi * 600 * time)).astype(np.float32)
        spectrum = AudioSpectrum(rate)
        row = spectrum.push(samples, now=1.0)
        self.assertIsNotNone(row)
        self.assertEqual(row.size, 160)
        peak = int(np.argmax(row)) * 1600 / 160
        self.assertAlmostEqual(peak, 600, delta=20)
