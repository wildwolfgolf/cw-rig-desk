"""Portable Hamlib discovery and local rigctld lifecycle."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
from zipfile import ZipFile

from .network_cat import Hamlib

VERSION = "4.7.2"
BINARY_NAME = f"hamlib-w64-{VERSION}.zip"
SOURCE_NAME = f"hamlib-{VERSION}.tar.gz"
RELEASE_URL = f"https://github.com/Hamlib/Hamlib/releases/download/{VERSION}/"
DIGESTS = {
    BINARY_NAME: "8553bc6c5c6032e8debf99c017e98f58fed7e07e7c25d04815dc3e8bbe3304c7",
    SOURCE_NAME: "ae1fcf2dbc80ea0786ea8f047b09399c3f7737d1930442f61a031708ed33e88f",
}
AUTO = "Авто"
LOOPBACK = "127.0.0.1"


def windows_flags():
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def download_asset(name, destination):
    """Return a verified official upstream asset."""
    expected = DIGESTS[name]
    destination = Path(destination)
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected:
        return destination
    digest = hashlib.sha256()
    total = 0
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as staging:
        temporary = Path(staging.name)
        try:
            with urlopen(RELEASE_URL + name, timeout=12) as response:
                deadline = time.monotonic() + 45
                while chunk := response.read(64 * 1024):
                    total += len(chunk)
                    if total > 12 * 1024 * 1024 or time.monotonic() > deadline:
                        raise RuntimeError("Не удалось завершить загрузку Hamlib.")
                    digest.update(chunk)
                    staging.write(chunk)
            if digest.hexdigest() != expected:
                raise RuntimeError("Контрольная сумма пакета Hamlib не совпала.")
            staging.close()
            temporary.replace(destination)
        finally:
            staging.close()
            temporary.unlink(missing_ok=True)
    return destination


def install_binary_archive(archive, destination):
    if hashlib.sha256(Path(archive).read_bytes()).hexdigest() != DIGESTS[BINARY_NAME]:
        raise RuntimeError("Контрольная сумма пакета Hamlib не совпала.")
    with ZipFile(archive) as package:
        # The complete, unmodified upstream package includes notices and licenses.
        package.extractall(destination)


def find_bin():
    if sys.platform != "win32":
        raise RuntimeError("Встроенная сборка Hamlib предназначена для Windows x64.")
    frozen = getattr(sys, "frozen", False)
    stem = Path(sys._MEIPASS) if frozen else Path(__file__).resolve().parents[1]
    bundle = f"hamlib-w64-{VERSION}"
    portable = stem / "vendor" / bundle / "bin"
    if (portable / "rigctl.exe").is_file() and (portable / "rigctld.exe").is_file():
        return portable
    if frozen:
        raise RuntimeError("В сборке отсутствуют файлы Hamlib. Скачайте выпуск CW Rig Desk заново.")
    cached = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "CW_Rig_Desk" / "vendor"
    cached_bin = cached / bundle / "bin"
    if (cached_bin / "rigctl.exe").is_file() and (cached_bin / "rigctld.exe").is_file():
        return cached_bin
    cached.mkdir(parents=True, exist_ok=True)
    # Separate staging keeps concurrent launches from seeing an incomplete package.
    with tempfile.TemporaryDirectory(dir=cached) as work:
        work = Path(work)
        asset = download_asset(BINARY_NAME, work / BINARY_NAME)
        install_binary_archive(asset, work)
        try:
            (work / bundle).rename(cached / bundle)
        except OSError:
            if not (cached / bundle / "bin" / "rigctld.exe").is_file():
                raise
    return cached_bin


@dataclass(frozen=True)
class Model:
    id: int
    name: str

    @property
    def label(self):
        return f"{self.name} [{self.id}]"


def parse_models(output):
    models = {}
    for line in output.splitlines():
        fields = re.split(r"\s{2,}", line.strip())
        if len(fields) < 4 or not fields[0].isdigit():
            continue
        model_id = int(fields[0])
        # Low-ID entries other than Dummy are bridges rather than radio models.
        if model_id == 1 or model_id >= 1000:
            name = " ".join(fields[1:3])
            models[model_id] = Model(model_id, name)
    return tuple(sorted(models.values(), key=lambda model: (model.id != 1, model.name.casefold())))


def catalog(bin_dir):
    try:
        result = subprocess.run(
            [str(bin_dir / "rigctl.exe"), "-l"], cwd=bin_dir, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, creationflags=windows_flags(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(f"Не удалось прочитать список моделей Hamlib: {error}") from error
    models = parse_models(result.stdout.decode("utf-8", errors="replace"))
    if not models:
        raise RuntimeError("Hamlib вернул пустой список моделей.")
    return models


def resolve_serial(model_id, selected, devices):
    if model_id == 1:
        return None
    if selected != AUTO:
        if any(item.device == selected for item in devices):
            return selected
        raise ValueError(f"Порт {selected} недоступен. Проверьте подключение CAT.")
    usb = [item for item in devices if item.vid is not None]
    if model_id == 1036:
        # The FT-891's dual Silicon Labs interface uses Enhanced for CAT.
        enhanced = [item.device for item in usb if item.vid == 0x10C4
                    and "enhanced" in (item.description or "").casefold()]
        if len(enhanced) == 1:
            return enhanced[0]
    if len(usb) == 1:
        return usb[0].device
    if not usb:
        raise ValueError("Автоопределение не нашло USB-порт CAT. Подключите трансивер или выберите COM-порт.")
    raise ValueError("Найдено несколько USB COM-портов. Выберите CAT-порт трансивера.")


def command_line(executable, model_id, serial_port, baud, tcp_port):
    arguments = [str(executable), "-m", str(model_id), "-P", "RIG",
                 "-T", LOOPBACK, "-t", str(tcp_port)]
    if serial_port:
        if os.name == "nt" and re.fullmatch(r"COM[0-9]+", serial_port, re.IGNORECASE):
            serial_port = "\\\\.\\" + serial_port.upper()
        arguments.extend(("-r", serial_port))
    if baud is not None and serial_port:
        arguments.extend(("-s", str(baud)))
    return arguments


def local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind((LOOPBACK, 0))
        return reservation.getsockname()[1]


class ManagedHamlib(Hamlib):
    def __init__(self, executable, model_id, serial_port, baud, publish, log, stop):
        super().__init__(LOOPBACK, 0, publish, log)
        self.executable = Path(executable)
        self.model_id, self.serial_port, self.baud = model_id, serial_port, baud
        self.stop = stop
        self.child = None
        self.stderr = None

    def open(self):
        # NetworkSession owns cleanup even when open or the CAT handshake fails.
        self.port = local_port()
        arguments = command_line(self.executable, self.model_id, self.serial_port, self.baud, self.port)
        self.stderr = tempfile.TemporaryFile()
        self.child = subprocess.Popen(
            arguments, cwd=self.executable.parent, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=self.stderr, creationflags=windows_flags(),
        )
        deadline = time.monotonic() + 6
        while not self.stop.is_set() and time.monotonic() < deadline and self.child.poll() is None:
            try:
                super().open()
            except OSError:
                self.stop.wait(0.09)
            else:
                if self.child.poll() is None:
                    return
                break
        if self.stop.is_set():
            return
        self.stderr.seek(max(0, self.stderr.seek(0, os.SEEK_END) - 1600))
        detail = self.stderr.read().decode("utf-8", errors="replace").strip()
        raise ConnectionError(f"Hamlib не запустил CAT для выбранной модели. {detail}".rstrip())

    def recover(self):
        # Keep the same rigctld instance so a lost TCP reply cannot leave TX active.
        super().close()
        if self.child is None or self.child.poll() is not None:
            raise ConnectionError("Встроенный rigctld остановился.")
        super().open()

    def close(self):
        try:
            super().close()
            if self.child is not None and self.child.poll() is None:
                self.child.terminate()
                try:
                    self.child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait(timeout=2)
        finally:
            self.child = None
            if self.stderr is not None:
                self.stderr.close()
                self.stderr = None
