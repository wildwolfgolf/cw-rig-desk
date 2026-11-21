"""CW alphabet, timing, tone generation and streaming discrimination."""

import re

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
        self.initial_dot = 1.2 / wpm
        self.dot = self.initial_dot
        self.adaptive = adaptive
        self.on = False
        self.started = 0.0
        self.pattern = ""
        self.letter_written = False
        self.word_written = True

    def step(self, on, time):
        age = time - self.started
        result = ""
        if self.on and not on:
            if 0.36 * self.dot <= age <= 5.4 * self.dot:
                dash = age >= 1.9 * self.dot
                self.pattern += "-" if dash else "."
                candidate = max(0, age - 0.005) / (3 if dash else 1)
                if self.adaptive and 0.65 * self.dot < candidate < 1.50 * self.dot:
                    self.dot = min(0.20, max(0.028, 0.84 * self.dot + 0.16 * candidate))
            self.letter_written = False
            if self.pattern:
                self.word_written = False

        if not self.on:
            if age >= 2.35 * self.dot and self.pattern and not self.letter_written:
                result = self.codebook.get(self.pattern, "�")
                self.pattern = ""
                self.letter_written = True
            if age >= 5.2 * self.dot and self.letter_written and not self.word_written:
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


class ToneDecoder:
    """Compare energy near the selected pitch with two nearby noise bands."""

    def __init__(self, rate, pitch, alphabet, wpm, sensitivity_db, adaptive=True, bandwidth_hz=0):
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
            self.level = 20 * np.log10(max(signal, 1e-5))
            # Hysteresis and two consecutive frames suppress short impulses.
            tone = signal >= max(self.threshold * (0.83 if self.key_down else 1),
                                 guard * (1.9 if self.key_down else 2.9))
            self.streak = self.streak + 1 if tone != self.key_down else 0
            if self.streak >= 2:
                self.key_down = tone
                self.streak = 0
            self.steps += 1
            char = self.timing.step(self.key_down, self.steps * self.time_step)
            if char:
                result.append(char)
        return "".join(result)
