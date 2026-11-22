"""CW alphabet, timing, tone generation and streaming discrimination."""

import re
from collections import deque
from statistics import median

import numpy as np

from .localization import Message

LATIN = dict(zip(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    ".- -... -.-. -.. . ..-. --. .... .. .--- -.- .-.. -- -. --- .--. --.- .-. ... - ..- ...- .-- -..- -.-- --.. "
    "----- .---- ..--- ...-- ....- ..... -.... --... ---.. ----.".split(),
))
RUSSIAN = dict(zip(
    "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ",
    ".- -... .-- --. -.. . ...- --.. .. .--- -.- .-.. -- -. --- .--. .-. ... - ..- ..-. .... -.-. ---. ---- --.- --.-- -.-- -..- ..-.. ..-- .-.-".split(),
))
COMMON = {key: LATIN[key] for key in "0123456789"} | {
    "/": "-..-.", "?": "..--..", "=": "-...-", "+": ".-.-.",
    ".": ".-.-.-", ",": "--..--", ":": "---...", "-": "-....-",
    "'": ".----.", "(": "-.--.", ")": "-.--.-", "@": ".--.-.",
}
PROSIGNS = {"<SK>": "...-.-", "<AR>": ".-.-.", "<BT>": "-...-", "<KN>": "-.--."}
ENCODE = LATIN | RUSSIAN | COMMON | PROSIGNS | {"Ё": "."}
DECODE = {
    "LAT": {code: char for char, code in (LATIN | COMMON).items()},
    "RUS": {code: char for char, code in (RUSSIAN | COMMON).items()},
}
for book in DECODE.values():
    book[PROSIGNS["<SK>"]] = "<SK>"

def expand_macro(template, call, other, rst):
    fields = {"CALL": call.strip().upper(), "OTHER": other.strip().upper(),
              "RST": rst.strip()}
    for name in re.findall(r"\{([^{}]+)\}", template):
        if name not in fields:
            raise ValueError(Message("Неизвестная подстановка {{{name}}}.", name=name))
        if not fields[name]:
            raise ValueError(Message("Заполните поле для {{{name}}}.", name=name))
    return re.sub(r"\{([^{}]+)\}", lambda match: fields[match[1]], template)


def encode_text(text):
    words = text.upper().split()
    if not words:
        raise ValueError("Введите текст для передачи.")
    tokens = [re.findall(r"<[^<>]+>|.", word) for word in words]
    unsupported = sorted({token for word in tokens for token in word} - ENCODE.keys())
    if unsupported:
        raise ValueError(Message("Нет кода для символов {characters}.", characters=" ".join(unsupported)))
    return [[ENCODE[token] for token in word] for word in tokens]


def keyed_segments(words):
    for word_index, word in enumerate(words):
        if word_index:
            yield False, 7
        for letter_index, letter in enumerate(word):
            if letter_index:
                yield False, 3
            for mark_index, mark in enumerate(letter):
                if mark_index:
                    yield False, 1
                yield True, 1 if mark == "." else 3


def waveform(words, rate, wpm, pitch, gain, max_seconds=60):
    segments = list(keyed_segments(words))
    unit = 1.2 / wpm
    duration = unit * sum(units for _, units in segments)
    if duration > max_seconds:
        raise ValueError(Message("Сообщение занимает {duration:.0f} с. Максимум {max_seconds} с.", duration=duration, max_seconds=max_seconds))
    result = np.zeros(round((duration + 0.09) * rate), dtype=np.float32)
    elapsed = 0
    for keyed, units in segments:
        start = round(elapsed * unit * rate)
        elapsed += units
        if not keyed:
            continue
        end = round(elapsed * unit * rate)
        tone = result[start:end]
        tone[:] = gain * np.sin((2 * np.pi * pitch / rate) * np.arange(len(tone)))
        ramp = min(round(0.004 * rate), len(tone) // 2)
        envelope = np.sin(np.linspace(0, np.pi / 2, ramp)) ** 2
        tone[:ramp] *= envelope
        tone[-ramp:] *= envelope[::-1]
    return result


class MorseTiming:
    """Classify keyed runs and delimit letters and words during a pause."""

    def __init__(self, alphabet, wpm, adaptive=True):
        self.codebook = DECODE[alphabet]
        self.dot = 1.2 / wpm
        self.adaptive = adaptive
        self.dot_estimates = deque(maxlen=7)
        self.on = False
        self.started = 0.0
        self.pattern = ""
        self.letter_written = False
        self.word_written = True

    def step(self, on, time):
        age = time - self.started
        result = ""
        if self.on and not on:
            if 0.43 * self.dot <= age <= 5.4 * self.dot:
                dash = age >= 1.9 * self.dot
                self.pattern += "-" if dash else "."
                candidate = age / (3 if dash else 1)
                if self.adaptive and 0.62 * self.dot <= candidate <= 1.80 * self.dot:
                    self.dot_estimates.append(candidate)
                    self.dot = min(0.20, max(0.028, 0.72 * self.dot + 0.28 * median(self.dot_estimates)))
            self.letter_written = False
            if self.pattern:
                self.word_written = False

        if not self.on:
            if age >= 1.8 * self.dot and self.pattern and not self.letter_written:
                result = self.codebook.get(self.pattern, "�")
                self.pattern = ""
                self.letter_written = True
            if age >= 4.5 * self.dot and self.letter_written and not self.word_written:
                result += " "
                self.word_written = True

        if self.on != on:
            self.started = time
            self.on = on
        return result


class CwBandpass:
    """Streaming Gaussian bandpass with a specified full -3 dB bandwidth."""

    def __init__(self, rate, pitch, bandwidth_hz):
        sigma = rate * np.sqrt(np.log(2)) / (np.pi * bandwidth_hz)
        radius = int(np.ceil(max(4 * sigma, rate * 0.006)))
        fft_size = 1 << (16 * radius).bit_length()
        frequencies = np.fft.rfftfreq(fft_size, d=1 / rate)
        # Build the positive-frequency response before mirroring. Adding two
        # Gaussian lobes instead would widen the lower edge near DC.
        response = np.exp(-0.5 * (2 * np.pi * sigma * (frequencies - pitch) / rate) ** 2)
        impulse = np.fft.irfft(response)
        taps = np.concatenate((impulse[-radius:], impulse[:radius + 1]))
        offsets = np.arange(-radius, radius + 1)
        carrier = np.cos(2 * np.pi * pitch * offsets / rate)
        self.taps = (taps / np.dot(taps, carrier)).astype(np.float32)
        self.history = np.zeros(2 * radius, dtype=np.float32)

    def feed(self, samples):
        if not len(samples):
            return samples
        block = np.concatenate((self.history, samples))
        self.history = block[-len(self.history):].copy()
        return np.convolve(block, self.taps, mode="valid")


class PitchTracker:
    """Follow the strongest stable keyed tone in a stream.

    The SDR's CW pitch is not reported over TCI and may differ from the value
    in the interface, so the decoder can lock onto the tone it hears instead.
    A stable peak well above the noise floor is required before switching.
    """

    def __init__(self, rate, low=300, high=1200, window_seconds=0.34, interval=0.2):
        size = 1 << max(10, int(np.ceil(np.log2(rate * window_seconds))))
        self.rate = rate
        self.buffer = np.zeros(size, dtype=np.float32)
        self.window = np.hanning(size).astype(np.float32)
        self.frequencies = np.fft.rfftfreq(size, 1.0 / rate)
        self.band = np.flatnonzero((self.frequencies >= low) & (self.frequencies <= high))
        self.hop = max(1, round(rate * interval))
        self.pending = np.empty(0, dtype=np.float32)
        self.candidates = []
        self.pitch = 0

    def feed(self, samples):
        if not len(samples):
            return self.pitch
        self.pending = np.concatenate((self.pending, samples))
        while len(self.pending) >= self.hop:
            chunk = self.pending[:self.hop]
            self.pending = self.pending[self.hop:]
            self.buffer[:-len(chunk)] = self.buffer[len(chunk):]
            self.buffer[-len(chunk):] = chunk
            frequency = self.detect()
            if frequency:
                self.consider(frequency)
        return self.pitch

    def detect(self):
        if not len(self.band):
            return 0.0
        spectrum = np.abs(np.fft.rfft(self.buffer * self.window))
        band = spectrum[self.band]
        position = int(np.argmax(band))
        level = float(band[position])
        if level < float(np.median(band)) * 20:
            return 0.0
        frequency = float(self.frequencies[self.band[position]])
        if 0 < position < len(band) - 1:
            left, right = float(band[position - 1]), float(band[position + 1])
            denominator = left - 2 * level + right
            if denominator:
                frequency += 0.5 * (left - right) / denominator * (self.rate / len(self.buffer))
        return frequency

    def consider(self, frequency):
        self.candidates.append(frequency)
        del self.candidates[:-6]
        if len(self.candidates) < 6 or max(self.candidates) - min(self.candidates) > 12:
            return
        pitch = round(float(np.median(self.candidates)))
        if abs(pitch - self.pitch) >= 5:
            self.pitch = pitch


class AudioSpectrum:
    """One row of the audio waterfall, about every 60 ms."""

    def __init__(self, rate, low=0, high=1600, bins=160, window_seconds=0.05, interval=0.06):
        self.rate = rate
        self.interval = interval
        self.last = 0.0
        size = 1 << max(9, int(round(np.log2(rate * window_seconds))))
        self.window = np.hanning(size).astype(np.float32)
        self.scale = 2.0 / self.window.sum()
        frequencies = np.fft.rfftfreq(size, d=1 / rate)
        edges = np.linspace(low, high, bins + 1)
        self.groups = [np.flatnonzero((frequencies >= start) & (frequencies < end))
                       for start, end in zip(edges[:-1], edges[1:])]
        self.buffer = np.empty(0, dtype=np.float32)

    def push(self, samples, now):
        if not len(samples):
            return None
        self.buffer = np.concatenate((self.buffer, samples))[-len(self.window):]
        if len(self.buffer) < len(self.window) or now - self.last < self.interval:
            return None
        self.last = now
        spectrum = np.abs(np.fft.rfft(self.buffer * self.window)) * self.scale
        values = np.empty(len(self.groups), dtype=np.float32)
        for index, group in enumerate(self.groups):
            values[index] = 20 * np.log10(max(float(spectrum[group].max()), 1e-6)) if len(group) else -120.0
        return values


class ToneDecoder:
    """Compare energy near the selected pitch with two nearby noise bands."""

    def __init__(self, rate, pitch, alphabet, wpm, sensitivity_db, adaptive=True, bandwidth_hz=0,
                 auto_gain=False):
        self.rate = rate
        self.pitch = pitch
        self.bandpass = CwBandpass(rate, pitch, bandwidth_hz) if bandwidth_hz else None
        self.hop = round(rate * 0.005)
        self.window_size = self.hop * (3 if 0 < bandwidth_hz <= 100 else 4)
        self.frame = np.zeros(self.window_size, dtype=np.float32)
        window = np.hanning(self.window_size)
        frequencies = pitch + np.array([-210, -150, -25, 0, 25, 150, 210])
        phase = 2 * np.pi * frequencies[:, None] * np.arange(self.window_size) / rate
        self.bank = np.vstack((np.cos(phase), np.sin(phase))) * (2 * window / window.sum())
        self.residual = np.empty(0, dtype=np.float32)
        self.timing = MorseTiming(alphabet, wpm, adaptive)
        self.threshold = 10 ** (sensitivity_db / 20)
        self.time_step = self.hop / rate
        self.steps = 0
        self.streak = 0
        self.key_down = False
        self.level = -100.0
        self.auto_gain = auto_gain
        self.peak = 0.0
        self.gain = 1.0
        self.noise_floor = 0.0
        self.peak_decay = float(np.exp(-self.time_step / 1.2))

    def feed(self, samples):
        if self.bandpass is not None:
            samples = self.bandpass.feed(samples)
        samples = np.concatenate((self.residual, samples))
        complete = len(samples) // self.hop * self.hop
        self.residual = samples[complete:].copy()
        result = []
        for offset in range(0, complete, self.hop):
            self.frame[:-self.hop] = self.frame[self.hop:]
            self.frame[-self.hop:] = samples[offset:offset + self.hop]
            channels = self.bank @ self.frame
            amplitudes = np.hypot(channels[:7], channels[7:])
            signal = float(amplitudes[2:5].max())
            guard = max(float(amplitudes[:2].max()), float(amplitudes[5:].max()))
            tone = self.detect_tone(signal, guard)
            self.steps += 1
            char = self.advance_key(tone)
            if char:
                result.append(char)
        return "".join(result)

    def detect_tone(self, signal, guard):
        self.level = 20 * np.log10(max(signal, 1e-5))
        if self.auto_gain:
            # Adjust from energy near the CW tone, so a broadband impulse
            # or an adjacent station does not set the gain for an entire block.
            self.peak *= self.peak_decay
            if signal >= guard * 2.0:
                self.peak = max(signal, self.peak)
            self.gain = min(100.0, max(1.0, 0.25 / max(self.peak, 0.0025)))
        # Estimate the floor quickly when a pause gets quieter and slowly
        # when its level rises. A key-down measurement must not raise it.
        if signal < self.noise_floor:
            self.noise_floor += 0.055 * (signal - self.noise_floor)
        elif not self.key_down and self.streak == 0:
            self.noise_floor += 0.015 * (signal - self.noise_floor)
        threshold = max(self.threshold / self.gain, 3.0 * self.noise_floor, 2.55 * guard)
        return signal >= threshold * (0.80 if self.key_down else 1.0)

    def advance_key(self, tone):
        now = self.steps * self.time_step
        if tone == self.key_down:
            self.streak = 0
            return self.timing.step(tone, now)
        self.streak += 1
        # Wait out very short clicks and fades, then date the confirmed
        # transition at its first frame to preserve the measured duration.
        span = self.streak * self.time_step
        required = max(0.010, min(0.025, self.timing.dot * (0.33 if self.key_down else 0.20)))
        if span + 1e-9 < required:
            return ""
        self.key_down = tone
        self.streak = 0
        return self.timing.step(tone, now - span + self.time_step)
