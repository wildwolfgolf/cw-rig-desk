"""Serial CI-V transport, Xiegu G90 commands and telemetry."""

from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
import queue
import time

import serial

from .localization import Message, error_text

CAT_PC = 0xE0
MODES = {
    "LSB": (0x00, 0), "USB": (0x01, 0), "U-D": (0x01, 1), "L-D": (0x00, 1),
    "AM": (0x02, 0), "CW": (0x03, 0), "CWR": (0x07, 0), "NFM": (0x05, 0),
}
MODE_NAMES = {code: name for name, code in MODES.items()}


class CivError(RuntimeError):
    """The radio did not return the requested result."""


class CivRejected(CivError):
    pass


def bcd(data):
    digits = data.hex()
    if not digits or not digits.isdecimal():
        raise ValueError("Некорректное BCD-значение")
    return int(digits)


def frequency(data):
    if len(data) != 5:
        raise ValueError("Некорректная длина частоты")
    return bcd(data[::-1])


def frequency_field(hz):
    if not 500_000 <= hz <= 30_000_000:
        raise ValueError("Частота G90 должна быть от 500 000 до 30 000 000 Гц.")
    return bytes.fromhex(f"{hz:010d}")[::-1]


def mode_info(data, detailed):
    if (detailed and (len(data) != 3 or data[1] not in (0, 1))
            or not detailed and len(data) not in (1, 2)):
        raise ValueError("Некорректный ответ о режиме")
    mode = MODE_NAMES.get((data[0], data[1] if detailed else 0), f"0x{data[0]:02X}")
    return mode, data[-1] if len(data) > 1 else None


def byte(data):
    if len(data) != 1:
        raise ValueError("Ожидался один байт")
    return data[0]


def switch(data):
    return "Вкл" if byte(data) else "Выкл"


def raw_level(data):
    value = bcd(data)
    if len(data) not in (1, 2) or value > 255:
        raise ValueError("Значение вне шкалы 0–255")
    return value


def level_text(data):
    try:
        return str(raw_level(data))
    except ValueError:
        return data.hex(" ").upper() + " hex"


def rit_offset(data):
    if len(data) != 3 or data[2] not in (0, 1):
        raise ValueError("Некорректный ответ RIT")
    return f"{bcd(data[:2][::-1]) * (-1 if data[2] else 1):+d} Гц"


def frequency_edges(data):
    if len(data) != 11:
        raise ValueError("Некорректный ответ о диапазоне")
    return f"{frequency(data[:5]):,}–{frequency(data[6:]):,} Гц".replace(",", " ")


def swr_label(raw):
    # G90 points documented by flrig. Above 3:1, keep the raw value.
    points = ((0, 1.0), (48, 1.5), (80, 2.0), (120, 3.0))
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= raw <= x1:
            return f"{y0 + (raw - x0) * (y1 - y0) / (x1 - x0):.2f}:1"
    return "> 3:1"


class Civ:
    def __init__(self, port, address, report):
        self.address = address
        self.report = report
        self.port = serial.Serial(baudrate=19200, timeout=0.025, write_timeout=0.40)
        self.port.port = port
        self.port.rts = False
        self.port.dtr = False
        self.buffer = bytearray()
        self.frames = deque()

    def read(self, wait):
        waiting = self.port.in_waiting
        if not (waiting or wait):
            return
        self.buffer.extend(self.port.read(min(waiting, 4096) or 1))
        while 0xFD in self.buffer:
            end = self.buffer.index(0xFD)
            frame = bytes(self.buffer[:end + 1])
            del self.buffer[:end + 1]
            start = frame.rfind(b"\xfe\xfe")
            if start < 0 or len(frame) - start < 6:
                continue
            frame = frame[start:]
            target, source = frame[2:4]
            if source == CAT_PC and target == self.address:
                continue  # USB serial echo
            self.report("cat_frame", ("←", frame))
            if wait and target == CAT_PC and source == self.address:
                self.frames.append(frame[4:-1])
        if len(self.buffer) > 4096:
            del self.buffer[:-2]

    def exchange(self, payload, prefix=b"\xfb", data_size=0, timeout=0.55):
        self.read(wait=False)
        self.frames.clear()
        packet = bytes([0xFE, 0xFE, self.address, CAT_PC, *payload, 0xFD])
        self.port.write(packet)
        self.report("cat_frame", ("→", packet))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.read(wait=True)
            while self.frames:
                body = self.frames.popleft()
                if body == b"\xfa":
                    raise CivRejected("G90 отклонил команду CAT.")
                if body.startswith(prefix) and len(body) >= len(prefix) + data_size:
                    return body[len(prefix):]
        code = bytes(payload).hex(" ").upper()
        raise CivError(Message("Нет ответа G90 на команду CAT {code}.", code=code))

    def query(self, command, *, timeout=0.21):
        return self.exchange(command, command, 1, timeout)

    def require_usb(self):
        data = self.query(b"\x04", timeout=0.55)
        if mode_info(data, False)[0] != "USB":
            raise CivError("Для передачи выберите U-D или USB с INPUT = LINE.")

    def ptt(self, enabled):
        self.exchange((0x1C, 0x00, int(enabled)))

    @contextmanager
    def keyed(self, cancel):
        if not cancel.is_set():
            self.require_usb()
            try:
                already_tx = byte(self.query(b"\x1c\x00")) != 0
            except (CivError, ValueError):
                already_tx = False
            if already_tx:
                raise CivError("G90 уже находится в состоянии TX.")
        if cancel.is_set():
            yield False
            return
        try:
            self.ptt(True)
            self.report("cat_value", ("ptt", "TX · CAT"))
            yield True
        finally:
            for attempt in range(3):
                try:
                    self.ptt(False)
                    self.report("cat_value", ("ptt", "RX · CAT"))
                    break
                except (CivError, OSError) as error:
                    if attempt == 2:
                        self.report("cat_value", ("ptt", "Неизвестно"))
                        raise CivError("Снятие PTT не подтверждено. Проверьте состояние TX на G90.") from error

    def set_mode(self, name):
        code, data_mode = MODES[name]
        try:
            # Preserve the current filter group when switching operating mode.
            _, group = mode_info(self.query(b"\x26\x00"), True)
        except (CivError, ValueError):
            if data_mode:
                raise CivError("G90 не ответил на запрос режима DATA. Выберите U-D/L-D на трансивере.") from None
            self.exchange((0x06, code, 0x01))
        else:
            self.exchange((0x26, 0x00, code, data_mode, group if group in (1, 2, 3) else 1))


@dataclass(frozen=True)
class Reading:
    key: str
    label: str
    command: bytes
    interval: float
    decode: Callable[[bytes], object] = level_text


READINGS = (
    Reading("frequency", "Частота активного VFO", b"\x03", .35, frequency),
    Reading("mode", "Режим и группа фильтра", b"\x26\x00", .75, lambda data: mode_info(data, True)),
    Reading("ptt", "Состояние приём / передача", b"\x1c\x00", .35, lambda data: "TX" if byte(data) else "RX"),
    Reading("smeter", "S-метр · CAT", b"\x15\x02", .45, raw_level),
    Reading("po", "Прямая мощность · CAT", b"\x15\x11", .28, raw_level),
    Reading("swr", "КСВ · CAT", b"\x15\x12", .32, raw_level),
    Reading("alc", "ALC · CAT", b"\x15\x13", .55, raw_level),
    Reading("split", "SPLIT", b"\x0f", 2.5, switch),
    Reading("other_frequency", "Частота второго VFO", b"\x25\x01", 2.5, frequency),
    Reading("other_mode", "Режим второго VFO", b"\x26\x01", 3.0, lambda data: mode_info(data, True)[0]),
    Reading("limits", "Границы диапазона", b"\x02", 18.0, frequency_edges),
    Reading("sql_gate", "Шумоподавитель · состояние/уровень", b"\x15\x01", 4.0),
    Reading("volts", "Напряжение · шкала CAT", b"\x15\x15", 5.0, raw_level),
    Reading("att", "Аттенюатор ATT", b"\x11", 4.0, switch),
    Reading("pre", "Предусилитель PRE", b"\x16\x02", 4.0, switch),
    Reading("agc", "АРУ / AGC", b"\x16\x12", 4.0,
            lambda data: {0: "Выкл", 1: "Fast", 2: "Mid / Slow", 3: "Slow / Auto"}.get(byte(data), level_text(data))),
    Reading("nb", "Noise Blanker", b"\x16\x22", 4.0, switch),
    Reading("comp", "Компрессор", b"\x16\x44", 4.0, switch),
    Reading("lock", "Блокировка органов управления", b"\x16\x50", 4.0, switch),
    Reading("atu", "Антенный тюнер ATU", b"\x1c\x01", 3.0,
            lambda data: {0: "Выкл", 1: "Вкл", 2: "Настройка"}.get(byte(data), level_text(data))),
    Reading("rit_offset", "Сдвиг RIT", b"\x21\x00", 5.0, rit_offset),
    Reading("rit", "RIT", b"\x21\x01", 5.0, switch),
    Reading("xit", "XIT", b"\x21\x02", 5.0, switch),
    Reading("model", "Модель · код Xiegu", b"\x1d\x19", 30.0,
            lambda data: "G90 / G90S · 0090" if data == b"\x00\x90" else data.hex().upper()),
    Reading("civ_id", "Идентификатор CI-V", b"\x19\x00", 30.0, lambda data: data.hex().upper()),
    Reading("data_mode", "DATA · ответ совместимости", b"\x1a\x06", 5.0),
    *(Reading(key, label, bytes((0x14, code)), 6.0) for key, label, code in (
        ("af", "Громкость AF", 0x01), ("rf", "Усиление RF", 0x02),
        ("sql", "Порог SQL", 0x03), ("nr_level", "Уровень шумоподавления NR", 0x06),
        ("cw_tone", "Тон CW", 0x09), ("tx_power", "Заданная мощность TX", 0x0A),
        ("mic", "Усиление микрофона", 0x0B), ("cw_speed", "Скорость ключа CW", 0x0C),
        ("qsk", "Задержка QSK", 0x0F), ("nb_level", "Уровень NB", 0x12),
        ("moni", "Уровень MONI", 0x15), ("vox", "Усиление VOX", 0x16),
        ("anti_vox", "Уровень ANTI-VOX", 0x17), ("lcd", "Яркость дисплея", 0x19),
    )),
)
BY_KEY = {reading.key: reading for reading in READINGS}
TX_METERS = ("po", "swr", "alc")


class CatSession:
    def __init__(self, port, address, report):
        self.rig = Civ(port, address, self.handle_frame_event)
        self.port = port
        self.address = address
        self.report = report
        self.jobs = queue.Queue()
        self.values = {}
        self.due = {}
        self.frequency_failures = 0
        self.probe_mode_at = 0
        self.probe_data_at = 0
        self.swr_sample = None

    def handle_frame_event(self, event, data):
        if event == "cat_value":
            self.publish(*data)
        else:
            self.report(event, data)

    def publish(self, key, value):
        if key not in self.values or self.values[key] != value:
            self.values[key] = value
            self.report("cat_value", (key, value))

    def read_mode(self):
        if time.monotonic() >= self.probe_mode_at:
            try:
                return mode_info(self.rig.query(b"\x26\x00"), True)
            except (CivError, ValueError):
                self.probe_mode_at = time.monotonic() + 15
        mode, group = mode_info(self.rig.query(b"\x04"), False)
        if mode in ("USB", "LSB") and time.monotonic() >= self.probe_data_at:
            try:
                flag = self.rig.query(b"\x1a\x06")[0]
                if flag not in (0, 1):
                    raise ValueError("Неизвестный флаг DATA")
            except (CivError, ValueError):
                self.probe_data_at = time.monotonic() + 15
            else:
                if flag:
                    mode = "U-D" if mode == "USB" else "L-D"
        return mode, group

    def read_one(self, reading, own_tx=False):
        key = reading.key
        # In RX, zero RF is expected. Only interpret SWR when there is RF output.
        rf = self.values.get("po")
        if key in ("swr", "alc") and not (own_tx or self.values.get("ptt") == "TX" or rf):
            self.due[key] = time.monotonic() + reading.interval
            return
        if key == "smeter" and self.values.get("ptt") == "TX":
            self.publish(key, None)
            self.due[key] = time.monotonic() + reading.interval
            return
        try:
            value = (self.read_mode() if key == "mode" else
                     reading.decode(self.rig.query(reading.command, timeout=.12 if own_tx else .21)))
        except (CivError, ValueError) as error:
            if key == "frequency":
                self.frequency_failures += 1
                if self.frequency_failures == 3:
                    raise CivError("Связь с G90 потеряна. Проверьте DE-19 и COM-порт.") from None
            self.publish(key, None)
            delay = (reading.interval if key in ("frequency", "mode") or isinstance(error, ValueError)
                     else 12.0)
        else:
            delay = reading.interval
            if key == "frequency":
                self.frequency_failures = 0
            if key == "swr":
                self.publish(key, value if value or rf else None)
                if rf:
                    self.swr_sample = value
                    self.publish("swr_live", (swr_label(value), value))
            else:
                self.publish(key, value)
            if own_tx:
                delay = {"po": .10, "swr": .14, "alc": .30}[key]
        self.due[key] = time.monotonic() + delay

    def next_reading(self, keys, own_tx=False):
        if not own_tx and self.values.get("ptt") != "TX" and not self.values.get("po"):
            self.mark_last_swr()
        now = time.monotonic()
        if not own_tx and self.due["frequency"] <= now:
            self.read_one(BY_KEY["frequency"])
            return
        key = min(keys, key=self.due.__getitem__)
        if self.due[key] <= now:
            self.read_one(BY_KEY[key], own_tx)

    def mark_last_swr(self):
        if self.swr_sample is not None:
            raw = self.swr_sample
            self.publish("swr_live", (f"{swr_label(raw)} · посл.", raw))

    def write(self, name, value):
        if name == "frequency":
            self.rig.exchange(bytes([0x05]) + frequency_field(value))
            self.read_one(BY_KEY["frequency"])
            actual = self.values["frequency"]
            if actual != value:
                raise CivError("G90 не подтвердил запрошенную частоту при повторном чтении.")
        elif name == "mode":
            self.rig.set_mode(value)
            self.probe_mode_at = 0
            self.read_one(BY_KEY["mode"])
            actual = self.values["mode"]
            if not actual or actual[0] != value:
                raise CivError("G90 не подтвердил запрошенный режим при повторном чтении.")
        elif name == "vfo":
            self.rig.exchange((0x07, value))
            for key in ("frequency", "mode", "other_frequency", "other_mode"):
                self.due[key] = 0
        elif name == "split":
            self.rig.exchange((0x0F, int(value)))
            self.read_one(BY_KEY["split"])

    def run(self, stop):
        try:
            self.rig.port.open()
            hz = frequency(self.rig.query(b"\x03", timeout=.65))
            started = time.monotonic()
            self.due = {reading.key: started + i * .052 for i, reading in enumerate(READINGS)}
            self.due["frequency"] = started + .35
            self.report("cat_ready", f"{self.port} · CI-V {self.address:02X}")
            self.publish("frequency", hz)
            while not stop.is_set():
                try:
                    job, arguments = self.jobs.get(timeout=.022)
                except queue.Empty:
                    self.next_reading(BY_KEY)
                    self.rig.read(wait=False)
                    continue
                if job == "tx":
                    action, *args = arguments
                    try:
                        for key in TX_METERS:
                            self.due[key] = 0
                        self.publish("po", None)
                        self.publish("alc", None)
                        action(*args, self.rig, lambda: self.next_reading(TX_METERS, own_tx=True), self.report)
                    except Exception as error:
                        self.report("tx_done", error_text(error))
                    else:
                        self.report("tx_done", None)
                    finally:
                        self.mark_last_swr()
                        for key in ("ptt", *TX_METERS):
                            self.due[key] = 0
                else:
                    try:
                        self.write(job, arguments[0])
                    except (CivError, ValueError) as error:
                        self.report("cat_write_done", error_text(error))
                    else:
                        self.report("cat_write_done", None)
        finally:
            self.rig.port.close()
