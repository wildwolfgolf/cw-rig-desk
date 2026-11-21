"""Smoke test for the actual standalone executable on Windows CI."""

from pathlib import Path
from threading import Event
from traceback import format_exc
import tkinter as tk

from . import __version__, hamlib_runtime, radio
from .app import App


def run(report_path):
    report = Path(report_path)
    root = None
    try:
        root = tk.Tk()
        gui = App(root)
        root.update()
        if __version__ not in root.title():
            raise RuntimeError("Missing version in window title")
        if gui.rx_status.get().startswith("Ошибка списка устройств"):
            raise RuntimeError(gui.rx_status.get())
        audio, _ = radio.sd.get_portaudio_version()
        if not audio:
            raise RuntimeError("PortAudio failed to load")
        demo = []
        radio.demo(gui.rx_settings(), lambda _, result: demo.append(result))
        if not demo or demo[0][0] != demo[0][1]:
            raise RuntimeError("Demo CW decoding failed")

        hamlib = hamlib_runtime.find_bin()
        models = {model.id for model in hamlib_runtime.catalog(hamlib)}
        if not {1, 1036, 2037, 3073}.issubset(models):
            raise RuntimeError("Incomplete Hamlib model catalog")
        readings = {}
        stop = Event()
        rig = hamlib_runtime.ManagedHamlib(
            hamlib / "rigctld.exe", 1, None, None, readings.__setitem__, lambda *_: None, stop
        )
        try:
            rig.open()
            process = rig.child
            rig.init_state(stop)
            rig.write("frequency", 14_060_000)
            if readings.get("frequency") != 14_060_000:
                raise RuntimeError("Hamlib Dummy did not confirm the CAT frequency")
        finally:
            rig.close()
        if process.poll() is None:
            raise RuntimeError("Hamlib process did not stop")
    except Exception:
        report.write_text(format_exc(), encoding="utf-8")
        return 1
    finally:
        if root is not None:
            root.destroy()
    report.write_text(f"CW Rig Desk {__version__}: Tk, PortAudio, CW decoder and Hamlib Dummy OK\n",
                      encoding="utf-8")
    return 0
