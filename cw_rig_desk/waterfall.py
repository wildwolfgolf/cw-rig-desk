"""Scrolling audio waterfall with a CW aiming frame."""

from collections import deque

import numpy as np
import tkinter as tk

from . import ui_theme as theme

LOW_DB = -90.0
HIGH_DB = -10.0
BINS = 160
HIGH_HZ = 1600
TICKS = (0, 500, 1000, 1500)


def _palette():
    stops = (
        (0.00, (0, 0, 0)),
        (0.18, (0, 8, 42)),
        (0.38, (0, 66, 132)),
        (0.58, (0, 194, 190)),
        (0.78, (232, 240, 64)),
        (1.00, (255, 255, 255)),
    )
    colors = []
    for index in range(256):
        level = index / 255
        for stop in range(1, len(stops)):
            start_level, start_rgb = stops[stop - 1]
            end_level, end_rgb = stops[stop]
            if level <= end_level:
                span = (level - start_level) / (end_level - start_level)
                rgb = tuple(round(a + (b - a) * span) for a, b in zip(start_rgb, end_rgb))
                break
        else:
            rgb = stops[-1][1]
        colors.append(f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}")
    return np.array(colors)


PALETTE = _palette()


class Waterfall(tk.Canvas):
    """Audio spectrum scrolling downwards with a marker for the decoder tone."""

    def __init__(self, parent, *, font=None, high=HIGH_HZ, bins=BINS,
                 history_seconds=6.0, interval=0.06, **options):
        super().__init__(parent, background=theme.SCREEN, highlightthickness=1,
                         highlightbackground=theme.LINE, borderwidth=0, **options)
        self.high = high
        self.bins = bins
        self.font = font
        self.history = deque(maxlen=max(8, round(history_seconds / interval)))
        self.pitch = 0
        self.bandwidth = 0
        self.image = None
        self.base = None
        self.image_item = None
        self.targets = []
        self.job = None
        self.bind("<Configure>", self.schedule)

    def add(self, values):
        self.history.append(np.asarray(values, dtype=np.float32))
        self.schedule()

    def set_target(self, pitch, bandwidth):
        if (pitch, bandwidth) != (self.pitch, self.bandwidth):
            self.pitch, self.bandwidth = int(pitch), int(bandwidth or 0)
            self.schedule()

    def clear(self):
        self.history.clear()
        self.schedule()

    def schedule(self, _event=None):
        if self.job is None:
            self.job = self.after(90, self.draw)

    def draw(self):
        self.job = None
        width = self.winfo_width()
        height = self.winfo_height() - 14
        if width < 16 or height < 16:
            return
        if self.history:
            rows = np.vstack(tuple(self.history))
            small_width = max(8, round(width / 3))
            small_height = max(8, round(height / 3))
            x_index = np.linspace(0, self.bins - 1, small_width).astype(int)
            y_index = np.linspace(0, rows.shape[0] - 1, small_height).astype(int)
            levels = (rows[y_index][:, x_index] - LOW_DB) * 255.0 / (HIGH_DB - LOW_DB)
            levels = np.clip(levels, 0, 255).astype(np.uint8)
            colors = PALETTE[levels]
            data = " ".join("{" + " ".join(row) + "}" for row in colors)
            if self.base is None or self.base.width() != small_width or self.base.height() != small_height:
                self.base = tk.PhotoImage(width=small_width, height=small_height)
            self.base.put(data)
            self.image = self.base.zoom(3)
            if self.image_item is None:
                self.image_item = self.create_image(0, 0, image=self.image, anchor="nw")
            else:
                self.itemconfigure(self.image_item, image=self.image)
            self.tag_lower(self.image_item)
        self.draw_target(width, height)

    def draw_target(self, width, height):
        for item in self.targets:
            self.delete(item)
        self.targets = []
        if not self.pitch:
            return

        def position(frequency):
            return max(0.0, min(width - 1.0, frequency / self.high * (width - 1)))

        center = position(self.pitch)
        half = max(self.bandwidth, 100) / 2
        left, right = position(self.pitch - half), position(self.pitch + half)
        options = dict(fill=theme.MUTED, dash=(2, 4))
        self.targets.extend((
            self.create_line(left, 0, left, height, **options),
            self.create_line(right, 0, right, height, **options),
            self.create_line(left, 0, right, 0, fill=theme.MUTED),
            self.create_line(left, height - 1, right, height - 1, fill=theme.MUTED),
        ))
        self.targets.extend((
            self.create_line(center, 0, center, height, fill=theme.ACCENT, width=1),
            self.create_line(center - 6, 6, center + 6, 6, fill=theme.ACCENT),
            self.create_text(center + 7, 3, text=str(self.pitch), anchor="nw",
                             fill=theme.ACCENT, font=self.font),
        ))
        for frequency in TICKS:
            if frequency > self.high:
                continue
            x = position(frequency)
            self.targets.append(self.create_line(x, height - 3, x, height, fill=theme.MUTED))
            self.targets.append(self.create_text(x, height + 1, text=str(frequency), anchor="n",
                                                 fill=theme.MUTED, font=self.font))
