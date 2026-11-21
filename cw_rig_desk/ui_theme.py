"""Dark radio-console styles for Tk on Windows and Linux."""

from tkinter import font, ttk

BG = "#0a111c"
PANEL = "#131f2e"
SCREEN = "#0c1623"
LINE = "#293a4e"
FIELD = "#0d1826"
BUTTON = "#1d2e41"
TEXT = "#edf4fc"
MUTED = "#9aafc4"
DIM = "#8197ae"
ACCENT = "#52e2cb"
ACCENT_INK = "#08241f"
DANGER = "#f89895"
DANGER_BG = "#49292f"


def configure(root):
    families = set(font.families(root))
    sans = "Segoe UI" if "Segoe UI" in families else "DejaVu Sans"
    mono = "Consolas" if "Consolas" in families else "DejaVu Sans Mono"
    root.configure(background=BG)
    root.option_add("*TCombobox*Listbox.background", FIELD)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", "#254b60")
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=PANEL, foreground=TEXT, font=(sans, 10),
                    bordercolor=LINE, darkcolor=PANEL, lightcolor=PANEL,
                    troughcolor=SCREEN, focuscolor=ACCENT)
    style.configure("Page.TFrame", background=BG)
    style.configure("Card.TFrame", background=PANEL, bordercolor=LINE,
                    borderwidth=1, relief="solid")
    style.configure("Screen.TFrame", background=SCREEN)
    style.configure("TSeparator", background=LINE, darkcolor=LINE, lightcolor=LINE)
    style.configure("Brand.TLabel", background=BG, font=(sans, 23, "bold"))
    style.configure("PageNote.TLabel", background=BG, foreground=MUTED, font=(sans, 9))
    style.configure("Heading.TLabel", font=(sans, 14, "bold"))
    style.configure("Hint.TLabel", foreground=MUTED, font=(sans, 9))
    style.configure("MeterTitle.TLabel", background=SCREEN, foreground=MUTED, font=(sans, 9))
    style.configure("Screen.TLabel", background=SCREEN)
    style.configure("Frequency.TLabel", background=SCREEN, foreground=ACCENT,
                    font=(mono, 34, "bold"))
    style.configure("MeterValue.TLabel", background=SCREEN, font=(mono, 15, "bold"))
    style.configure("RadioBadge.TLabel", background="#253449", foreground=TEXT,
                    padding=(9, 4), font=(sans, 9, "bold"))
    style.configure("ReceiveBadge.TLabel", background="#173c37", foreground=ACCENT,
                    padding=(9, 4), font=(sans, 9, "bold"))
    style.configure("TransmitBadge.TLabel", background=DANGER_BG, foreground=DANGER,
                    padding=(9, 4), font=(sans, 9, "bold"))
    style.configure("Link.TLabel", background=BG, foreground=MUTED, font=(sans, 9, "bold"))
    style.configure("LinkReady.TLabel", background=BG, foreground=ACCENT, font=(sans, 9, "bold"))

    style.configure("TButton", background=BUTTON, padding=(9, 6), relief="flat", borderwidth=1)
    style.map("TButton", background=[("disabled", "#172334"), ("pressed", "#24485c"),
                                      ("active", "#29425a")],
              foreground=[("disabled", DIM)], bordercolor=[("focus", ACCENT)])
    style.configure("Control.TButton", width=0)
    style.configure("Band.TButton", width=0, padding=(5, 5))
    style.map("Band.TButton", background=[("selected", "disabled", "#1b3a43"),
                                           ("disabled", "#172334"), ("selected", "#173c37"),
                                           ("pressed", "#24485c"), ("active", "#29425a")],
              foreground=[("disabled", DIM), ("selected", ACCENT)],
              bordercolor=[("focus", ACCENT), ("selected", "#2c6b68")])
    style.configure("Primary.TButton", background=ACCENT, foreground=ACCENT_INK,
                    bordercolor=ACCENT, font=(sans, 10, "bold"), padding=(12, 7))
    style.map("Primary.TButton", background=[("disabled", "#1b3039"), ("pressed", "#32b9a6"),
                                              ("active", "#83f2df")],
              foreground=[("disabled", DIM), ("!disabled", ACCENT_INK)],
              bordercolor=[("focus", TEXT), ("disabled", LINE)])
    style.configure("Stop.TButton", background=DANGER_BG, foreground=DANGER,
                    bordercolor="#694248", padding=(10, 7))
    style.map("Stop.TButton", background=[("disabled", "#182436"), ("pressed", "#663539"),
                                           ("active", "#60383d")])
    style.configure("Macro.TButton", background="#183a42", foreground="#a5f4e5",
                    bordercolor="#2c6b68", font=(sans, 11, "bold"), padding=(8, 8))
    style.map("Macro.TButton", background=[("disabled", "#172837"), ("pressed", "#245e58"),
                                            ("active", "#23514f")],
              bordercolor=[("focus", ACCENT), ("disabled", LINE)])
    for widget in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(widget, fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT,
                        arrowcolor=MUTED, selectbackground="#28556a", selectforeground=TEXT,
                        padding=(6, 5), arrowsize=12)
        style.map(widget, fieldbackground=[("disabled", "#152235"), ("readonly", FIELD)],
                  foreground=[("disabled", DIM), ("readonly", TEXT)],
                  background=[("active", BUTTON), ("readonly", FIELD)],
                  bordercolor=[("focus", ACCENT)])
    style.configure("TCheckbutton", indicatorbackground=FIELD, indicatorforeground=ACCENT_INK)
    style.map("TCheckbutton", indicatorbackground=[("selected", ACCENT)],
              background=[("active", PANEL)], foreground=[("active", TEXT)])
    style.configure("Horizontal.TProgressbar", background=ACCENT, bordercolor=SCREEN,
                    darkcolor=ACCENT, lightcolor=ACCENT, thickness=5)
    style.configure("Vertical.TScrollbar", background=BUTTON, arrowcolor=MUTED,
                    bordercolor=SCREEN, darkcolor=BUTTON, lightcolor=BUTTON, arrowsize=11)
    style.map("Vertical.TScrollbar", background=[("disabled", SCREEN), ("active", "#345168")],
              troughcolor=[("disabled", SCREEN)], arrowcolor=[("disabled", DIM)],
              lightcolor=[("disabled", SCREEN)], darkcolor=[("disabled", SCREEN)])
    style.configure("TNotebook", borderwidth=0, tabmargins=0)
    style.configure("TNotebook.Tab", background=BUTTON, foreground=MUTED, padding=(14, 8))
    style.map("TNotebook.Tab", background=[("selected", SCREEN)], foreground=[("selected", ACCENT)])
    style.configure("Treeview", background=SCREEN, fieldbackground=SCREEN, rowheight=28,
                    foreground=TEXT, borderwidth=0)
    style.configure("Treeview.Heading", background=BUTTON, foreground=MUTED, borderwidth=0,
                    font=(sans, 10, "bold"))
    style.map("Treeview", background=[("selected", "#244b60")], foreground=[("selected", TEXT)])
    return mono
