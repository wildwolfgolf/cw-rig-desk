"""Capture and play CW audio on the selected sound devices."""

from queue import Empty
import threading
import time

import numpy as np
from serial.tools import list_ports
import sounddevice as sd

from .morse import ToneDecoder, encode_text, waveform


def devices():
    hosts = sd.query_hostapis()
    inputs, outputs = {}, {}
    for index, device in enumerate(sd.query_devices()):
        host = hosts[device["hostapi"]]["name"]
        label = f'{device["name"]} · {host} [{index}]'
        rate = round(device["default_samplerate"])
        for direction, target in (("input", inputs), ("output", outputs)):
            if device[f"max_{direction}_channels"]:
                # Capture the first channel. Feed the same TX tone to both channels.
                target[label] = (index, rate, min(2, device[f"max_{direction}_channels"]))
    return inputs, outputs, [item.device for item in list_ports.comports()]


def receive(device, settings, stop, tx_active, filter_updates, report):
    index, rate, channels = device
    decoder = ToneDecoder(rate, **settings)
    last_report = 0.0
    with sd.InputStream(device=index, samplerate=rate, channels=channels, dtype="float32",
                        latency="low") as stream:
        report("rx_started", "")
        muted = False
        while not stop.is_set():
            samples, overflow = stream.read(round(rate * 0.025))
            if tx_active.is_set():
                muted = True
                continue
            bandwidth = settings["bandwidth_hz"]
            try:
                while True:
                    bandwidth = filter_updates.get_nowait()
            except Empty:
                pass
            if muted or overflow or bandwidth != settings["bandwidth_hz"]:
                settings["bandwidth_hz"] = bandwidth
                decoder = ToneDecoder(rate, **settings)
                muted = False
            text = decoder.feed(samples[:, 0])
            if text:
                report("text", text)
            now = time.monotonic()
            if now - last_report >= 0.1:
                report("meter", (decoder.level, 1.2 / decoder.timing.dot, decoder.key_down))
                last_report = now


def transmit(device, words, pitch, wpm, gain, lead, cancel, rig, telemetry, report):
    index, rate, channels = device
    audio = waveform(words, rate, wpm, pitch, gain)
    played = threading.Event()
    cursor = 0
    underrun = False

    def callback(outdata, frames, time_info, status):
        nonlocal cursor, underrun
        underrun |= bool(status.output_underflow)
        outdata.fill(0)
        if cancel.is_set():
            raise sd.CallbackAbort
        count = min(frames, len(audio) - cursor)
        outdata[:count, :] = audio[cursor:cursor + count, None]
        cursor += count
        if cursor == len(audio):
            raise sd.CallbackStop

    # Validate/open the exact audio output before attempting to assert PTT.
    with sd.OutputStream(device=index, samplerate=rate, channels=channels, dtype="float32",
                         latency="low", callback=callback, finished_callback=played.set) as stream:
        if cancel.is_set():
            return
        with rig.keyed(cancel) as keyed:
            if not keyed or cancel.wait(lead):
                return
            report("tx_phase", "Передача")
            try:
                stream.start()
                deadline = time.monotonic() + len(audio) / rate + 2.0
                while not played.wait(0.02):
                    if cancel.is_set():
                        return
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Аудиовыход перестал отвечать. Передача остановлена.")
                    telemetry()
            finally:
                if not played.is_set():
                    stream.abort(ignore_errors=False)
            if not cancel.is_set() and (underrun or cursor != len(audio)):
                raise RuntimeError("Сбой аудиовыхода. Сообщение могло передаться с пропусками.")


def demo(settings, report):
    rate = 8000
    rate_wpm = settings["wpm"]
    phrase = "CQ CQ DE TEST 5NN" if settings["alphabet"] == "LAT" else "ВНИМАНИЕ ТЕСТ 73"
    tone = waveform(encode_text(phrase), rate, rate_wpm, settings["pitch"], 0.28)
    noise = np.random.default_rng(42).normal(0, 0.025, len(tone) + rate // 2)
    noise = noise.astype(np.float32)
    noise[:len(tone)] += tone
    decoder = ToneDecoder(rate, **settings)
    result = "".join(decoder.feed(noise[i:i + 185]) for i in range(0, len(noise), 185))
    report("demo_text", (phrase, result.strip()))
