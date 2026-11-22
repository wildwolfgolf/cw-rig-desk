"""Smoke test for the actual standalone executable on Windows CI."""

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from traceback import format_exc
import tkinter as tk

import numpy as np

from . import __version__, app, hamlib_runtime, radio
from .app import App, load_settings


def check_languages(gui):
    gui.settings["alphabet"].set("RUS")
    gui.tx_text.insert("1.0", "CQ TEST")
    gui.update_reading("frequency", 7_030_000)
    gui.show_details()
    gui.language_selector.current(1)
    gui.language_selector.event_generate("<<ComboboxSelected>>")
    gui.root.update()
    if (gui.equipment.title() != "Equipment" or gui.cat_button["text"] != "Connect CAT"
            or gui.cat_table.set("frequency", "label") != "Active VFO frequency"
            or gui.cat_table.set("frequency", "value") != "7 030 000 Hz"
            or gui.macro_buttons[1]["text"] != "Reply"
            or "Hamlib · built-in" not in gui.profile_selector["values"]
            or gui.hamlib_baud.get() != "Auto"
            or gui.settings["alphabet"].get() != "RUS"
            or gui.tx_text.get("1.0", "end-1c") != "CQ TEST"
            or load_settings()["language"] != "en"):
        raise RuntimeError("English interface switch did not update controls or preserve state")
    gui.language_selector.current(0)
    gui.language_selector.event_generate("<<ComboboxSelected>>")
    gui.root.update()
    if gui.equipment.title() != "Оборудование" or gui.macro_buttons[1]["text"] != "Ответ":
        raise RuntimeError("Could not switch the interface back to Russian")
    gui.settings["alphabet"].set("LAT")
    gui.close_details()


def run(report_path):
    report = Path(report_path)
    root = None
    settings_dir = TemporaryDirectory()
    original_paths = app.CONFIG, app.LEGACY_CONFIG
    app.CONFIG = Path(settings_dir.name) / "settings.json"
    app.LEGACY_CONFIG = Path(settings_dir.name) / "legacy.json"
    try:
        root = tk.Tk()
        gui = App(root)
        root.update()
        if __version__ not in root.title():
            raise RuntimeError("Missing version in window title")
        if gui.rx_status.source.startswith("Ошибка списка устройств"):
            raise RuntimeError(gui.rx_status.get())
        check_languages(gui)
        gui.waterfall.add(np.linspace(-90, -10, 160))
        gui.waterfall.set_target(700, 200)
        gui.waterfall.draw()
        audio, _ = radio.sd.get_portaudio_version()
        if not audio:
            raise RuntimeError("PortAudio failed to load")
        for bayesian in (False, True):
            rx = gui.rx_settings()
            if rx["bayesian"] != bayesian:
                raise RuntimeError("Bayesian decoder checkbox did not update receive settings")
            if bayesian:
                gui.save_settings()
                if not load_settings()["bayesian"]:
                    raise RuntimeError("Bayesian decoder setting was not saved")
            for alphabet in ("LAT", "RUS"):
                rx["alphabet"] = alphabet
                demo = []
                radio.demo(rx, lambda _, result: demo.append(result))
                if not demo or demo[0][0] != demo[0][1]:
                    raise RuntimeError(f"Demo CW decoding failed: {alphabet}, Bayesian={bayesian}")
            gui.bayesian_choice.invoke()

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
        app.CONFIG, app.LEGACY_CONFIG = original_paths
        settings_dir.cleanup()
    report.write_text(f"CW Rig Desk {__version__}: Tk, RU/EN switch, PortAudio, both CW decoders and Hamlib Dummy OK\n",
                      encoding="utf-8")
    return 0
