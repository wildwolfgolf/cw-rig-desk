"""Windows desktop interface for the CW Rig Desk decoder and keyboard sender."""

from collections import deque
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from urllib.parse import urlsplit
from tkinter import messagebox, ttk

from serial.tools import list_ports

from . import __version__
from . import cat as civ, diagnostics, hamlib_runtime as bundled, network_cat as network, radio, ui_theme as theme
from .localization import LANGUAGES, Message, error_text, reading_text, translate
from .morse import encode_text, expand_macro

CONFIG = Path(os.getenv("LOCALAPPDATA") or Path.home()) / "CW_Rig_Desk" / "settings.json"
LEGACY_CONFIG = CONFIG.parent.parent / "G90_CW" / "settings.json"
CW_FILTERS = {"Выкл.": 0, "100": 100, "200": 200, "300": 300, "500": 500}
# Band edges for the display and initial tuning presets, all in hertz.
HF_BANDS = (
    (160, 1_800_000, 2_000_000, 1_836_000),
    (80, 3_500_000, 4_000_000, 3_560_000),
    (60, 5_330_500, 5_405_000, 5_354_000),
    (40, 7_000_000, 7_300_000, 7_030_000),
    (30, 10_100_000, 10_150_000, 10_116_000),
    (20, 14_000_000, 14_350_000, 14_060_000),
    (17, 18_068_000, 18_168_000, 18_086_000),
    (15, 21_000_000, 21_450_000, 21_060_000),
    (12, 24_890_000, 24_990_000, 24_906_000),
    (10, 28_000_000, 29_700_000, 28_060_000),
)
DEFAULT_MACROS = [
    ["CQ", "CQ CQ DE {CALL} K"],
    ["Ответ", "{OTHER} DE {CALL} K"],
    ["Рапорт", "{OTHER} DE {CALL} UR RST {RST} K"],
    ["73", "{OTHER} DE {CALL} TNX QSO 73 <SK>"],
]
DEFAULTS = {
    "language": "ru", "input": "", "output": "", "port": "", "address": "70", "pitch": "700",
    "rx_wpm": "18", "tx_wpm": "18", "sensitivity": "-34", "level": "12",
    "lead": "250", "alphabet": "LAT", "adaptive": True, "cw_filter": "Выкл.",
    "auto_pitch": True,
    "call": "", "other": "", "rst": "599", "macros": DEFAULT_MACROS,
    "profile": network.G90_PROFILE, "hamlib_host": "127.0.0.1", "hamlib_port": "4532",
    "tci_url": "ws://127.0.0.1:40001", "tci_receiver": "0", "tci_audio": True,
    "hamlib_model": "", "hamlib_device": bundled.AUTO, "hamlib_baud": bundled.AUTO,
}


def load_settings():
    try:
        try:
            payload = CONFIG.read_text(encoding="utf-8")
        except FileNotFoundError:
            payload = LEGACY_CONFIG.read_text(encoding="utf-8")
        saved = json.loads(payload)
        if not isinstance(saved, dict):
            return DEFAULTS.copy()
    except (OSError, ValueError):
        return DEFAULTS.copy()

    settings = {key: saved.get(key, value) for key, value in DEFAULTS.items()}
    for key, default in DEFAULTS.items():
        if type(settings[key]) is not type(default):
            settings[key] = default
    macros = settings["macros"]
    if len(macros) != len(DEFAULT_MACROS) or any(
        not isinstance(row, list) or len(row) != 2 or
        not all(isinstance(cell, str) and cell.strip() for cell in row)
        for row in macros
    ):
        settings["macros"] = DEFAULT_MACROS
    if settings["alphabet"] not in ("LAT", "RUS"):
        settings["alphabet"] = "LAT"
    if settings["cw_filter"] not in CW_FILTERS:
        settings["cw_filter"] = DEFAULTS["cw_filter"]
    for key, values in (("language", LANGUAGES), ("profile", network.PROFILES), ("tci_receiver", ("0", "1"))):
        if settings[key] not in values:
            settings[key] = DEFAULTS[key]
    return settings


class StatusText(tk.StringVar):
    def __init__(self, root, translate_text, value=""):
        super().__init__(root)
        self.translate_text = translate_text
        self.set(value)

    def set(self, value):
        self.source = value
        self.refresh()

    def refresh(self):
        super().set(self.translate_text(self.source))


class App:
    def __init__(self, root):
        self.root = root
        self.events = queue.SimpleQueue()
        self.rx_stop = threading.Event()
        self.rx_filter_updates = queue.SimpleQueue()
        self.tx_cancel = threading.Event()
        self.tx_active = threading.Event()
        self.cat_stop = threading.Event()
        self.session = None
        self.cat_ready = False
        self.cat_writing = False
        self.cat_values = {}
        self.hamlib_models = {}
        self.hamlib_bin = None
        self.hamlib_loading = False
        self.band_frequencies = {band: preset for band, _, _, preset in HF_BANDS}
        self.cat_log = deque(maxlen=800)
        self.details = None
        self.ports_found = []
        self.rx_running = False
        self.rx_uses_tci = False
        self.tx_running = False
        self.closing = False
        self.macros = []
        self.inputs, self.outputs = {}, {}
        saved = load_settings()
        self.macros = saved.pop("macros")
        self.settings = {
            key: (tk.BooleanVar if isinstance(value, bool) else tk.StringVar)(
                root, value=value
            ) for key, value in saved.items()
        }
        self.language_updates = {}
        self.status_texts = []
        self.hamlib_hint = self.status()
        self.armed = tk.BooleanVar(root, value=False)
        self.rx_status = self.status("Приём остановлен")
        self.tx_status = self.status("Передача отключена")
        self.level = tk.DoubleVar(root, value=0)
        self.cat_status = self.status("CAT отключён")
        self.cat_link = ""
        self.frequency_entry = tk.StringVar(root)
        self.mode_entry = tk.StringVar(root, value="U-D")
        self.cat_display = {key: tk.StringVar(root, value="—") for key in
                            ("frequency", "mode", "swr_live", "ptt", "smeter", "po", "alc")}

        self.frequency_digits = tk.StringVar(root, value="—")
        self.signal_display = tk.StringVar(root, value="—")
        self.split_display = tk.StringVar(root, value="SPLIT —")
        self.swr_note = self.status()
        self.mono_font = theme.configure(root)

        self.reflect(root, root.title, Message("CW Rig Desk {version} — приём и передача Морзе",
                                              version=__version__))
        root.minsize(1010, 710)
        root.geometry("1180x780")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", lambda event: self.stop_tx())
        root.bind("<Control-Return>", lambda event: self.send())
        self.build()
        self.refresh()
        root.after(40, self.poll)

    def tr(self, value):
        return translate(value, self.settings["language"].get())

    def status(self, value=""):
        variable = StatusText(self.root, self.tr, value)
        self.status_texts.append(variable)
        return variable

    def reflect(self, widget, display, text):
        self.on_language(widget, lambda: display(self.tr(text)))

    def on_language(self, widget, update):
        if widget not in self.language_updates:
            self.language_updates[widget] = []

            def forget(event):
                if event.widget == widget:
                    self.language_updates.pop(widget, None)

            widget.bind("<Destroy>", forget, add="+")
        self.language_updates[widget].append(update)
        update()

    def widget(self, widget_type, parent, *, text=None, **options):
        widget = widget_type(parent, **options)
        if text is not None:
            self.reflect(widget, lambda value: widget.configure(text=value), text)
        return widget

    def localize_choices(self, widget, key, choices):
        setting = self.settings[key]
        display = tk.StringVar(self.root)
        widget.configure(textvariable=display)

        def refresh_choices():
            widget.configure(values=tuple(self.tr(value) for value in choices()))
            display.set(self.tr(setting.get()))

        def select(_event):
            index = widget.current()
            if index >= 0:
                setting.set(choices()[index])

        widget.bind("<<ComboboxSelected>>", select)
        setting.trace_add("write", lambda *_: display.set(self.tr(setting.get())))
        self.on_language(widget, refresh_choices)
        return refresh_choices

    def change_language(self, _event=None):
        index = self.language_selector.current()
        if index < 0:
            return
        self.settings["language"].set(tuple(LANGUAGES)[index])
        for updates in self.language_updates.values():
            for update in updates:
                update()
        for status in self.status_texts:
            status.refresh()
        self.update_cat_buttons()
        self.update_macros()
        for key, value in self.cat_values.items():
            self.update_reading(key, value)
        self.save_settings()

    def notify(self, show, title, detail, *, parent):
        show(self.tr(title), self.tr(detail), parent=parent)

    def build(self):
        root = self.root
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        body = ttk.Frame(root, style="Page.TFrame", padding=(22, 14, 22, 18))
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=5, uniform="workspace")
        body.columnconfigure(1, weight=5, uniform="workspace")
        body.rowconfigure(2, weight=1)

        header = ttk.Frame(body, style="Page.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 13))
        title = ttk.Frame(header, style="Page.TFrame")
        title.pack(side="left")
        self.widget(ttk.Label, title, text=f"CW Rig Desk {__version__}", style="Brand.TLabel").pack(anchor="w")
        profile_text = self.status(self.settings["profile"].get())
        self.settings["profile"].trace_add("write", lambda *_: profile_text.set(self.settings["profile"].get()))
        self.widget(ttk.Label, title, textvariable=profile_text, style="PageNote.TLabel").pack(anchor="w")
        self.language_selector = ttk.Combobox(header, values=tuple(LANGUAGES.values()), width=8, state="readonly")
        self.language_selector.set(LANGUAGES[self.settings["language"].get()])
        self.language_selector.bind("<<ComboboxSelected>>", self.change_language)
        self.language_selector.pack(side="right", padx=(8, 0))
        self.widget(ttk.Button, header, text="Оборудование", command=self.show_equipment).pack(side="right")
        self.widget(ttk.Button, header, text="Телеметрия CAT", command=self.show_details).pack(
            side="right", padx=(8, 8)
        )
        self.cat_button = ttk.Button(header, command=self.toggle_cat)
        self.cat_button.pack(side="right")
        self.link_label = self.widget(ttk.Label, header, textvariable=self.cat_status, style="Link.TLabel")
        self.link_label.pack(side="right", padx=(0, 12))

        self.build_cat(body)
        self.build_receive(body)
        self.build_transmit(body)
        self.build_equipment()
        self.update_rx_buttons()
        self.update_tx_buttons()
        self.update_cat_buttons()

    def build_cat(self, parent):
        panel = ttk.Frame(parent, style="Card.TFrame", padding=12)
        panel.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        screen = ttk.Frame(panel, style="Screen.TFrame", padding=(16, 11))
        screen.pack(fill="x")
        screen.columnconfigure(0, weight=5, uniform="display")
        screen.columnconfigure(2, weight=4, uniform="display")

        vfo = ttk.Frame(screen, style="Screen.TFrame")
        vfo.grid(row=0, column=0, sticky="nsew", padx=(0, 15))
        self.widget(ttk.Label, vfo, text="Частота активного VFO", style="MeterTitle.TLabel").pack(anchor="w")
        digits = ttk.Frame(vfo, style="Screen.TFrame")
        digits.pack(fill="x", pady=(1, 3))
        self.widget(ttk.Label, digits, textvariable=self.frequency_digits, style="Frequency.TLabel").pack(side="left")
        self.widget(ttk.Label, digits, text="Гц", style="MeterTitle.TLabel").pack(side="left", padx=(10, 0))
        flags = ttk.Frame(vfo, style="Screen.TFrame")
        flags.pack(fill="x")
        self.widget(ttk.Label, flags, textvariable=self.cat_display["mode"], style="RadioBadge.TLabel").pack(side="left")
        self.radio_state = self.widget(ttk.Label, flags, textvariable=self.cat_display["ptt"], style="RadioBadge.TLabel")
        self.radio_state.pack(side="left", padx=7)
        self.widget(ttk.Label, flags, textvariable=self.split_display, style="MeterTitle.TLabel").pack(side="left", padx=4)

        ttk.Separator(screen, orient="vertical").grid(row=0, column=1, sticky="ns")
        meter = ttk.Frame(screen, style="Screen.TFrame")
        meter.grid(row=0, column=2, sticky="nsew", padx=(15, 0))
        caption = ttk.Frame(meter, style="Screen.TFrame")
        caption.pack(fill="x")
        self.widget(ttk.Label, caption, text="S-метр · CAT", style="MeterTitle.TLabel").pack(side="left")
        self.widget(ttk.Label, caption, textvariable=self.signal_display, style="Screen.TLabel").pack(side="right")
        self.smeter = tk.Canvas(meter, width=1, height=14, background=theme.SCREEN, highlightthickness=0)
        self.smeter.pack(fill="x", pady=(5, 10))
        self.smeter.bind("<Configure>", lambda event: self.draw_smeter())
        metrics = ttk.Frame(meter, style="Screen.TFrame")
        metrics.pack(fill="x")
        for col, (name, key) in enumerate((("КСВ", "swr_live"), ("Мощность · CAT", "po"), ("ALC · CAT", "alc"))):
            metrics.columnconfigure(col, weight=1, uniform="meters")
            cell = ttk.Frame(metrics, style="Screen.TFrame")
            cell.grid(row=0, column=col, sticky="new")
            self.widget(ttk.Label, cell, text=name, style="MeterTitle.TLabel").pack(anchor="w")
            self.widget(ttk.Label, cell, textvariable=self.cat_display[key], style="MeterValue.TLabel").pack(anchor="w")
            if key == "swr_live":
                self.widget(ttk.Label, cell, textvariable=self.swr_note, style="MeterTitle.TLabel").pack(anchor="w")

        controls = ttk.Frame(panel)
        controls.pack(fill="x", pady=(10, 0))
        self.cat_controls = []
        self.widget(ttk.Label, controls, text="Частота, Гц", style="Hint.TLabel").pack(side="left", padx=(0, 6))
        entry = ttk.Entry(controls, textvariable=self.frequency_entry, width=12)
        entry.pack(side="left", padx=(0, 5))
        entry.bind("<Return>", lambda event: self.set_frequency())
        self.cat_controls.append((entry, "normal"))

        def button(label, action, gap=(0, 5)):
            widget = self.widget(ttk.Button, controls, text=label, command=action, style="Control.TButton")
            widget.pack(side="left", padx=gap)
            self.cat_controls.append((widget, "normal"))

        button("Установить", self.set_frequency, (0, 14))
        self.mode_picker = mode = ttk.Combobox(controls, textvariable=self.mode_entry, state="readonly",
                            values=tuple(civ.MODES), width=5)
        mode.pack(side="left", padx=(0, 5))
        self.cat_controls.append((mode, "readonly"))
        button("Режим", lambda: self.write_cat("mode", self.mode_entry.get()), (0, 14))
        button("VFO A", lambda: self.write_cat("vfo", 0))
        button("VFO B", lambda: self.write_cat("vfo", 1), (0, 14))
        button("SPLIT вкл.", lambda: self.write_cat("split", True))
        button("SPLIT выкл.", lambda: self.write_cat("split", False), (0, 0))

        bands = ttk.Frame(panel)
        bands.pack(fill="x", pady=(8, 0))
        self.widget(ttk.Label, bands, text="Диапазон", style="Hint.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        self.band_buttons = {}
        for column, (band, _, _, _) in enumerate(HF_BANDS, start=1):
            bands.columnconfigure(column, weight=1, uniform="bands")
            widget = self.widget(ttk.Button,
                bands, text=Message("{band} м", band=band), style="Band.TButton",
                command=lambda meters=band: self.write_cat("frequency", self.band_frequencies[meters]),
            )
            widget.grid(row=0, column=column, sticky="ew", padx=(0, 4 if column < len(HF_BANDS) else 0))
            self.band_buttons[band] = widget
            self.cat_controls.append((widget, "normal"))

    def draw_smeter(self):
        self.smeter.delete("segment")
        width = self.smeter.winfo_width()
        if width < 24:
            return
        active = round(24 * (self.cat_values.get("smeter") or 0) / 255)
        for index in range(24):
            x = index * width / 24
            color = theme.ACCENT if index < active else theme.LINE
            self.smeter.create_rectangle(x, 1, (index + 1) * width / 24 - 3, 13,
                                         fill=color, width=0, tags="segment")

    def build_receive(self, parent):
        rx = ttk.Frame(parent, style="Card.TFrame", padding=14)
        rx.grid(row=2, column=0, sticky="nsew", padx=(0, 6))
        rx.columnconfigure(0, weight=1)
        rx.rowconfigure(2, weight=1)
        header = ttk.Frame(rx)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.widget(ttk.Label, header, text="Приём CW", style="Heading.TLabel").pack(side="left")
        self.rx_stop_button = self.widget(ttk.Button,
            header, text="Остановить приём", command=self.stop_rx, style="Control.TButton"
        )
        self.rx_stop_button.pack(side="right")
        self.rx_start_button = self.widget(ttk.Button,
            header, text="Запустить", command=self.start_rx, style="Primary.TButton", width=0
        )
        self.rx_start_button.pack(side="right", padx=(4, 4))
        self.widget(ttk.Button, header, text="Демо", command=self.demo, style="Control.TButton").pack(side="right")
        params = ttk.Frame(rx)
        params.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.number(params, "Тон, Гц", "pitch", 0, 300, 1200, 10)
        self.number(params, "RX, WPM", "rx_wpm", 1, 6, 35)
        self.number(params, "Порог, дБFS", "sensitivity", 2, -65, -8)
        self.widget(ttk.Label, params, text="Алфавит", style="Hint.TLabel").grid(row=0, column=3, sticky="w")
        self.combo(params, "alphabet", 1, 3, ("LAT", "RUS"), 5)
        self.widget(ttk.Label, params, text="Фильтр CW, Гц", style="Hint.TLabel").grid(
            row=0, column=4, sticky="w", padx=(9, 0)
        )
        cw_filter = self.combo(params, "cw_filter", 1, 4, tuple(CW_FILTERS), 6)
        cw_filter.grid_configure(padx=(9, 0))
        self.localize_choices(cw_filter, "cw_filter", lambda: tuple(CW_FILTERS))
        cw_filter.bind("<<ComboboxSelected>>", self.change_rx_filter, add="+")

        self.rx_text = self.text_box(rx, 2, 6, readonly=True)
        status = ttk.Frame(rx)
        status.grid(row=3, column=0, sticky="ew", pady=(9, 0))
        self.widget(ttk.Button, status, text="Очистить", command=self.clear).pack(side="right")
        self.widget(ttk.Label, status, textvariable=self.rx_status, style="Hint.TLabel", wraplength=300).pack(anchor="w")
        ttk.Progressbar(status, variable=self.level, maximum=60, length=147).pack(anchor="w", pady=(4, 0))
        options = ttk.Frame(rx)
        options.grid(row=4, column=0, sticky="w", pady=(8, 0))
        self.widget(ttk.Checkbutton, options, text="Подстройка скорости",
                    variable=self.settings["adaptive"]).pack(side="left")
        self.widget(ttk.Checkbutton, options, text="Авто тон",
                    variable=self.settings["auto_pitch"]).pack(side="left", padx=(12, 0))

    def build_transmit(self, parent):
        tx = ttk.Frame(parent, style="Card.TFrame", padding=14)
        tx.grid(row=2, column=1, sticky="nsew", padx=(6, 0))
        tx.columnconfigure(0, weight=1)
        tx.rowconfigure(4, weight=1)
        header = ttk.Frame(tx)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.widget(ttk.Label, header, text="Передача CW", style="Heading.TLabel").pack(side="left")
        self.widget(ttk.Button, header, text="Изменить макросы", command=self.edit_macros).pack(side="right")

        fields = ttk.Frame(tx)
        fields.grid(row=1, column=0, sticky="ew")
        for col, (label, key, width) in enumerate((
            ("Мой позывной", "call", 11), ("Корреспондент", "other", 11), ("RST", "rst", 5),
        )):
            fields.columnconfigure(col, weight=1 if col < 2 else 0)
            self.widget(ttk.Label, fields, text=label, style="Hint.TLabel").grid(row=0, column=col, sticky="w")
            ttk.Entry(fields, textvariable=self.settings[key], width=width).grid(
                row=1, column=col, sticky="ew", padx=(0, 8 if col < 2 else 0), pady=(3, 0)
            )

        macro_bar = ttk.Frame(tx)
        macro_bar.grid(row=2, column=0, sticky="ew", pady=(10, 9))
        self.macro_buttons = []
        for col in range(len(self.macros)):
            macro_bar.columnconfigure(col, weight=1, uniform="macros")
            button = ttk.Button(macro_bar, text=self.macro_title(col), width=1, style="Macro.TButton",
                                command=lambda index=col: self.use_macro(index))
            button.grid(row=0, column=col, sticky="ew", padx=(0, 6 if col < 3 else 0))
            self.macro_buttons.append(button)

        self.widget(ttk.Label, tx, text="Текст для передачи", style="Hint.TLabel").grid(
            row=3, column=0, sticky="w", pady=(0, 4)
        )
        self.tx_text = self.text_box(tx, 4, 2)
        params = ttk.Frame(tx)
        params.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.number(params, "TX, WPM", "tx_wpm", 0, 6, 35)
        self.number(params, "Выход, %", "level", 1, 1, 60)
        self.number(params, "Пауза PTT, мс", "lead", 2, 0, 1000, 25)
        actions = ttk.Frame(tx)
        actions.grid(row=6, column=0, sticky="ew", pady=(9, 0))
        self.widget(ttk.Checkbutton, actions, text="Разрешить TX", variable=self.armed,
                        command=self.arm_changed).pack(side="left")
        self.stop_button = self.widget(ttk.Button, actions, text="Стоп TX · Esc", style="Stop.TButton", command=self.stop_tx)
        self.stop_button.pack(side="right")
        self.send_button = self.widget(ttk.Button, actions, text="Передать", style="Primary.TButton", command=self.send)
        self.send_button.pack(side="right", padx=(0, 7))
        self.widget(ttk.Label, tx, textvariable=self.tx_status, style="Hint.TLabel", wraplength=400).grid(
            row=7, column=0, sticky="w", pady=(4, 0)
        )

    def text_box(self, parent, row, height, *, readonly=False):
        box = ttk.Frame(parent, style="Screen.TFrame")
        box.grid(row=row, column=0, sticky="nsew")
        text = self.console_text(box, height=height, width=1)
        text.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(box, command=text.yview)
        bar.pack(side="right", fill="y")
        text.configure(yscrollcommand=bar.set, state="disabled" if readonly else "normal")
        return text

    def console_text(self, parent, **options):
        return tk.Text(parent, background=theme.SCREEN, foreground=theme.TEXT,
                       insertbackground=theme.ACCENT, selectbackground="#28556a",
                       selectforeground=theme.TEXT, highlightthickness=1,
                       highlightbackground=theme.LINE, highlightcolor=theme.ACCENT,
                       borderwidth=0, wrap="word", padx=10, pady=8,
                       font=(self.mono_font, 11), **options)

    def build_equipment(self):
        dialog = tk.Toplevel(self.root, background=theme.BG)
        dialog.withdraw()
        self.reflect(dialog, dialog.title, "Оборудование")
        dialog.transient(self.root)
        dialog.resizable(True, False)
        dialog.protocol("WM_DELETE_WINDOW", dialog.withdraw)
        dialog.bind("<Escape>", lambda event: dialog.withdraw())
        frame = ttk.Frame(dialog, style="Card.TFrame", padding=16)
        frame.pack(fill="both", expand=True, padx=11, pady=11)
        frame.columnconfigure(1, weight=1)
        self.widget(ttk.Label, frame, text="Оборудование", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )
        self.widget(ttk.Label, frame, text="Вход RX", style="Hint.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.rx_devices = self.combo(frame, "input", 1, 1, width=43)
        self.widget(ttk.Label, frame, text="Выход TX", style="Hint.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 8))
        self.tx_devices = self.combo(frame, "output", 2, 1, width=43)
        self.tx_devices.bind("<<ComboboxSelected>>", self.output_changed)

        self.widget(ttk.Label, frame, text="Интерфейс CAT", style="Hint.TLabel").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=(10, 0)
        )
        self.profile_selector = self.combo(frame, "profile", 3, 1, network.PROFILES, 24)
        self.profile_selector.grid_configure(pady=(10, 0))
        self.localize_choices(self.profile_selector, "profile", lambda: network.PROFILES)
        self.profile_selector.bind("<<ComboboxSelected>>", self.profile_changed, add="+")

        serial = ttk.Frame(frame)
        serial.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.widget(ttk.Label, serial, text="Порт CAT", style="Hint.TLabel").pack(side="left", padx=(0, 7))
        self.ports = ttk.Combobox(serial, textvariable=self.settings["port"], state="readonly", width=8)
        self.ports.pack(side="left")
        self.widget(ttk.Label, serial, text="Адрес CI-V (hex)", style="Hint.TLabel").pack(side="left", padx=(14, 7))
        self.cat_address = ttk.Entry(serial, textvariable=self.settings["address"], width=6)
        self.cat_address.pack(side="left")

        local = ttk.Frame(frame)
        local.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        local.columnconfigure(1, weight=1)
        self.widget(ttk.Label, local, text="Модель", style="Hint.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.hamlib_model = ttk.Combobox(local, textvariable=self.settings["hamlib_model"], width=39)
        self.hamlib_model.grid(row=0, column=1, sticky="ew")
        self.hamlib_model.bind("<KeyRelease>", self.filter_hamlib_models)
        self.hamlib_model.bind("<<ComboboxSelected>>", self.filter_hamlib_models)
        serial_options = ttk.Frame(local)
        serial_options.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        self.widget(ttk.Label, serial_options, text="Порт CAT", style="Hint.TLabel").pack(side="left", padx=(0, 7))
        self.hamlib_device = ttk.Combobox(serial_options, textvariable=self.settings["hamlib_device"],
                                          values=(bundled.AUTO,), width=9, state="readonly")
        self.hamlib_device.pack(side="left")
        self.widget(ttk.Label, serial_options, text="Скорость CAT", style="Hint.TLabel").pack(side="left", padx=(12, 7))
        self.hamlib_baud = ttk.Combobox(
            serial_options, textvariable=self.settings["hamlib_baud"], width=8, state="readonly",
            values=(bundled.AUTO, "1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200", "230400"),
        )
        self.hamlib_baud.pack(side="left")
        self.refresh_hamlib_ports = self.localize_choices(
            self.hamlib_device, "hamlib_device", lambda: (bundled.AUTO, *self.ports_found)
        )
        speeds = tuple(self.hamlib_baud["values"])
        self.localize_choices(self.hamlib_baud, "hamlib_baud", lambda: speeds)
        self.widget(ttk.Label, local, textvariable=self.hamlib_hint, style="Hint.TLabel", wraplength=465).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(6, 0)
        )

        hamlib = ttk.Frame(frame)
        hamlib.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.widget(ttk.Label, hamlib, text="Хост rigctld", style="Hint.TLabel").pack(side="left")
        self.hamlib_host = ttk.Entry(hamlib, textvariable=self.settings["hamlib_host"], width=20)
        self.hamlib_host.pack(side="left", padx=8)
        self.widget(ttk.Label, hamlib, text="Порт TCP", style="Hint.TLabel").pack(side="left", padx=(8, 6))
        self.hamlib_port = ttk.Entry(hamlib, textvariable=self.settings["hamlib_port"], width=7)
        self.hamlib_port.pack(side="left")

        tci_panel = ttk.Frame(frame)
        tci_panel.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tci = ttk.Frame(tci_panel)
        tci.pack(anchor="w")
        self.widget(ttk.Label, tci, text="Адрес TCI", style="Hint.TLabel").pack(side="left")
        self.tci_url = ttk.Entry(tci, textvariable=self.settings["tci_url"], width=28)
        self.tci_url.pack(side="left", padx=8)
        self.widget(ttk.Label, tci, text="Приёмник", style="Hint.TLabel").pack(side="left", padx=(8, 6))
        self.tci_receiver = ttk.Combobox(tci, textvariable=self.settings["tci_receiver"],
                                         values=("0", "1"), width=3, state="readonly")
        self.tci_receiver.pack(side="left")
        self.tci_audio_choice = self.widget(
            ttk.Checkbutton, tci_panel, text="Звук RX напрямую через TCI", variable=self.settings["tci_audio"]
        )
        self.tci_audio_choice.pack(anchor="w", pady=(6, 0))
        self.widget(ttk.Label, tci_panel, text=Message("Журнал TCI: {path}", path=diagnostics.LOG),
                    style="Hint.TLabel", wraplength=465).pack(anchor="w", pady=(2, 0))

        self.profile_panels = {
            network.G90_PROFILE: serial, network.LOCAL_HAMLIB_PROFILE: local,
            network.REMOTE_HAMLIB_PROFILE: hamlib, network.TCI_PROFILE: tci_panel,
        }
        footer = ttk.Frame(frame)
        footer.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.widget(ttk.Button, footer, text="Обновить устройства", command=self.refresh).pack(side="left")
        self.equipment_done = ttk.Button(footer, style="Primary.TButton",
                                         command=self.finish_equipment)
        self.equipment_done.pack(side="right")
        self.equipment = dialog
        self.profile_changed()

    def profile_changed(self, event=None):
        profile = self.settings["profile"].get()
        for kind, panel in self.profile_panels.items():
            if kind == profile:
                panel.grid()
            else:
                panel.grid_remove()
        modes = tuple(civ.MODES) if profile == network.G90_PROFILE else network.STANDARD_MODES
        self.mode_picker.configure(values=modes)
        if self.mode_entry.get() not in modes:
            self.mode_entry.set("U-D")
        if self.details is not None:
            self.close_details()
        self.cat_log.clear()
        if profile == network.LOCAL_HAMLIB_PROFILE and not (self.hamlib_models or self.hamlib_loading):
            self.load_hamlib_catalog()
        self.update_equipment_button()

    def update_equipment_button(self):
        connect = self.settings["profile"].get() == network.LOCAL_HAMLIB_PROFILE and self.session is None
        self.equipment_done.configure(text=self.tr("Подключить" if connect else "Готово"),
                                      state="disabled" if connect and self.hamlib_loading else "normal")

    def finish_equipment(self):
        self.equipment.withdraw()
        if self.settings["profile"].get() == network.LOCAL_HAMLIB_PROFILE and self.session is None:
            self.toggle_cat()

    def load_hamlib_catalog(self):
        self.hamlib_loading = True
        self.hamlib_hint.set("Подготавливаю Hamlib и список моделей…")

        def lookup(report):
            location = bundled.find_bin()
            report("hamlib_catalog", (location, bundled.catalog(location)))

        self.run("hamlib_catalog", lookup)

    def filter_hamlib_models(self, event=None):
        needle = self.settings["hamlib_model"].get().strip().casefold()
        if needle in {label.casefold() for label in self.hamlib_models}:
            needle = ""
        labels = [label for label in self.hamlib_models if needle in label.casefold()]
        self.hamlib_model.configure(values=labels)

    def show_equipment(self):
        self.equipment.deiconify()
        self.equipment.lift()
        self.equipment.focus_set()

    def show_details(self):
        if self.details is not None:
            self.details.lift()
            return
        self.details = tk.Toplevel(self.root, background=theme.BG)
        self.details.transient(self.root)
        self.reflect(self.details, self.details.title, "CW Rig Desk · Показания и журнал CAT")
        self.details.geometry("780x560")
        self.details.minsize(620, 380)
        self.details.protocol("WM_DELETE_WINDOW", self.close_details)
        surface = ttk.Frame(self.details, style="Card.TFrame", padding=16)
        surface.pack(fill="both", expand=True, padx=10, pady=10)
        self.widget(ttk.Label, surface, text="Телеметрия CAT", style="Heading.TLabel").pack(anchor="w", pady=(0, 9))
        tabs = ttk.Notebook(surface)
        tabs.pack(fill="both", expand=True)
        readings = ttk.Frame(tabs)
        log = ttk.Frame(tabs)
        tabs.add(readings)
        self.reflect(tabs, lambda title: tabs.tab(readings, text=title), "Показания")
        direct = self.settings["profile"].get() == network.G90_PROFILE
        tabs.add(log)
        self.reflect(tabs, lambda title: tabs.tab(log, text=title), "Кадры CI-V" if direct else "Журнал соединения")
        columns = ("label", "value", "command") if direct else ("label", "value")
        self.cat_table = ttk.Treeview(readings, columns=columns, show="headings")
        for column, label, width in (("label", "Показание", 292), ("value", "Значение", 210),
                                     ("command", "Запрос", 100))[:len(columns)]:
            self.reflect(self.cat_table, lambda text, key=column: self.cat_table.heading(key, text=text), label)
            self.cat_table.column(column, width=width)
        self.cat_table.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(readings, command=self.cat_table.yview)
        bar.pack(side="right", fill="y")
        self.cat_table.configure(yscrollcommand=bar.set)
        self.cat_table.tag_configure("even", background=theme.SCREEN)
        self.cat_table.tag_configure("odd", background="#122131")
        rows = ((item.key, item.label, item.command.hex(" ").upper()) for item in civ.READINGS) if direct else (
            (key, title, "") for key, title in network.NETWORK_READINGS
        )
        for index, (key, title, command) in enumerate(rows):
            stripe = "odd" if index % 2 else "even"
            table = self.cat_table
            table.insert("", "end", iid=key, tags=(stripe,), values=("", "—", command))
            self.reflect(table, lambda text, row=key: table.set(row, "label", text), title)
        for key, value in self.cat_values.items():
            self.update_reading(key, value)
        self.cat_log_view = self.console_text(log)
        self.cat_log_view.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(log, command=self.cat_log_view.yview)
        bar.pack(side="right", fill="y")
        self.cat_log_view.configure(yscrollcommand=bar.set)
        self.cat_log_view.insert("end", "".join(self.cat_log))
        self.cat_log_view.see("end")
        self.cat_log_view.configure(state="disabled")

    def close_details(self):
        self.details.destroy()
        self.details = None

    def add_frame(self, frame):
        direction, packet = frame
        payload = packet.hex(" ").upper() if isinstance(packet, bytes) else packet
        line = f"{direction}  {payload}\n"
        self.cat_log.append(line)
        if self.details is not None:
            self.cat_log_view.configure(state="normal")
            self.cat_log_view.insert("end", line)
            if int(self.cat_log_view.index("end-1c").split(".")[0]) > 801:
                self.cat_log_view.delete("1.0", "2.0")
            self.cat_log_view.see("end")
            self.cat_log_view.configure(state="disabled")

    def update_reading(self, key, value):
        self.cat_values[key] = value
        label = "—" if value is None else str(value)
        if key in ("frequency", "other_frequency") and value is not None:
            label = f"{value:,} Гц".replace(",", " ")
        if key == "mode" and value is not None:
            mode, group = value
            if isinstance(group, str):
                label = f"{mode} · {group}"
            else:
                label = f"{mode} · FIL{group}" if group in (1, 2, 3) else mode
        if key == "frequency":
            self.frequency_digits.set(label.removesuffix(" Гц"))
            self.update_band_buttons(value)
        elif key == "swr_live":
            label, marker, _ = value[0].partition(" · посл.") if value is not None else ("—", "", "")
            self.swr_note.set("Последний замер" if marker else "")
        elif key == "split":
            self.split_display.set(f"SPLIT · {self.tr(label).lower()}" if value is not None else "SPLIT —")
        elif key == "ptt":
            if label.startswith("TX"):
                self.radio_state.configure(style="TransmitBadge.TLabel")
            elif label.startswith("RX"):
                self.radio_state.configure(style="ReceiveBadge.TLabel")
            else:
                self.radio_state.configure(style="RadioBadge.TLabel")
        elif key == "smeter":
            self.draw_smeter()
            if self.settings["profile"].get() == network.G90_PROFILE:
                self.signal_display.set(reading_text(label, self.settings["language"].get()))
        elif key == "signal":
            self.signal_display.set(reading_text(label, self.settings["language"].get()))
        label = reading_text(label, self.settings["language"].get())
        if key in self.cat_display:
            self.cat_display[key].set(label)
        if self.details is not None and self.cat_table.exists(key):
            self.cat_table.set(key, "value", label)

    def update_band_buttons(self, frequency):
        for band, low, high, _ in HF_BANDS:
            selected = frequency is not None and low <= frequency <= high
            self.band_buttons[band].state(["selected" if selected else "!selected"])
            if selected:
                self.band_frequencies[band] = frequency

    def update_cat_buttons(self):
        configurable = self.session is None
        self.ports.configure(state="readonly" if configurable else "disabled")
        for field in (self.cat_address, self.hamlib_host, self.hamlib_port, self.tci_url, self.hamlib_model):
            field.configure(state="normal" if configurable else "disabled")
        for field in (self.profile_selector, self.tci_receiver, self.hamlib_device, self.hamlib_baud):
            field.configure(state="readonly" if configurable else "disabled")
        self.update_equipment_button()
        self.cat_button.configure(
            text=self.tr("Подключить CAT" if configurable else "Отключить CAT"),
            style="Primary.TButton" if configurable else "TButton",
        )
        self.link_label.configure(style="LinkReady.TLabel" if self.cat_ready else "Link.TLabel")
        self.cat_button.state(["disabled" if self.tx_running or self.closing else "!disabled"])
        self.tx_devices.configure(state="disabled" if self.tx_running else "readonly")
        available = (self.cat_ready and self.cat_values.get("ptt") not in ("TX", "TX · CAT")
                     and not (self.tx_running or self.cat_writing or self.closing))
        for widget, state in self.cat_controls:
            widget.configure(state=state if available else "disabled")

    def toggle_cat(self):
        if self.session is not None:
            if self.tx_running:
                return
            self.cat_ready = False
            self.armed.set(False)
            self.cat_status.set("Отключение CAT…")
            if self.rx_uses_tci:
                self.stop_rx()
            self.cat_stop.set()
            self.update_tx_buttons()
            self.update_cat_buttons()
            return
        try:
            profile = self.settings["profile"].get()

            def report(kind, data):
                self.events.put((kind, data))

            if profile == network.G90_PROFILE:
                port = self.settings["port"].get()
                if port not in self.ports_found:
                    raise ValueError("Выберите COM-порт Xiegu G90.")
                try:
                    address = int(self.settings["address"].get(), 16)
                    if not 1 <= address <= 0xDF:
                        raise ValueError
                except ValueError:
                    raise ValueError("Введите адрес CI-V в hex, например 70 или 88.") from None
                self.session = civ.CatSession(port, address, report)
            elif profile == network.LOCAL_HAMLIB_PROFILE:
                if not self.hamlib_models:
                    if not self.hamlib_loading:
                        self.load_hamlib_catalog()
                    raise ValueError("Дождитесь загрузки списка моделей Hamlib.")
                label = self.settings["hamlib_model"].get().strip()
                model = self.hamlib_models.get(label)
                if model is None:
                    raise ValueError("Выберите модель трансивера из списка Hamlib.")
                port = bundled.resolve_serial(model.id, self.settings["hamlib_device"].get(), list_ports.comports())
                speed = self.settings["hamlib_baud"].get()
                baud = None if speed == bundled.AUTO else self.read_number("hamlib_baud", "Скорость CAT", 1, 1_000_000)
                self.session = network.NetworkSession(
                    lambda publish, log: bundled.ManagedHamlib(
                        self.hamlib_bin / "rigctld.exe", model.id, port, baud, publish, log, self.cat_stop
                    ),
                    f"Hamlib · {model.name}" + (f" / {port}" if port else ""), report,
                )
            elif profile == network.REMOTE_HAMLIB_PROFILE:
                host = self.settings["hamlib_host"].get().strip()
                port = self.read_number("hamlib_port", "Порт rigctld", 1, 65535)
                if not host or any(ch.isspace() or ch in "/@" for ch in host):
                    raise ValueError("Укажите имя или IP-адрес сервера rigctld.")
                self.session = network.NetworkSession(
                    lambda publish, log: network.Hamlib(host, port, publish, log),
                    f"Hamlib · {host}:{port}", report,
                )
            else:
                endpoint = self.settings["tci_url"].get().strip()
                uri = urlsplit(endpoint)
                if (uri.scheme not in ("ws", "wss") or not uri.hostname or
                        uri.username or uri.password or uri.fragment or not uri.port or
                        any(ch.isspace() for ch in endpoint)):
                    raise ValueError("Укажите адрес TCI, например ws://127.0.0.1:40001.")
                receiver = int(self.settings["tci_receiver"].get())
                self.session = network.NetworkSession(
                    lambda publish, log: network.Tci(endpoint, receiver, publish, log),
                    f"TCI · {uri.hostname}:{uri.port} / RX{receiver+1}", report,
                )
        except (ValueError, OSError) as error:
            self.show_equipment()
            self.notify(messagebox.showwarning, "CAT", error_text(error), parent=self.equipment)
            return
        self.cat_stop.clear()
        self.cat_status.set("Подключение…")
        self.update_cat_buttons()
        self.run("cat", lambda report: self.session.run(self.cat_stop))

    def set_frequency(self):
        try:
            value = int(self.frequency_entry.get().replace(" ", ""))
            if self.settings["profile"].get() == network.G90_PROFILE:
                civ.frequency_field(value)
            elif not 1 <= value <= 99_999_999_999:
                raise ValueError
        except ValueError:
            direct = self.settings["profile"].get() == network.G90_PROFILE
            text = ("Введите частоту в Гц от 500 000 до 30 000 000." if direct
                    else "Введите положительную целую частоту в Гц.")
            self.notify(messagebox.showwarning, "CAT", text, parent=self.root)
            return
        self.write_cat("frequency", value)

    def write_cat(self, command, value):
        if (not self.cat_ready or self.tx_running or self.cat_writing or self.closing or
                self.cat_values.get("ptt") in ("TX", "TX · CAT")):
            return
        self.cat_writing = True
        self.cat_status.set("Отправка команды CAT…")
        self.update_cat_buttons()
        self.update_tx_buttons()
        self.session.jobs.put((command, (value,)))

    def output_changed(self, event):
        if not self.tx_running and self.armed.get():
            self.armed.set(False)
            self.arm_changed()

    def combo(self, parent, key, row, column, values=(), width=25):
        widget = ttk.Combobox(parent, textvariable=self.settings[key], state="readonly",
                              values=values, width=width)
        widget.grid(row=row, column=column, sticky="ew", pady=(3, 0))
        return widget

    def number(self, parent, label, key, column, low, high, step=1):
        self.widget(ttk.Label, parent, text=label, style="Hint.TLabel").grid(
            row=0, column=column, sticky="w", padx=(0, 9)
        )
        ttk.Spinbox(parent, textvariable=self.settings[key], from_=low, to=high,
                    increment=step, width=6).grid(
            row=1, column=column, padx=(0, 9), pady=(3, 0), sticky="w"
        )

    def read_number(self, key, label, low, high):
        try:
            value = int(self.settings[key].get())
        except ValueError:
            raise ValueError(Message("{label} — введите число от {low} до {high}.", label=Message(label), low=low, high=high)) from None
        if not low <= value <= high:
            raise ValueError(Message("{label} — введите число от {low} до {high}.", label=Message(label), low=low, high=high))
        return value

    def refresh(self):
        if self.rx_running or self.tx_running:
            self.notify(messagebox.showinfo, "Устройства", "Остановите приём и передачу перед обновлением.",
                                parent=self.root)
            return
        try:
            self.inputs, self.outputs, ports = radio.devices()
            self.ports_found = ports
        except Exception as error:
            self.rx_status.set(Message("Ошибка списка устройств: {error}", error=error_text(error)))
            return
        choices = [("input", self.rx_devices, self.inputs), ("output", self.tx_devices, self.outputs)]
        if self.session is None:
            choices.append(("port", self.ports, ports))
            self.refresh_hamlib_ports()
        for key, widget, values in choices:
            widget.configure(values=tuple(values))
            if self.settings[key].get() not in values:
                self.settings[key].set("")
        self.armed.set(False)
        self.tx_status.set("Передача отключена")
        self.update_tx_buttons()

    def rx_settings(self):
        return {
            "pitch": self.read_number("pitch", "Тон", 300, 1200),
            "wpm": self.read_number("rx_wpm", "Скорость RX", 6, 35),
            "sensitivity_db": self.read_number("sensitivity", "Порог", -65, -8),
            "alphabet": self.settings["alphabet"].get(),
            "adaptive": self.settings["adaptive"].get(),
            "auto_pitch": self.settings["auto_pitch"].get(),
            "bandwidth_hz": CW_FILTERS[self.settings["cw_filter"].get()],
        }

    def change_rx_filter(self, event):
        if self.rx_running and not self.rx_stop.is_set():
            self.rx_filter_updates.put(CW_FILTERS[self.settings["cw_filter"].get()])

    def update_rx_buttons(self):
        self.rx_start_button.state(["disabled" if self.rx_running or self.closing else "!disabled"])
        can_stop = self.rx_running and not self.rx_stop.is_set() and not self.closing
        self.rx_stop_button.state(["!disabled" if can_stop else "disabled"])
        self.tci_audio_choice.state(["disabled" if self.rx_running else "!disabled"])

    def start_rx(self):
        if self.rx_running or self.closing:
            return
        try:
            settings = self.rx_settings()
            via_tci = self.settings["profile"].get() == network.TCI_PROFILE and self.settings["tci_audio"].get()
            if via_tci:
                rig = getattr(self.session, "driver", None)
                if not self.cat_ready or not isinstance(rig, network.Tci):
                    raise ValueError("Сначала подключите CAT по TCI.")
                source = (rig.url, int(rig.receiver))
            else:
                source = self.inputs.get(self.settings["input"].get())
                if not source:
                    self.show_equipment()
                    self.notify(messagebox.showwarning, "Приём", "Выберите аудиоустройство «Вход RX».",
                                parent=self.equipment)
                    return
        except ValueError as error:
            self.notify(messagebox.showwarning, "Приём", error_text(error), parent=self.root)
            return
        self.rx_running = True
        self.rx_uses_tci = via_tci
        self.rx_stop.clear()
        self.rx_filter_updates = queue.SimpleQueue()
        self.update_rx_buttons()
        self.rx_status.set("Ожидание аудио RX по TCI…" if via_tci else "Открываю аудиовход…")
        self.run("rx", radio.receive_tci if via_tci else radio.receive, source, settings, self.rx_stop, self.tx_active,
                 self.rx_filter_updates)

    def stop_rx(self):
        if self.rx_running and not self.rx_stop.is_set():
            self.rx_stop.set()
            self.update_rx_buttons()
            self.rx_status.set("Останавливаю приём…")

    def demo(self):
        try:
            self.run("demo", radio.demo, self.rx_settings())
        except ValueError as error:
            self.notify(messagebox.showwarning, "Демо", error_text(error), parent=self.root)

    def run(self, name, action, *args):
        def report(event, data):
            self.events.put((event, data))

        def worker():
            error = None
            try:
                action(*args, report)
            except Exception as exc:
                error = error_text(exc)
            finally:
                report(f"{name}_done", error)

        threading.Thread(target=worker, daemon=(name != "cat")).start()

    def append(self, text):
        self.rx_text.configure(state="normal")
        self.rx_text.insert("end", text)
        if int(self.rx_text.count("1.0", "end", "chars")[0]) > 50_000:
            self.rx_text.delete("1.0", "1.0 + 1000 chars")
        self.rx_text.see("end")
        self.rx_text.configure(state="disabled")

    def clear(self):
        self.rx_text.configure(state="normal")
        self.rx_text.delete("1.0", "end")
        self.rx_text.configure(state="disabled")

    def macro_title(self, index, *, deferred=False):
        title, _ = self.macros[index]
        if self.macros[index] == DEFAULT_MACROS[index]:
            return Message(title) if deferred else self.tr(title)
        return title

    def update_macros(self):
        for index, button in enumerate(self.macro_buttons):
            button.configure(text=self.macro_title(index))

    def use_macro(self, index):
        try:
            message = expand_macro(self.macros[index][1], self.settings["call"].get(),
                                   self.settings["other"].get(), self.settings["rst"].get())
        except ValueError as error:
            self.notify(messagebox.showwarning, "Макрос", error_text(error), parent=self.root)
            return
        self.start_tx(message, self.macro_title(index, deferred=True))

    def edit_macros(self):
        dialog = tk.Toplevel(self.root, background=theme.BG)
        self.reflect(dialog, dialog.title, "Макросы ответа")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.minsize(650, 310)
        frame = ttk.Frame(dialog, style="Card.TFrame", padding=16)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        frame.columnconfigure(1, weight=1)
        self.widget(ttk.Label, frame, text="Макросы CW", style="Heading.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self.widget(ttk.Label, frame, text="{CALL} — мой позывной    {OTHER} — корреспондент    {RST} — рапорт",
                  style="Hint.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 14))
        self.widget(ttk.Label, frame, text="Кнопка", style="Hint.TLabel").grid(row=2, column=0, sticky="w")
        self.widget(ttk.Label, frame, text="Текст для передачи", style="Hint.TLabel").grid(row=2, column=1, sticky="w")
        entries = []
        for row, (_, template) in enumerate(self.macros, start=3):
            name = ttk.Entry(frame, width=13)
            name.insert(0, self.macro_title(row - 3))
            name.grid(row=row, column=0, padx=(0, 8), pady=4)
            body = ttk.Entry(frame, width=58, font=(self.mono_font, 10))
            body.insert(0, template)
            body.grid(row=row, column=1, sticky="ew", pady=4)
            entries.append((name, body))

        def save():
            macros = [[name.get().strip(), body.get().strip()] for name, body in entries]
            for index, row in enumerate(macros):
                if row == [self.macro_title(index), self.macros[index][1]]:
                    macros[index] = self.macros[index]
            try:
                for name, template in macros:
                    if not name:
                        raise ValueError("У каждого макроса должно быть название.")
                    encode_text(expand_macro(template, "TEST", "TEST", "599"))
            except ValueError as error:
                self.notify(messagebox.showwarning, "Макросы", error_text(error), parent=dialog)
                return
            self.macros = macros
            self.update_macros()
            self.save_settings()
            dialog.destroy()

        actions = ttk.Frame(frame)
        actions.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.widget(ttk.Button, actions, text="Сохранить", command=save, style="Primary.TButton").pack(side="right")
        self.widget(ttk.Button, actions, text="Отмена", command=dialog.destroy).pack(side="right", padx=(0, 7))
        dialog.bind("<Escape>", lambda event: dialog.destroy())
        dialog.bind("<Return>", lambda event: save())

    def arm_changed(self):
        if self.armed.get():
            text = ("TX разрешён. Макросы передаются сразу." if self.cat_ready else
                    "Для передачи подключите CAT.")
            self.tx_status.set(text)
        else:
            self.stop_tx()
            if not self.tx_running:
                self.tx_status.set("Передача отключена")
        self.update_tx_buttons()

    def update_tx_buttons(self):
        ready = (self.armed.get() and self.cat_ready
                 and self.cat_values.get("ptt") not in ("TX", "TX · CAT")
                 and not (self.tx_running or self.cat_writing or self.closing))
        for widget in (self.send_button, *self.macro_buttons):
            widget.state(["!disabled" if ready else "disabled"])
        self.stop_button.state(["!disabled" if self.tx_running else "disabled"])

    def send(self):
        self.start_tx(self.tx_text.get("1.0", "end-1c"))
        return "break"

    def start_tx(self, text, title=None):
        if (self.tx_running or not self.armed.get() or not self.cat_ready or
                self.cat_writing or self.closing or self.cat_values.get("ptt") in ("TX", "TX · CAT")):
            return
        try:
            device = self.outputs.get(self.settings["output"].get())
            if not device:
                self.show_equipment()
                self.notify(messagebox.showwarning, "Передача", "Выберите аудиоустройство «Выход TX».",
                                       parent=self.equipment)
                return
            if len(text) > 600:
                raise ValueError("Сократите сообщение до 600 символов.")
            words = encode_text(text)
            pitch = self.read_number("pitch", "Тон", 300, 1200)
            wpm = self.read_number("tx_wpm", "Скорость TX", 6, 35)
            gain = self.read_number("level", "Выход", 1, 60) / 100
            lead = self.read_number("lead", "Пауза PTT", 0, 1000) / 1000
        except ValueError as error:
            self.notify(messagebox.showwarning, "Передача", error_text(error), parent=self.root)
            return
        self.tx_running = True
        self.tx_cancel.clear()
        self.tx_active.set()
        self.tx_status.set(Message("Запуск макроса «{title}»…", title=title) if title else "Запуск передачи…")
        self.update_tx_buttons()
        self.update_cat_buttons()
        self.session.jobs.put(("tx", (radio.transmit, device, words, pitch, wpm,
                                      gain, lead, self.tx_cancel)))

    def stop_tx(self):
        if self.tx_running:
            self.tx_cancel.set()
            self.tx_status.set("Останавливаю передачу…")
        return "break"

    def poll(self):
        for _ in range(80):
            try:
                event, data = self.events.get_nowait()
            except queue.Empty:
                break
            if event == "cat_frame":
                self.add_frame(data)
            elif event == "hamlib_catalog":
                self.hamlib_bin, models = data
                self.hamlib_models = {model.label: model for model in models}
                self.filter_hamlib_models()
                self.hamlib_hint.set("Выберите модель. Порт и скорость можно оставить в режиме «Авто».")
            elif event == "hamlib_catalog_done":
                self.hamlib_loading = False
                if data:
                    self.hamlib_hint.set(data)
                self.update_equipment_button()
            elif event == "cat_ready" and not self.closing and not self.cat_stop.is_set():
                self.cat_ready = True
                self.cat_link = data
                self.cat_status.set(data)
                if self.armed.get():
                    self.arm_changed()
                self.update_cat_buttons()
                self.update_tx_buttons()
            elif event == "cat_value":
                self.update_reading(*data)
                if data[0] == "ptt":
                    self.update_cat_buttons()
                    self.update_tx_buttons()
            elif event == "cat_write_done":
                self.cat_writing = False
                self.cat_status.set(self.cat_link)
                self.update_cat_buttons()
                self.update_tx_buttons()
                if data and not self.closing:
                    self.notify(messagebox.showwarning, "CAT", data, parent=self.root)
            elif event == "cat_done":
                if self.rx_uses_tci:
                    self.stop_rx()
                self.session = None
                self.cat_ready = self.cat_writing = False
                self.armed.set(False)
                self.tx_running = False
                self.tx_active.clear()
                for key in tuple(self.cat_values):
                    self.update_reading(key, None)
                self.cat_values.clear()
                self.cat_status.set("CAT отключён")
                self.tx_status.set("Передача отключена")
                self.update_cat_buttons()
                self.update_tx_buttons()
                if data and not self.closing:
                    self.notify(messagebox.showerror, "CAT", data, parent=self.root)
            elif event == "text":
                self.append(data)
            elif event == "meter" and not self.rx_stop.is_set():
                db, speed, key, pitch = data
                self.level.set(max(0, min(60, db + 60)))
                mark = Message(" · Тон") if key else ""
                self.rx_status.set(Message("{prefix}{db:.0f} дБFS · {speed:.1f} WPM · {pitch} Гц{mark}",
                                           prefix="TCI RX · " if self.rx_uses_tci else "",
                                           db=db, speed=speed, pitch=pitch, mark=mark))
            elif event == "rx_started" and not self.rx_stop.is_set():
                self.rx_status.set("Приём аудио по TCI" if self.rx_uses_tci else "Приём")
            elif event == "rx_done":
                self.rx_running = False
                self.rx_uses_tci = False
                self.level.set(0)
                self.update_rx_buttons()
                self.rx_status.set("Ошибка аудиовхода" if data else "Приём остановлен")
                if data and not self.closing:
                    self.notify(messagebox.showerror, "Аудиовход", data, parent=self.root)
            elif event == "tx_phase" and not self.tx_cancel.is_set():
                self.tx_status.set(data)
            elif event == "tx_done":
                self.tx_running = False
                self.tx_active.clear()
                if data:
                    self.armed.set(False)
                    self.tx_status.set(data)
                    self.notify(messagebox.showerror, "Передача", data, parent=self.root)
                else:
                    self.tx_status.set("Передача прервана" if self.tx_cancel.is_set()
                                       else "Сообщение передано")
                self.update_tx_buttons()
                self.update_cat_buttons()
            elif event == "demo_text":
                expected, actual = data
                self.append(self.tr(Message("\n[Демо] Передано: {expected}\n[Демо] Принято: {actual}\n",
                                            expected=expected, actual=actual or "—")))
            elif event == "demo_done" and data:
                self.notify(messagebox.showerror, "Демо", data, parent=self.root)
        if self.closing and not self.tx_running:
            self.cat_stop.set()
            if self.session is None:
                self.save_settings()
                self.root.destroy()
                return
        self.root.after(40, self.poll)

    def save_settings(self):
        settings = {key: value.get() for key, value in self.settings.items()}
        settings["macros"] = self.macros
        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            temporary = CONFIG.with_suffix(".tmp")
            temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(CONFIG)
        except OSError as error:
            self.notify(messagebox.showwarning, "Настройки", error_text(error), parent=self.root)

    def close(self):
        self.closing = True
        self.rx_stop.set()
        self.update_rx_buttons()
        self.stop_tx()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
