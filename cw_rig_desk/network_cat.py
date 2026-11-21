"""Hamlib rigctld and ExpertSDR TCI control transports."""

from contextlib import contextmanager
import math
import queue
import socket
import time

PROFILES = ("Xiegu G90 · CI-V", "Hamlib · rigctld", "TCI · WebSocket")
STANDARD_MODES = ("LSB", "USB", "U-D", "L-D", "CW", "CWR", "AM", "NFM", "FM")
NETWORK_READINGS = (
    ("frequency", "Частота"), ("other_frequency", "Частота второго канала"),
    ("mode", "Режим"), ("ptt", "Приём / передача"), ("split", "SPLIT"),
    ("vfo", "Канал"), ("signal", "Уровень сигнала"), ("po", "Выходная мощность"),
    ("alc", "ALC"), ("swr_live", "КСВ"), ("device", "Устройство"),
)


class CommandError(RuntimeError):
    """The rig rejected a command or failed to confirm the requested value."""


def numeric(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("Некорректное число от трансивера.")
    return value


def state(text):
    if text.lower() in ("1", "true"):
        return True
    if text.lower() in ("0", "false"):
        return False
    raise ValueError("Некорректное состояние от трансивера.")


class Hamlib:
    mode_names = {"U-D": "PKTUSB", "L-D": "PKTLSB", "NFM": "FM"}

    def __init__(self, host, port, publish, log):
        self.host, self.port = host, port
        self.publish, self.log = publish, log
        self.sock = None
        self.buffer = bytearray()
        self.next_poll = 0.0
        self.optional_retry = {}
        self.meters = ("STRENGTH", "RFPOWER_METER_WATTS", "SWR", "ALC")
        self.meter_index = 0

    def open(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=2)
        self.sock.settimeout(0.65)
        self.buffer.clear()

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def request(self, command):
        message = "+\\" + command
        self.log("→", message)
        self.sock.sendall((message + "\n").encode("ascii"))
        values = {}
        deadline = time.monotonic() + 1.3
        while time.monotonic() < deadline:
            end = self.buffer.find(b"\n")
            if end < 0:
                packet = self.sock.recv(4096)
                if not packet:
                    raise ConnectionError("Соединение с rigctld закрыто.")
                self.buffer.extend(packet)
                if len(self.buffer) > 65536:
                    break
                continue
            line = bytes(self.buffer[:end]).decode("utf-8", errors="replace").strip()
            del self.buffer[:end + 1]
            self.log("←", line)
            if line.startswith("RPRT "):
                code = line[5:]
                if code != "0":
                    raise CommandError(f"Hamlib · {command}: RPRT {code}")
                return values
            key, sep, val = line.partition(":")
            if sep and key != command.split()[0]:
                values[key.strip().lower()] = val.strip()
            elif not sep and line:
                # Some rigctld versions emit get_level as an unlabelled value.
                values.setdefault("value", line)
        raise ConnectionError("Не удалось прочитать полный ответ rigctld.")

    def value(self, command):
        response = self.request(command)
        if not response:
            raise CommandError(f"Hamlib · {command}: пустой ответ.")
        return next(iter(response.values()))

    def frequency(self):
        return round(numeric(self.value("get_freq")))

    def get_mode(self):
        fields = self.request("get_mode")
        if "mode" not in fields:
            raise CommandError("Hamlib не сообщает режим.")
        mode = {"PKTUSB": "U-D", "PKTLSB": "L-D"}.get(fields["mode"], fields["mode"])
        width = fields.get("passband")
        self.publish("mode", (mode, f"{width} Гц" if width and width != "0" else None))
        return mode

    def get_ptt(self):
        enabled = int(self.value("get_ptt")) != 0
        self.publish("ptt", "TX" if enabled else "RX")
        return enabled

    def optional(self, command, action):
        if time.monotonic() < self.optional_retry.get(command, 0):
            return
        try:
            action()
        except (CommandError, ValueError):
            self.optional_retry[command] = time.monotonic() + 20

    def read_split(self):
        enabled = state(self.value("get_split_vfo"))
        self.publish("split", "Вкл" if enabled else "Выкл")
        return enabled

    def read_meter(self, name):
        value = numeric(self.value(f"get_level {name}"))
        if name == "STRENGTH":
            self.publish("smeter", round(max(0, min(255, (value + 54) * 2))))
            self.publish("signal", f"{value:+g} дБ от S9")
        elif name == "RFPOWER_METER_WATTS":
            self.publish("po", f"{value:g} Вт")
        elif name == "SWR" and value >= 1:
            self.publish("swr_live", (f"{value:.2f}:1", value))
        elif name == "ALC":
            self.publish("alc", f"{100 * value:g}%")

    def init_state(self, stop):
        self.publish("frequency", self.frequency())
        self.get_mode()
        self.optional("ptt", self.get_ptt)

    def sync(self, during_tx=False):
        now = time.monotonic()
        if now < self.next_poll:
            return
        self.next_poll = now + (0.35 if during_tx else 0.55)
        if not during_tx:
            self.publish("frequency", self.frequency())
            self.get_mode()
            self.optional("ptt", self.get_ptt)
            self.optional("split", self.read_split)
        tx_metrics = self.meters[1:]
        names = tx_metrics if during_tx else self.meters[:1]
        meter = names[self.meter_index % len(names)]
        self.meter_index += 1
        self.optional(meter, lambda: self.read_meter(meter))

    def write(self, key, value):
        if key == "frequency":
            self.request(f"set_freq {value}")
            observed = self.frequency()
            self.publish("frequency", observed)
            if observed != value:
                raise CommandError(f"Hamlib вернул частоту {observed} Гц.")
        elif key == "mode":
            self.request(f"set_mode {self.mode_names.get(value, value)} 0")
            self.get_mode()
        elif key == "vfo":
            selected = ("VFOA", "VFOB")[value]
            self.request(f"set_vfo {selected}")
            self.publish("vfo", selected)
            self.publish("frequency", self.frequency())
            self.get_mode()
        elif key == "split":
            current = self.value("get_vfo")
            if current not in ("VFOA", "VFOB"):
                raise CommandError("Hamlib не определил активный VFO A/B.")
            opposite = "VFOB" if current == "VFOA" else "VFOA"
            self.request(f"set_split_vfo {int(value)} {opposite if value else current}")
            self.read_split()

    def check_tx(self):
        if self.get_mode() not in ("USB", "U-D"):
            raise CommandError("Для аудиопередачи выберите USB или USB DATA и вход звука от ПК.")
        if self.get_ptt():
            raise CommandError("Трансивер уже в TX.")
        try:
            split = self.read_split()
        except CommandError:
            # Some rigctld backends cannot read split. The operator sets it on the radio.
            split = False
        if split:
            raise CommandError("Для аудиопередачи отключите SPLIT.")

    def ptt(self, enabled):
        self.request(f"set_ptt {int(enabled)}")
        if self.get_ptt() != enabled:
            raise CommandError("Hamlib не подтвердил состояние PTT.")

    def recover(self):
        self.close()
        self.open()


class Tci:
    mode_names = {"U-D": "DIGU", "L-D": "DIGL", "FM": "NFM"}

    def __init__(self, url, receiver, publish, log):
        self.url, self.receiver = url, str(receiver)
        self.publish, self.log = publish, log
        self.ws = None
        self.channel = "0"
        self.cached = {}
        self.revisions = {}
        self.ready = False
        self.receive_only = False
        self.modes = ()

    def open(self):
        import websocket

        self.ready = False
        self.ws = websocket.create_connection(self.url, timeout=2, suppress_origin=True)
        self.ws.settimeout(0.045)
        self.timeout_error = websocket.WebSocketTimeoutException
        self.transport_error = websocket.WebSocketException

    def close(self):
        if self.ws is not None:
            try:
                self.ws.close(timeout=0.2)
            finally:
                self.ws = None

    def send(self, message):
        self.log("→", message)
        try:
            self.ws.send(message)
        except self.transport_error as error:
            raise ConnectionError("Не удалось отправить команду TCI.") from error

    def record(self, key, value):
        self.cached[key] = value
        self.revisions[key] = self.revisions.get(key, 0) + 1

    def sync(self, during_tx=False):
        try:
            message = self.ws.recv()
        except self.timeout_error:
            return
        except self.transport_error as error:
            raise ConnectionError("Соединение TCI закрыто или прервано.") from error
        if message == "":
            raise ConnectionError("Сервер TCI закрыл соединение.")
        if not isinstance(message, str):
            return
        for packet in message.split(";"):
            packet = packet.strip()
            if not packet:
                continue
            self.log("←", packet + ";")
            try:
                self.on_packet(packet)
            except (ValueError, OverflowError):
                continue

    def on_packet(self, packet):
        command, _, payload = packet.partition(":")
        command = command.lower()
        args = payload.split(",")
        if command == "ready":
            self.ready = True
        elif command == "device" and payload:
            self.publish("device", payload)
        elif command == "receive_only":
            self.receive_only = state(args[0])
        elif command == "modulations_list":
            self.modes = tuple(name.upper() for name in args)
        elif args[0] != self.receiver:
            return
        elif command == "vfo" and len(args) == 3 and args[1] in ("0", "1"):
            self.record("vfo" + args[1], int(args[2]))
            self.publish_frequencies()
        elif command == "modulation" and len(args) == 2:
            raw = args[1].upper()
            self.record("modulation", raw)
            self.publish("mode", ({"DIGU": "U-D", "DIGL": "L-D"}.get(raw, raw), None))
        elif command in ("trx", "split_enable") and len(args) >= 2:
            flag = state(args[1])
            self.record(command, flag)
            label = ("TX" if flag else "RX") if command == "trx" else ("Вкл" if flag else "Выкл")
            self.publish("ptt" if command == "trx" else "split", label)
        elif command == "rx_sensors" and len(args) == 2:
            self.signal(args[1])
        elif command == "rx_channel_sensors" and len(args) == 3 and args[1] == self.channel:
            self.signal(args[2])
        elif command == "tx_sensors" and len(args) >= 5:
            power, swr = numeric(args[2]), numeric(args[4])
            self.publish("po", f"{power:g} Вт")
            if power > 0 and swr >= 1:
                self.publish("swr_live", (f"{swr:.2f}:1", swr))

    def signal(self, raw):
        value = numeric(raw)
        self.publish("smeter", round(max(0, min(255, (value + 127) * 2))))
        self.publish("signal", f"{value:g} дБм")

    def publish_frequencies(self):
        self.publish("frequency", self.cached.get("vfo" + self.channel))
        self.publish("other_frequency", self.cached.get("vfo" + ("1" if self.channel == "0" else "0")))

    def wait_for(self, predicate, timeout=1.4, stop=None):
        deadline = time.monotonic() + timeout
        while not predicate():
            if (stop is not None and stop.is_set()) or time.monotonic() >= deadline:
                raise CommandError("Сервер TCI не подтвердил состояние.")
            self.sync()

    def exchange(self, message, key, expected=None):
        baseline = self.revisions.get(key, 0)
        self.send(message)
        self.wait_for(lambda: self.revisions.get(key, 0) > baseline and
                      (expected is None or self.cached[key] == expected))
        return self.cached[key]

    def init_state(self, stop):
        self.wait_for(lambda: self.ready, timeout=3, stop=stop)
        rx = self.receiver
        self.exchange(f"vfo:{rx},{self.channel};", "vfo" + self.channel)
        self.exchange(f"modulation:{rx};", "modulation")
        self.publish("vfo", "A")
        for command in (f"trx:{rx};", f"split_enable:{rx};",
                        "rx_sensors_enable:true,250;", "tx_sensors_enable:true,300;"):
            self.send(command)

    def write(self, key, value):
        rx, ch = self.receiver, self.channel
        if key == "frequency":
            self.exchange(f"vfo:{rx},{ch},{value};", "vfo" + ch, value)
        elif key == "mode":
            name = self.mode_names.get(value, value)
            if self.modes and name not in self.modes:
                raise CommandError(f"Сервер TCI не поддерживает режим {name}.")
            self.exchange(f"modulation:{rx},{name};", "modulation", name)
        elif key == "vfo":
            new = str(value)
            self.exchange(f"vfo:{rx},{new};", "vfo" + new)
            self.channel = new
            self.publish("vfo", ("A", "B")[value])
            self.publish_frequencies()
        elif key == "split":
            self.exchange(f"split_enable:{rx},{str(value).lower()};", "split_enable", value)

    def check_tx(self):
        if self.receive_only:
            raise CommandError("TCI: это приёмник без передачи.")
        if self.channel != "0":
            raise CommandError("Для передачи через TCI выберите канал A.")
        rx = self.receiver
        if self.exchange(f"modulation:{rx};", "modulation") not in ("USB", "DIGU"):
            raise CommandError("Для аудиопередачи TCI нужен USB или DIGU.")
        if self.exchange(f"trx:{rx};", "trx"):
            raise CommandError("Трансивер уже в TX.")
        if self.exchange(f"split_enable:{rx};", "split_enable"):
            raise CommandError("Для аудиопередачи TCI отключите SPLIT.")

    def ptt(self, enabled):
        arg = "true,micpc" if enabled else "false"
        self.exchange(f"trx:{self.receiver},{arg};", "trx", enabled)

    def recover(self):
        self.close()
        self.open()
        self.wait_for(lambda: self.ready, timeout=3)


class NetworkSession:
    """Serialize network requests and keep PTT release in the radio worker."""

    def __init__(self, make_driver, label, report):
        self.label, self.report = label, report
        self.jobs = queue.Queue()
        self.values = {}
        self.driver = make_driver(self.publish, self.log)

    def publish(self, key, value):
        if key not in self.values or self.values[key] != value:
            self.values[key] = value
            self.report("cat_value", (key, value))

    def log(self, direction, message):
        self.report("cat_frame", (direction, message))

    @contextmanager
    def keyed(self, cancel):
        if not cancel.is_set():
            self.driver.check_tx()
        if cancel.is_set():
            yield False
            return
        try:
            self.driver.ptt(True)
            yield True
        finally:
            self.release_ptt()

    def release_ptt(self):
        for attempt in range(3):
            try:
                if attempt:
                    self.driver.recover()
                self.driver.ptt(False)
                return
            except Exception as error:
                if attempt == 2:
                    self.publish("ptt", "Неизвестно")
                    raise CommandError("Снятие PTT не подтверждено. Проверьте TX на трансивере.") from error

    def run(self, stop):
        try:
            self.driver.open()
            self.driver.init_state(stop)
            self.report("cat_ready", self.label)
            while not stop.is_set():
                try:
                    job, args = self.jobs.get(timeout=0.035)
                except queue.Empty:
                    self.driver.sync()
                    continue
                if job == "tx":
                    action, *arguments = args
                    try:
                        action(*arguments, self, lambda: self.driver.sync(during_tx=True), self.report)
                    except Exception as error:
                        self.report("tx_done", str(error))
                    else:
                        self.report("tx_done", None)
                    last = self.values.get("swr_live")
                    if last and not last[0].endswith(" · посл."):
                        self.publish("swr_live", (last[0] + " · посл.", last[1]))
                else:
                    try:
                        self.driver.write(job, args[0])
                    except (CommandError, ValueError) as error:
                        self.report("cat_write_done", str(error))
                    else:
                        self.report("cat_write_done", None)
        finally:
            self.driver.close()
