import math
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import simpledialog, messagebox, scrolledtext
from pathlib import Path

from core import config

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import psutil
except ImportError:
    psutil = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    from skills.voice.voice_interface import listen, speak
except ImportError:
    listen = None
    speak = None

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    Image = None
    ImageDraw = None
    ImageTk = None

ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
BACKGROUND_IMAGE = ASSETS_DIR / "ai_core.png"
AVATAR_IMAGE = ASSETS_DIR / "angelique_avatar.png"


def _get_resampling_filter():
    if Image is None:
        return None
    resampling = getattr(Image, "Resampling", None)
    if resampling is not None:
        for name in ("LANCZOS", "BILINEAR", "BICUBIC", "BOX", "HAMMING", "NEAREST"):
            value = getattr(resampling, name, None)
            if value is not None:
                return value
    return getattr(Image, "LANCZOS", None) or getattr(Image, "Resampling", None)


class AngeliqueDesktopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        # Acquire session lock for GUI mode. If another session exists, exit.
        try:
            from core.session_lock import acquire_lock, release_lock, read_lock
        except Exception:
            acquire_lock = None
            release_lock = None
            read_lock = None

        self._release_lock = release_lock
        if acquire_lock:
            ok = acquire_lock("gui")
            if not ok:
                existing = read_lock() if read_lock is not None else None
                mode = existing.get("mode") if existing else "unknown"
                print(f"Another Angelique session is already running (mode={mode}). Exiting GUI.")
                self.destroy()
                return
        self._theme_name = "blue"
        self._themes = {
            "blue": {
                "bg": "#050a12",
                "panel": "#08111f",
                "panel_alt": "#0c2234",
                "text": "#c9f7ff",
                "accent": "#7ef3ff",
                "button_bg": "#132441",
                "button_active": "#0a263c",
                "title_bg": "#03070f",
                "border": "#0d3b55",
            }
        }
        # Animation and ring HUD state (ensure initialized before UI build)
        self._animation_phase = 0.0
        self._scanner_angle = 0
        self._glow_items = []
        self._scanner_item = None
        self._scanner_dot = None
        self._avatar_canvas_id = None
        self._avatar_text_id = None
        # Ensure commonly-referenced GUI attributes exist to avoid
        # AttributeError when parts of the UI reference them before
        # they are created during runtime. Only set if not already present.
        _defaults = {
            "_mt5_data_badge_var": None,
            "_mt5_data_badge_label": None,
            "_last_account_error": None,
            "_last_account": {},
            "_account_labels": {},
            "_gui_settings": {},
            "_mt5_raw_text": None,
            "_bridge_manager": None,
            "_mode_label": None,
            "_avatar_image": None,
            "_avatar_photo": None,
            "_avatar_size_cached": 0,
            "_bg_image_id": None,
            "_bg_overlay_id": None,
            "_is_online": None,
            "_network_status_locked": False,
            "_trading_chart_view_count": 80,
            "_trading_chart_view_offset": 0,
            "_chart_selection_rect_id": None,
            "_last_chart_data": None,
            "_chart_tooltip": None,
            "_last_full_candles": None,
            "_trading_status_var": None,
            "_trading_detail_var": None,
            "_ticker_index": 0,
            "_ticker_labels": [],
            "_scan_line_ids": [],
            "_system_stats": {
                "cpu": 0,
                "memory": 0,
                "network_mbps": 0.0,
                "temperature": "N/A",
                "status": "READY",
            },
        }
        for _k, _v in _defaults.items():
            if not hasattr(self, _k):
                setattr(self, _k, _v)
        
        self._is_online = None
        self._network_status_locked = False
        self._mode_label = None
        self._avatar_size_cached = 0
        self._active_center_view = "home"
        self.center_title_label = None
        self.center_status_label = None
        self.ring_canvas = None
        self.trading_view_frame = None
        self.trading_status_var = None
        self.trading_detail_var = None

        self._mission_status_generators = [
            lambda s: f"CPU {s['cpu']}%  |  MEMORY {s['memory']}%",
            lambda s: f"NETWORK {s['network_mbps']:.1f} Mbps  |  STATUS {s['status']}",
            lambda s: f"TEMP {s['temperature']}°C  |  UPTIME {s['uptime']}",
            lambda s: "SYSTEM STATUS: LIVE DATA FEED ACTIVE",
        ]
        self._ticker_index = 0
        if psutil:
            psutil.cpu_percent(interval=None)
            net = psutil.net_io_counters()
            self._last_network_bytes = net.bytes_sent + net.bytes_recv
            self._last_network_time = time.time()

        self._build_ui()
        self._register_shell_callbacks()
        try:
            self.state("zoomed")
        except tk.TclError:
            self.attributes("-fullscreen", True)
        self.attributes("-topmost", False)
        self._bind_events()
        self._initialize_runtime()
        self._update_system_metrics()
        self._refresh_trading_bridge_status()
        self._append_console("SYSTEM", "Angelique desktop matrix initialized. Live system data is now active.")

        # Chart state
        self._trading_chart_view_count = 80
        self._trading_chart_view_offset = 0
        self._chart_selection_rect_id = None
        self._last_chart_data = None
        self._chart_tooltip = None

    def _build_ui(self):
        self.canvas = tk.Canvas(self, bg=self._theme("bg"), highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self._load_images()
        self._create_frames()
        self._update_background()
        self._apply_theme()

        self.canvas.lower("all")

    def _create_title_bar(self):
        self.overrideredirect(True)
        self.title_bar = tk.Frame(self, bg=self._theme("title_bg"), height=40)
        self.title_bar.place(relx=0, rely=0, relwidth=1)
        self.title_bar.lift()

        title_label = tk.Label(
            self.title_bar,
            text="ANGELIQUE | SYNTHESIS CORE",
            fg=self._theme("accent"),
            bg=self._theme("title_bg"),
            font=("Consolas", 11, "bold"),
        )
        title_label.place(x=18, y=10)
        title_label.bind("<Double-Button-1>", lambda event: self._toggle_maximize())
        title_label.bind("<ButtonPress-1>", self._start_move)
        title_label.bind("<B1-Motion>", self._do_move)

        self.title_bar.bind("<ButtonPress-1>", self._start_move)
        self.title_bar.bind("<B1-Motion>", self._do_move)

        button_frame = tk.Frame(self.title_bar, bg=self._theme("title_bg"))
        button_frame.place(relx=0.98, y=4, anchor="ne")

        self._create_title_bar_button(button_frame, "—", self._minimize_window)
        self._create_title_bar_button(button_frame, "❐", self._toggle_maximize)
        self._create_title_bar_button(button_frame, "✕", self.on_close)

    def _create_title_bar_button(self, parent, symbol, command):
        button = tk.Button(
            parent,
            text=symbol,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=10,
            pady=4,
            font=("Consolas", 10, "bold"),
            command=command,
        )
        button.pack(side="right", padx=(4, 0))
        return button


    def _create_frames(self):
        self.left_panel = self._create_panel(self._theme("panel"))
        self.center_panel = self._create_panel(self._theme("panel"))
        self.right_panel = self._create_panel(self._theme("panel"))
        self.bottom_panel = self._create_panel(self._theme("panel"))
        self.footer_bar = tk.Frame(self, bg=self._theme("panel"), height=36)

        self.left_panel.place(relx=0.02, rely=0.055, relwidth=0.235, relheight=0.62)
        self.center_panel.place(relx=0.265, rely=0.055, relwidth=0.47, relheight=0.62)
        self.right_panel.place(relx=0.76, rely=0.055, relwidth=0.225, relheight=0.62)
        self.bottom_panel.place(relx=0.02, rely=0.69, relwidth=0.96, relheight=0.25)
        self.footer_bar.place(relx=0, rely=0.95, relwidth=1, height=36)

        self._build_left_panel()
        self._build_center_panel()
        self._build_right_panel()
        self._build_bottom_panel()
        self._build_footer_bar()

    def _create_panel(self, bg_color: str):
        panel = tk.Frame(self, bg=bg_color, bd=1, relief="flat")
        return panel

    def _load_images(self):
        if Image and BACKGROUND_IMAGE.exists():
            try:
                self._background_image = Image.open(BACKGROUND_IMAGE)
            except Exception:
                self._background_image = None
        else:
            self._background_image = None

        if Image and AVATAR_IMAGE.exists():
            try:
                self._avatar_image = Image.open(AVATAR_IMAGE)
            except Exception:
                self._avatar_image = None
        else:
            self._avatar_image = None

    def _build_left_panel(self):
        header = tk.Label(
            self.left_panel,
            text="SYSTEM INTEL",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 14, "bold"),
        )
        header.pack(anchor="nw", padx=20, pady=(18, 12))

        self._temperature_label = self._create_status_row(self.left_panel, "CORE TEMPERATURE", "N/A")
        self._cpu_label = self._create_status_row(self.left_panel, "NEURAL LOAD", "0%")
        self._memory_label = self._create_status_row(self.left_panel, "MEMORY STABILITY", "0%")
        self._network_label = self._create_status_row(self.left_panel, "NETWORK BANDWIDTH", "0 Mbps")

        divider = tk.Frame(self.left_panel, bg=self._theme("border"), height=1)
        divider.pack(fill="x", padx=20, pady=18)

        tk.Label(
            self.left_panel,
            text="ACTIVE SUBSYSTEMS",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 10, "bold"),
        ).pack(anchor="nw", padx=20)

        self._create_subsystem_label(self.left_panel, "Vision Matrix", True)
        self._create_subsystem_label(self.left_panel, "Voice Layer", True)
        self._create_subsystem_label(self.left_panel, "Trading Bridge", False, store_as="trading_bridge")
        self._create_subsystem_label(self.left_panel, "Memory Vault", True)

    def _create_status_row(self, parent, label, value):
        frame = tk.Frame(parent, bg=self._theme("panel"))
        frame.pack(fill="x", padx=20, pady=8)
        tk.Label(
            frame,
            text=label,
            fg=self._theme("text"),
            bg=self._theme("panel"),
            font=("Consolas", 10),
        ).pack(anchor="w")
        value_label = tk.Label(
            frame,
            text=value,
            fg=self._theme("text"),
            bg=self._theme("panel_alt"),
            font=("Consolas", 15, "bold"),
        )
        value_label.pack(anchor="w", pady=(4, 0))
        return value_label

    def _create_subsystem_label(self, parent, label, active, store_as=None):
        frame = tk.Frame(parent, bg=self._theme("panel"))
        frame.pack(fill="x", padx=20, pady=8)
        dot = tk.Canvas(frame, width=12, height=12, bg=self._theme("panel"), highlightthickness=0)
        dot.create_oval(2, 2, 10, 10, fill=self._theme("accent") if active else self._theme("border"), outline="")
        dot.pack(side="left")
        label_widget = tk.Label(
            frame,
            text=label,
            fg=self._theme("accent") if active else self._theme("text"),
            bg=self._theme("panel"),
            font=("Consolas", 11),
        )
        label_widget.pack(side="left", padx=10)
        if store_as == "trading_bridge":
            self._trading_bridge_dot = dot
            self._trading_bridge_status_label = label_widget

    def _build_center_panel(self):
        self.center_title_label = tk.Label(
            self.center_panel,
            text="CORE MATRIX",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 16, "bold"),
        )
        self.center_title_label.pack(anchor="n", pady=(18, 8))

        self.ring_canvas = tk.Canvas(
            self.center_panel,
            bg=self._theme("panel"),
            highlightthickness=0,
        )
        self.ring_canvas.pack(fill="both", expand=True, padx=18, pady=18)
        self.center_panel.bind("<Configure>", self._on_center_panel_resize)
        self._draw_ring_hud()
        self._animate_ring()

        # Avatar will be drawn on the ring canvas for pixel stability
        self.avatar_label = None
        self._update_avatar()

        self.center_status_label = tk.Label(
            self.center_panel,
            text="PRIORITY: HARMONIC SYNTHESIS",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 11),
        )
        self.center_status_label.pack(anchor="s", pady=(16, 20))

        self._build_trading_view()
        self._show_home_view()

    def _build_trading_view(self):
        self.trading_view_frame = tk.Frame(self, bg=self._theme("panel"))
        self.trading_view_frame.place_forget()

        title = tk.Label(
            self.trading_view_frame,
            text="TRADING HUB",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 16, "bold"),
        )
        title.pack(anchor="nw", padx=20, pady=(16, 8))

        self.trading_status_var = tk.StringVar(value="Trading status initializing...")
        status = tk.Label(
            self.trading_view_frame,
            textvariable=self.trading_status_var,
            fg=self._theme("text"),
            bg=self._theme("panel"),
            font=("Consolas", 11),
            justify="left",
            wraplength=1100,
        )
        status.pack(anchor="nw", padx=20, pady=(0, 8))

        self._trading_bridge_error_var = tk.StringVar(value="Bridge status unknown.")
        self._trading_mode_banner_var = tk.StringVar(value="Preparing trading status...")
        bridge_error_label = tk.Label(
            self.trading_view_frame,
            textvariable=self._trading_bridge_error_var,
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 10, "italic"),
            justify="left",
            wraplength=1100,
        )
        bridge_error_label.pack(anchor="nw", padx=20, pady=(0, 8))

        banner_label = tk.Label(
            self.trading_view_frame,
            textvariable=self._trading_mode_banner_var,
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 11, "bold"),
            justify="left",
            wraplength=1100,
        )
        banner_label.pack(anchor="nw", padx=20, pady=(0, 14))
        self._trading_mode_label_widget = banner_label

        # MT5 data availability badge (shows whether real MT5 data is being used)
        self._mt5_data_badge_var = tk.StringVar(value="")
        self._mt5_data_badge_label = tk.Label(
            self.trading_view_frame,
            textvariable=self._mt5_data_badge_var,
            fg="#ffffff",
            bg="#16a34a",
            font=("Consolas", 10, "bold"),
            padx=8,
            pady=3,
            bd=0,
            relief="flat",
        )
        try:
            # pack to the right side of the header area
            self._mt5_data_badge_label.pack(anchor="ne", padx=20, pady=(0, 14))
        except Exception:
            self._mt5_data_badge_label.pack(anchor="nw", padx=20, pady=(0, 14))
        # Tooltip: show raw bridge error on hover
        self._mt5_tooltip = None
        self._mt5_data_badge_label.bind("<Enter>", lambda e: self._show_mt5_tooltip(e))
        self._mt5_data_badge_label.bind("<Leave>", lambda e: self._hide_mt5_tooltip(e))

        self.trading_detail_var = tk.StringVar(value="Awaiting trading actions...")
        detail_label = tk.Label(
            self.trading_view_frame,
            textvariable=self.trading_detail_var,
            fg=self._theme("text"),
            bg=self._theme("panel"),
            font=("Consolas", 11, "italic"),
            justify="left",
            wraplength=1100,
        )
        detail_label.pack(anchor="nw", padx=20, pady=(0, 12))

        timeframe_frame = tk.Frame(self.trading_view_frame, bg=self._theme("panel"))
        timeframe_frame.pack(anchor="nw", padx=20, pady=(0, 14))

        tk.Label(
            timeframe_frame,
            text="Symbol:",
            fg=self._theme("text"),
            bg=self._theme("panel"),
            font=("Consolas", 10, "bold"),
        ).pack(side="left", padx=(0, 8))
        symbols = self._get_market_symbols()
        self._symbol_var = tk.StringVar(value=symbols[0] if symbols else config.DEFAULT_TRADING_SYMBOL)
        self._symbol_var.trace_add("write", lambda *args: self._refresh_trading_view())
        symbol_menu = tk.OptionMenu(timeframe_frame, self._symbol_var, *symbols)
        symbol_menu.configure(
            bg=self._theme("button_bg"),
            fg=self._theme("text"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            highlightthickness=0,
            font=("Consolas", 10),
        )
        symbol_menu.pack(side="left", padx=(0, 16))

        tk.Label(
            timeframe_frame,
            text="Timeframe:",
            fg=self._theme("text"),
            bg=self._theme("panel"),
            font=("Consolas", 10, "bold"),
        ).pack(side="left", padx=(0, 8))
        self._timeframe_var = tk.StringVar(value=config.DEFAULT_TRADING_TIMEFRAME)
        self._timeframe_var.trace_add("write", lambda *args: self._refresh_trading_view())
        timeframe_options = config.TRADING_TIMEFRAMES
        timeframe_menu = tk.OptionMenu(timeframe_frame, self._timeframe_var, *timeframe_options)
        timeframe_menu.configure(
            bg=self._theme("button_bg"),
            fg=self._theme("text"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            highlightthickness=0,
            font=("Consolas", 10),
        )
        timeframe_menu.pack(side="left", padx=(0, 16))

        tk.Label(
            timeframe_frame,
            text="Account:",
            fg=self._theme("text"),
            bg=self._theme("panel"),
            font=("Consolas", 10, "bold"),
        ).pack(side="left", padx=(0, 8))
        account_mode = self._gui_settings.get("account_mode", "demo")
        self._account_mode_var = tk.StringVar(value=account_mode)
        account_mode_menu = tk.OptionMenu(
            timeframe_frame,
            self._account_mode_var,
            "demo",
            "real",
            command=self._on_account_mode_change,
        )
        account_mode_menu.configure(
            bg=self._theme("button_bg"),
            fg=self._theme("text"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            highlightthickness=0,
            font=("Consolas", 10),
        )
        account_mode_menu.pack(side="left")

        dashboard_container = tk.Frame(self.trading_view_frame, bg=self._theme("panel"))
        dashboard_container.pack(fill="both", expand=True, padx=20, pady=(0, 14))

        account_frame = tk.Frame(dashboard_container, bg=self._theme("panel"), bd=1, relief="solid")
        account_frame.pack(side="left", fill="y", padx=(0, 12), pady=0)
        tk.Label(
            account_frame,
            text="ACCOUNT SUMMARY",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 12, "bold"),
        ).pack(anchor="nw", padx=14, pady=(14, 6))

        for label in ["Balance", "Equity", "Free Margin", "Margin Level", "Leverage", "Currency"]:
            container = tk.Frame(account_frame, bg=self._theme("panel"))
            container.pack(fill="x", padx=14, pady=6)
            tk.Label(
                container,
                text=f"{label}",
                fg=self._theme("text"),
                bg=self._theme("panel"),
                font=("Consolas", 10),
            ).pack(anchor="w")
            value_label = tk.Label(
                container,
                text="—",
                fg=self._theme("accent"),
                bg=self._theme("panel"),
                font=("Consolas", 11, "bold"),
            )
            value_label.pack(anchor="w", pady=(2, 0))
            self._account_labels[label.lower().replace(" ", "_")] = value_label

        chart_frame = tk.Frame(dashboard_container, bg=self._theme("panel"), bd=1, relief="solid")
        chart_frame.pack(side="left", fill="both", expand=True, pady=0)
        tk.Label(
            chart_frame,
            text="MARKET CHART",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 12, "bold"),
        ).pack(anchor="nw", padx=14, pady=(14, 6))

        self.trading_chart_canvas = tk.Canvas(
            chart_frame,
            bg=self._theme("panel_alt"),
            height=520,
            highlightthickness=0,
        )
        self.trading_chart_canvas.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._draw_trading_placeholder_chart()

        # Tooltip widget for OHLC on hover (created as child of canvas so we can use create_window)
        try:
            self._chart_tooltip = tk.Label(self.trading_chart_canvas, bg=self._theme("panel"), fg=self._theme("text"), bd=1, relief="solid", font=("Consolas", 9), padx=6, pady=4)
        except Exception:
            self._chart_tooltip = None

        # Bind mouse events for tooltip and interactions
        try:
            self.trading_chart_canvas.bind("<Motion>", lambda e: self._on_chart_motion(e))
            self.trading_chart_canvas.bind("<Leave>", lambda e: self._hide_chart_tooltip())
            # mouse selection for drag-to-zoom
            self.trading_chart_canvas.bind("<ButtonPress-1>", lambda e: self._on_chart_button_press(e))
            self.trading_chart_canvas.bind("<B1-Motion>", lambda e: self._on_chart_button_motion(e))
            self.trading_chart_canvas.bind("<ButtonRelease-1>", lambda e: self._on_chart_button_release(e))
        except Exception:
            pass

        transcript_frame = tk.Frame(self.trading_view_frame, bg=self._theme("panel"), bd=1, relief="solid")
        transcript_frame.pack(fill="both", expand=True, padx=20, pady=(0, 18))
        tk.Label(
            transcript_frame,
            text="TRADE ACTIVITY LOG",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 12, "bold"),
        ).pack(anchor="nw", padx=14, pady=(14, 6))

        self.trading_transcript_text = scrolledtext.ScrolledText(
            transcript_frame,
            height=6,
            bg=self._theme("bg"),
            fg=self._theme("text"),
            insertbackground=self._theme("text"),
            bd=0,
            highlightthickness=1,
            highlightbackground=self._theme("border"),
            wrap="word",
            font=("Consolas", 10),
        )
        self.trading_transcript_text.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.trading_transcript_text.configure(state="disabled")

        button_row = tk.Frame(self.trading_view_frame, bg=self._theme("panel"))
        button_row.pack(anchor="nw", padx=20, pady=(0, 8))

        self._trade_action_button = tk.Button(
            button_row,
            text="PLAN TRADE",
            command=self._handle_plan_and_execute_trade,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=16,
            pady=10,
            font=("Consolas", 10, "bold"),
        )
        self._trade_action_button.pack(side="left", padx=(0, 12))

        self._back_to_home_button = tk.Button(
            button_row,
            text="BACK TO HOME",
            command=self._show_home_view,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=16,
            pady=10,
            font=("Consolas", 10, "bold"),
        )
        self._back_to_home_button.pack(side="left")

    def _hide_main_panels(self):
        for panel in [self.left_panel, self.center_panel, self.right_panel, self.bottom_panel]:
            if panel is not None:
                try:
                    panel.place_forget()
                except Exception:
                    pass

    def _show_main_panels(self):
        self.left_panel.place(relx=0.02, rely=0.055, relwidth=0.235, relheight=0.62)
        self.center_panel.place(relx=0.265, rely=0.055, relwidth=0.47, relheight=0.62)
        self.right_panel.place(relx=0.76, rely=0.055, relwidth=0.225, relheight=0.62)
        self.bottom_panel.place(relx=0.02, rely=0.69, relwidth=0.96, relheight=0.25)

    def _show_home_view(self):
        self._active_center_view = "home"
        self.center_title_label.configure(text="CORE MATRIX")
        self.center_status_label.configure(text="PRIORITY: HARMONIC SYNTHESIS")
        if self.trading_view_frame is not None:
            self.trading_view_frame.place_forget()
        self._show_main_panels()
        if self.ring_canvas is not None:
            self.ring_canvas.pack(fill="both", expand=True, padx=18, pady=18)
            self.center_status_label.pack(anchor="s", pady=(16, 20))
        self._draw_ring_hud()
        self._update_avatar()

    def _show_trading_view(self):
        self._active_center_view = "trading"
        self.center_title_label.configure(text="TRADING HUB")
        self.center_status_label.configure(text="MODE: LIVE TRADING CO-PILOT")
        if self.ring_canvas is not None:
            self.ring_canvas.pack_forget()
        if self.center_status_label is not None:
            self.center_status_label.pack_forget()
        self._hide_main_panels()
        if self.trading_view_frame is not None:
            self.trading_view_frame.place(relx=0.02, rely=0.055, relwidth=0.96, relheight=0.88)
        self._refresh_trading_view()

    def _refresh_trading_view(self):
        symbol, timeframe = self._get_selected_symbol_and_timeframe()
        account_mode = self._get_selected_account_mode()
        self.trading_status_var.set(
            f"{symbol} • {timeframe} • bridge checking • balance $0.00"
        )
        self.trading_detail_var.set(f"Loading trading data for {symbol} {timeframe}...")
        self._draw_trading_placeholder_chart()
        threading.Thread(target=self._refresh_trading_view_data, args=(symbol, timeframe, account_mode), daemon=True).start()

    def _get_selected_account_mode(self) -> str:
        return (getattr(self, "_account_mode_var", None).get() if getattr(self, "_account_mode_var", None) is not None else "demo")

    def _on_account_mode_change(self, selected_mode: str):
        self._save_gui_settings(account_mode=selected_mode)
        self._refresh_trading_view()

    def _load_gui_settings(self) -> dict:
        try:
            if self._gui_settings_path.exists():
                with open(self._gui_settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _save_gui_settings(self, **values):
        settings = {**(self._gui_settings or {}), **values}
        try:
            os.makedirs(self._gui_settings_path.parent, exist_ok=True)
            with open(self._gui_settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
        except Exception:
            pass
        self._gui_settings = settings

    def _refresh_trading_view_data(self, symbol: str, timeframe: str, account_mode: str):
        bridge_error = None
        account = {}
        market_data = {}
        try:
            from skills.trading.engine.account import get_account_summary
            from skills.trading.engine.connection_manager import bridge_manager
            from skills.trading.market.market_data import market

            account = get_account_summary(account_mode=account_mode)
            active = bridge_manager.get_status()
            if not active:
                bridge_manager.connect()
                active = bridge_manager.get_status()
            bridge_error = account.get("error")
            if not bridge_error and not active:
                bridge_error = bridge_manager.get_last_error()
            market_data = market.get_candles_and_indicators(symbol, timeframe, account_mode=account_mode)

            self.after(0, lambda: self._apply_trading_view_data(symbol, account, market_data, active, bridge_error, account_mode))
        except Exception as exc:
            bridge_error = str(exc)
            self.after(0, lambda: self._apply_trading_view_data(symbol, {}, {}, False, bridge_error, account_mode))

    def _apply_trading_view_data(self, symbol: str, account: dict, market_data: dict, active: bool, bridge_error: str | None, account_mode: str):
        status = "connected" if active else "disconnected"
        balance = account.get("balance", 0)
        # Debug: log full account response to console for tracing UI mismatch issues
        try:
            self._append_console("DEBUG", f"Account response: {account}")
        except Exception:
            pass
        # If user selected live but bridge is disconnected, show explicit offline label and avoid silently showing demo values
        account_mode_match = account.get("mode_match", True)
        actual_mode = account.get("mode")
        display_actual_mode = "real" if actual_mode in ("live", "real") else "demo"
        display_requested_mode = "real" if account_mode in ("live", "real") else "demo"
        actual_login = account.get("login") or "unavailable"

        # If the returned account indicates no login, treat the requested account as unavailable
        if not account.get("login"):
            # Ensure the summary shows zero values for the requested account
            balance = 0
            account = {**(account or {}), "balance": 0, "equity": 0, "free_margin": 0, "margin_level": 0, "login": None}
            if account_mode in ("live", "real"):
                self.trading_status_var.set(f"{symbol} • BRIDGE CONNECTED • REAL ACCOUNT NOT CONNECTED")
            else:
                self.trading_status_var.set(f"{symbol} • bridge {status} • balance ${balance:,.2f}")
            self._update_account_summary(account)
            self._update_trading_mode_banner(account_mode, active, bridge_error, balance, account_mode_match, account_login_exists=False)
            # Keep last account response for badge and diagnostics
            self._last_account = account or {}
            self._last_account_error = account.get("error") or bridge_error
            # No further chart updates for unavailable requested account
            return

        if active and not account_mode_match:
            self.trading_status_var.set(
                f"{symbol} • bridge connected to {display_actual_mode.upper()} account • login {actual_login}"
            )
            bridge_error = f"Bridge is connected to {display_actual_mode.upper()} account, not {display_requested_mode.upper()}."
        elif account_mode in ("live", "real") and not active:
            self.trading_status_var.set(f"{symbol} • BRIDGE OFFLINE • REAL ACCOUNT NOT CONNECTED")
        else:
            self.trading_status_var.set(f"{symbol} • bridge {status} • balance ${balance:,.2f}")

        self._update_account_summary(account)
        self._update_trading_mode_banner(account_mode, active, bridge_error, balance, account_mode_match, account_login_exists=bool(account.get("login")))

        # Keep last account response for badge and diagnostics
        self._last_account = account or {}
        self._last_account_error = account.get("error") or bridge_error

        if isinstance(market_data, dict) and "candles" in market_data and market_data["candles"]:
            self._draw_trading_chart(market_data["candles"])
            self.trading_detail_var.set("Bridge connected and ready.")
        else:
            self._draw_trading_placeholder_chart()
            error_text = market_data.get("error") if isinstance(market_data, dict) else None
            self.trading_detail_var.set(
                f"Market chart unavailable{': ' + error_text if error_text else ''}"
            )

        self._update_bridge_error(bridge_error)

    def _flash_widget(self, widget, cycles=4, interval=250):
        if not widget:
            return
        try:
            orig = widget.cget("bg")
        except Exception:
            orig = self._theme("button_bg")

        def step(count):
            if count <= 0:
                try:
                    widget.configure(bg=orig)
                except Exception:
                    pass
                return
            try:
                widget.configure(bg=self._theme("accent") if count % 2 == 0 else orig)
            except Exception:
                pass
            self.after(interval, lambda: step(count - 1))

        step(cycles)

    def _get_selected_symbol_and_timeframe(self) -> tuple[str, str]:
        symbol = getattr(self, '_symbol_var', None)
        symbol = symbol.get() if symbol is not None else None
        timeframe = getattr(self, '_timeframe_var', None)
        timeframe = timeframe.get() if timeframe is not None else None
        return symbol or config.DEFAULT_TRADING_SYMBOL, timeframe or config.DEFAULT_TRADING_TIMEFRAME

    def _swap_display_mode(self, mode: str | None) -> str:
        mode = (mode or "demo").lower()
        if mode in ("live", "real"):
            return "real"
        if mode == "demo":
            return "demo"
        return mode

    def _update_account_summary(self, account: dict):
        display_mode = account.get("display_mode")
        if not display_mode:
            requested_mode = account.get("requested_mode")
            if requested_mode == "live":
                display_mode = "real"
            elif requested_mode:
                display_mode = requested_mode
            else:
                display_mode = account.get("mode", "demo")
        display_mode = self._swap_display_mode(display_mode)

        if not account or not account.get("login") or (account.get("error") and account.get("mode_match", True) is True):
            values = {
                "balance": 0,
                "equity": 0,
                "free_margin": 0,
                "margin_level": 0,
                "leverage": "—",
                "currency": account.get("currency", "USD"),
                "account_mode": display_mode,
                "login": "—",
            }
        else:
            values = {
                "balance": account.get("balance", 0),
                "equity": account.get("equity", 0),
                "free_margin": account.get("free_margin", 0),
                "margin_level": account.get("margin_level", 0),
                "leverage": account.get("leverage", "—"),
                "currency": account.get("currency", "USD"),
                "account_mode": display_mode,
                "login": account.get("login", "—"),
            }
        for key, label in self._account_labels.items():
            value = values.get(key, "—")
            label.configure(text=f"{value:,}" if isinstance(value, (int, float)) else str(value))

    def _draw_trading_placeholder_chart(self):
        if self.trading_chart_canvas is None:
            return
        self.trading_chart_canvas.delete("all")
        width = self.trading_chart_canvas.winfo_width() or 860
        height = self.trading_chart_canvas.winfo_height() or 220
        padding = 16
        self.trading_chart_canvas.create_rectangle(
            padding,
            padding,
            width - padding,
            height - padding,
            outline=self._theme("accent"),
            width=2,
        )
        self.trading_chart_canvas.create_text(
            width // 2,
            height // 2,
            text="Market chart unavailable",
            fill=self._theme("text"),
            font=("Consolas", 12, "italic"),
        )

    def _draw_trading_chart(self, candles):
        if self.trading_chart_canvas is None or not candles:
            self._draw_trading_placeholder_chart()
            return

        # Keep a reference to the full dataset for zooming
        try:
            self._last_full_candles = list(candles)
        except Exception:
            self._last_full_candles = candles

        self.trading_chart_canvas.delete("all")
        width = self.trading_chart_canvas.winfo_width() or 860
        height = self.trading_chart_canvas.winfo_height() or 220
        padding = 16

        total = len(candles)
        view_count = min(self._trading_chart_view_count, total)
        offset = max(0, int(self._trading_chart_view_offset))
        start_idx = max(0, total - view_count - offset)
        end_idx = min(total, start_idx + view_count)
        selected = candles[start_idx:end_idx]

        # Extract prices and preserve metadata
        prices = []
        for c in selected:
            o = float(c.get("open", c.get("o", c.get("Open", 0))))
            h = float(c.get("high", c.get("h", c.get("High", o))))
            l = float(c.get("low", c.get("l", c.get("Low", o))))
            cl = float(c.get("close", c.get("c", c.get("Close", o))))
            t = c.get("time") or c.get("timestamp") or c.get("t")
            vol = c.get("tick_volume") or c.get("volume") or c.get("v")
            prices.append({"open": o, "high": h, "low": l, "close": cl, "time": t, "tick_volume": vol, "raw": c})

        closes = [p["close"] for p in prices]
        if not closes or all(c == 0 for c in closes):
            self._draw_trading_placeholder_chart()
            return

        min_price = min(p["low"] for p in prices)
        max_price = max(p["high"] for p in prices)
        span = max_price - min_price or 1
        chart_width = width - padding * 2
        chart_height = height - padding * 2

        # Compute x positions for candles
        points_x = []
        for idx in range(len(prices)):
            x = padding + (idx / (len(prices) - 1 or 1)) * chart_width
            points_x.append(x)

        body_width = max(4, chart_width / max(40, len(prices)) * 0.6)

        def y_for(price):
            return height - padding - ((price - min_price) / span) * chart_height

        for idx, p in enumerate(prices):
            o = p["open"]
            h = p["high"]
            l = p["low"]
            cl = p["close"]
            x = points_x[idx]

            y_open = y_for(o)
            y_close = y_for(cl)
            y_high = y_for(h)
            y_low = y_for(l)

            # wick
            self.trading_chart_canvas.create_line(x, y_high, x, y_low, fill=self._theme("text"), width=1)

            # body
            top = min(y_open, y_close)
            bottom = max(y_open, y_close)
            color = "#2ecc71" if cl >= o else "#e74c3c"
            self.trading_chart_canvas.create_rectangle(
                x - body_width / 2,
                top,
                x + body_width / 2,
                bottom,
                fill=color,
                outline=self._theme("border"),
            )

        # Border and label
        self.trading_chart_canvas.create_rectangle(
            padding,
            padding,
            width - padding,
            height - padding,
            outline=self._theme("text"),
            width=1,
        )
        self.trading_chart_canvas.create_text(
            width - padding - 10,
            padding + 12,
            text=f"{len(prices)}-period OHLC (view {start_idx}:{end_idx})",
            fill=self._theme("text"),
            font=("Consolas", 9),
            anchor="ne",
        )

        # Persistent selection rectangle (most recent portion of the view)
        try:
            recent_count = min(8, len(prices))
            start_x = points_x[-recent_count] - body_width
            end_x = points_x[-1] + body_width
            # remove previous selection
            if self._chart_selection_rect_id:
                try:
                    self.trading_chart_canvas.delete(self._chart_selection_rect_id)
                except Exception:
                    pass
            self._chart_selection_rect_id = self.trading_chart_canvas.create_rectangle(start_x, padding, end_x, height - padding, outline=self._theme("accent"), width=2)
            # draw resize handles
            try:
                # remove previous handles
                if getattr(self, "_selection_handle_ids", None):
                    for hid in getattr(self, "_selection_handle_ids", []):
                        try:
                            self.trading_chart_canvas.delete(hid)
                        except Exception:
                            pass
                self._selection_handle_ids = []
                handle_w = max(6, body_width * 0.6)
                mid_y = (padding + (height - padding)) / 2
                left_handle = self.trading_chart_canvas.create_rectangle(start_x - handle_w / 2, mid_y - handle_w / 2, start_x + handle_w / 2, mid_y + handle_w / 2, fill=self._theme("accent"), outline=self._theme("border"))
                right_handle = self.trading_chart_canvas.create_rectangle(end_x - handle_w / 2, mid_y - handle_w / 2, end_x + handle_w / 2, mid_y + handle_w / 2, fill=self._theme("accent"), outline=self._theme("border"))
                self._selection_handle_ids.extend([left_handle, right_handle])
            except Exception:
                pass
        except Exception:
            self._chart_selection_rect_id = None

        # Save last chart data for tooltip/interactions
        self._last_chart_data = {"prices": prices, "points_x": points_x, "start_idx": start_idx}

    def _update_trading_mode_banner(
        self,
        account_mode: str,
        bridge_connected: bool,
        bridge_error: str | None,
        balance: float | None = None,
        mode_match: bool | None = None,
        account_login_exists: bool = True,
    ):
        if not account_login_exists and mode_match:
            mode_match = False
        from skills.trading.engine.trading_status import build_trading_status_banner, get_trading_status_state
        if self._trading_mode_banner_var is not None:
            banner_text = build_trading_status_banner(account_mode, bridge_connected, bridge_error, balance, mode_match)
            self._trading_mode_banner_var.set(banner_text)

        if self._trading_mode_banner_var is not None:
            state = get_trading_status_state(account_mode, bridge_connected, bridge_error, mode_match)
            try:
                self._trading_mode_label_widget.configure(fg=state.get("color", self._theme("accent")))
            except Exception:
                pass

    def _update_bridge_error(self, bridge_error: str | None):
        if self._trading_bridge_error_var is None:
            return
        if bridge_error:
            self._trading_bridge_error_var.set(f"Bridge detail: {bridge_error}")
        else:
            self._trading_bridge_error_var.set("Bridge connected and ready.")

        # Update MT5 data badge state
        try:
            if getattr(self, "_mt5_data_badge_var", None) is not None:
                account_error = getattr(self, "_last_account_error", None)
                last_account = getattr(self, "_last_account", {}) or {}
                actual_mode = (last_account.get("mode") or "").lower()
                requested_mode = (last_account.get("requested_mode") or "").lower()
                mode_match = last_account.get("mode_match", True)
                actual_mode = self._swap_display_mode(actual_mode)
                requested_mode = self._swap_display_mode(requested_mode)

                if not mode_match:
                    mismatch_text = f"Mode mismatch: connected {actual_mode.upper()}, requested {requested_mode.upper()}"
                    self._mt5_data_badge_var.set(mismatch_text)
                    try:
                        self._mt5_data_badge_label.configure(bg="#f59e0b")
                    except Exception:
                        pass
                elif actual_mode in {"live", "demo"}:
                    if actual_mode == "live":
                        self._mt5_data_badge_var.set("Using real MT5 data")
                        try:
                            self._mt5_data_badge_label.configure(bg="#16a34a")
                        except Exception:
                            pass
                    else:
                        self._mt5_data_badge_var.set("Using demo MT5 data")
                        try:
                            self._mt5_data_badge_label.configure(bg="#0ea5e9")
                        except Exception:
                            pass
                elif bridge_error or account_error:
                    self._mt5_data_badge_var.set("MT5 unavailable")
                    try:
                        self._mt5_data_badge_label.configure(bg="#dc2626")
                    except Exception:
                        pass
                else:
                    self._mt5_data_badge_var.set("")
                    try:
                        self._mt5_data_badge_label.configure(bg=self._theme("accent"))
                    except Exception:
                        pass

        except Exception:
            pass

    def _zoom_in_chart(self):
        # reduce view count to zoom in
        old = self._trading_chart_view_count
        self._trading_chart_view_count = max(6, int(old * 0.6))
        try:
            self._draw_trading_chart(self._last_full_candles)
        except Exception:
            pass

    def _zoom_out_chart(self):
        # increase view count to zoom out
        old = self._trading_chart_view_count
        self._trading_chart_view_count = min(max(6, old + 10), max(60, getattr(self, "_last_full_candles", []) and len(self._last_full_candles) or 60))
        try:
            self._draw_trading_chart(self._last_full_candles)
        except Exception:
            pass

    def _on_chart_motion(self, event):
        try:
            data = self._last_chart_data
            if not data or not data.get("prices"):
                return
            points = data["points_x"]
            prices = data["prices"]
            if not points:
                return
            # find nearest index
            x = event.x
            nearest = min(range(len(points)), key=lambda i: abs(points[i] - x))
            p = prices[nearest]
            txt_lines = []
            if p.get("time"):
                txt_lines.append(str(p.get("time")))
            txt_lines.append(f"O {p['open']:.6f}  H {p['high']:.6f}")
            txt_lines.append(f"L {p['low']:.6f}  C {p['close']:.6f}")
            if p.get("tick_volume") is not None:
                txt_lines.append(f"Vol: {p.get('tick_volume')}")
            txt = "\n".join(txt_lines)
            if self._chart_tooltip is None:
                return
            try:
                self.trading_chart_canvas.delete("chart_tooltip")
            except Exception:
                pass
            self._chart_tooltip.configure(text=txt)
            # place tooltip near cursor
            try:
                self.trading_chart_canvas.create_window(event.x + 12, event.y - 12, window=self._chart_tooltip, anchor="nw", tags=("chart_tooltip",))
            except Exception:
                pass
        except Exception:
            pass

    def _hide_chart_tooltip(self):
        try:
            if self.trading_chart_canvas is not None:
                self.trading_chart_canvas.delete("chart_tooltip")
        except Exception:
            pass

    def _show_mt5_tooltip(self, event):
        # Show a small tooltip near the cursor with the raw bridge error or status
        try:
            text = self._trading_bridge_error_var.get() if getattr(self, "_trading_bridge_error_var", None) is not None else "MT5 status unavailable"
        except Exception:
            text = "MT5 status unavailable"
        try:
            if self._mt5_tooltip is not None:
                try:
                    self._mt5_tooltip.destroy()
                except Exception:
                    pass
            self._mt5_tooltip = tk.Toplevel(self)
            self._mt5_tooltip.wm_overrideredirect(True)
            lbl = tk.Label(self._mt5_tooltip, text=text, bg=self._theme("panel_alt"), fg=self._theme("text"), font=("Consolas", 9), bd=1, relief="solid", padx=6, pady=4)
            lbl.pack()
            x = event.x_root + 12
            y = event.y_root + 12
            self._mt5_tooltip.wm_geometry(f"+{x}+{y}")
            self._mt5_tooltip.attributes("-topmost", True)
        except Exception:
            pass

    def _hide_mt5_tooltip(self, event):
        try:
            if self._mt5_tooltip:
                try:
                    self._mt5_tooltip.destroy()
                except Exception:
                    pass
                self._mt5_tooltip = None
        except Exception:
            pass

    def _on_chart_button_press(self, event):
        try:
            self._selection_start_x = event.x
            self._selection_start_y = event.y
            # remove any existing ephemeral selection
            try:
                self.trading_chart_canvas.delete("chart_drag_select")
            except Exception:
                pass
            self.trading_chart_canvas.create_rectangle(self._selection_start_x, self._selection_start_y, self._selection_start_x, self._selection_start_y, outline=self._theme("accent"), width=1, tags=("chart_drag_select",))
        except Exception:
            pass

    def _on_chart_button_motion(self, event):
        try:
            # update drag rectangle
            try:
                self.trading_chart_canvas.delete("chart_drag_select")
            except Exception:
                pass
            x1 = self._selection_start_x
            y1 = self._selection_start_y
            x2 = event.x
            y2 = event.y
            self.trading_chart_canvas.create_rectangle(x1, y1, x2, y2, outline=self._theme("accent"), width=1, dash=(2, 2), tags=("chart_drag_select",))
        except Exception:
            pass

    def _on_chart_button_release(self, event):
        try:
            # finalize selection and zoom to it
            try:
                sel = self.trading_chart_canvas.find_withtag("chart_drag_select")
                for s in sel:
                    # compute coordinates
                    coords = self.trading_chart_canvas.coords(s)
                    if not coords or len(coords) < 4:
                        continue
                    x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]
                    sx, ex = sorted((x1, x2))
                    data = getattr(self, "_last_chart_data", None)
                    if not data:
                        continue
                    points = data.get("points_x", [])
                    if not points:
                        continue
                    # find nearest indices
                    start_idx = min(range(len(points)), key=lambda i: abs(points[i] - sx))
                    end_idx = min(range(len(points)), key=lambda i: abs(points[i] - ex))
                    if end_idx < start_idx:
                        start_idx, end_idx = end_idx, start_idx
                    # compute selection size in absolute candle indexes relative to full data
                    selection_count = max(1, end_idx - start_idx + 1)
                    total = len(getattr(self, "_last_full_candles", []))
                    # determine full-data start index based on last_chart_data.start_idx
                    view_start = data.get("start_idx", 0)
                    absolute_start = view_start + start_idx
                    # set view to the selection
                    self._trading_chart_view_count = selection_count
                    # offset = total - view_count - start_idx
                    self._trading_chart_view_offset = max(0, total - self._trading_chart_view_count - absolute_start)
                    # remove drag rectangle
                    try:
                        self.trading_chart_canvas.delete("chart_drag_select")
                    except Exception:
                        pass
                    # redraw with new zoom
                    try:
                        self._draw_trading_chart(self._last_full_candles)
                    except Exception:
                        pass
                    break
            except Exception:
                pass
        except Exception:
            pass

    def _append_trading_transcript(self, message: str):
        if self.trading_transcript_text is None:
            return
        self.trading_transcript_text.configure(state="normal")
        self.trading_transcript_text.insert(tk.END, f"{message}\n\n")
        self.trading_transcript_text.see(tk.END)
        self.trading_transcript_text.configure(state="disabled")

    def _get_market_symbols(self) -> list[str]:
        # Attempt to query the market module or bridge for available symbols
        try:
            from skills.trading.market.market_data import market
            # Common heuristics: try a small probe to see if MT5 is available
            # If market module has no direct symbol list, try bridge
            try:
                from skills.trading.engine.connection_manager import bridge_manager
                resp = None
                try:
                    resp = bridge_manager.send_request({"command": "get_symbols"})
                except Exception:
                    try:
                        # Some bridges expose via send_command
                        resp = bridge_manager.send_command("get_symbols")
                    except Exception:
                        resp = None
                if isinstance(resp, dict) and resp.get("symbols"):
                    return [s.upper() for s in resp.get("symbols")]
                if isinstance(resp, dict) and resp.get("instruments"):
                    return [s.upper() for s in resp.get("instruments")]
                if isinstance(resp, list):
                    return [s.upper() for s in resp]
                # Try multiple common bridge command names
                for cmd in ("list_instruments", "get_instruments", "list_symbols", "get_symbols"):
                    try:
                        alt = bridge_manager.send_command(cmd)
                        if isinstance(alt, list) and alt:
                            return [s.upper() for s in alt]
                        if isinstance(alt, dict) and alt.get("symbols"):
                            return [s.upper() for s in alt.get("symbols")]
                    except Exception:
                        continue
            except Exception:
                pass
        except Exception:
            pass

        # Fallback common symbols list
        return [s.upper() for s in config.TRADING_SYMBOLS]

    def _handle_plan_and_execute_trade(self):
        symbol = self._prompt_for_trade_symbol()
        if not symbol:
            return

        selected_timeframe = getattr(self, '_timeframe_var', None)
        selected_timeframe = selected_timeframe.get() if selected_timeframe is not None else config.DEFAULT_TRADING_TIMEFRAME
        account_mode = (getattr(self, "_account_mode_var", None).get() if getattr(self, "_account_mode_var", None) is not None else "demo")

        if self._pending_trade is None:
            if not self._confirm_dialog(
                "Plan Trade",
                f"Analyze and prepare a trade plan for {symbol} on {selected_timeframe}? This will not execute the trade yet.",
                confirm_text="Plan",
                cancel_text="Cancel",
            ):
                return

            self._append_console("TRADING", f"Planning trade for {symbol} {selected_timeframe} in {account_mode.upper()} mode.")
            self.trading_detail_var.set("Planning trade and analyzing market conditions...")
            self._trade_action_button.configure(state="disabled")
            threading.Thread(
                target=self._plan_trade_background,
                args=(symbol, selected_timeframe, account_mode),
                daemon=True,
            ).start()
        else:
            if not self._confirm_dialog(
                "Execute Trade",
                f"Execute the planned trade for {self._pending_trade} in {account_mode.upper()} mode?",
                confirm_text="Execute",
                cancel_text="Cancel",
            ):
                return
            self._append_console("TRADING", f"Executing trade for {self._pending_trade}.")
            self.trading_detail_var.set("Executing planned trade...")
            self._trade_action_button.configure(state="disabled")
            threading.Thread(
                target=self._execute_trade_background,
                args=(self._pending_trade, selected_timeframe, account_mode),
                daemon=True,
            ).start()

    def _plan_trade_background(self, symbol: str, timeframe: str, account_mode: str):
        try:
            from skills.trading.trading_skill import analyze_and_recommend
            result = analyze_and_recommend(symbol, timeframe=timeframe, auto_execute=False, account_mode=account_mode)
            self.after(0, lambda: self._finish_trade_plan(symbol, result))
        except Exception as exc:
            self.after(0, lambda: self._finish_trade_error(f"Planning failed: {exc}"))

    def _execute_trade_background(self, symbol: str, timeframe: str, account_mode: str):
        try:
            from skills.trading.trading_skill import analyze_and_recommend
            result = analyze_and_recommend(symbol, timeframe=timeframe, auto_execute=True, account_mode=account_mode)
            self.after(0, lambda: self._finish_trade_execution(result))
        except Exception as exc:
            self.after(0, lambda: self._finish_trade_error(f"Execution failed: {exc}"))

    def _finish_trade_plan(self, symbol: str, result: str):
        self._pending_trade = symbol
        self.trading_detail_var.set(result[:1400])
        self._trade_action_button.configure(text="EXECUTE PLANNED TRADE", state="normal")
        self._append_console("TRADING", f"Trade plan ready for {symbol}.")

    def _finish_trade_execution(self, result: str):
        self.trading_detail_var.set(result[:1400])
        self._append_console("TRADING", result)
        self._pending_trade = None
        self._trade_action_button.configure(text="PLAN TRADE", state="normal")

    def _finish_trade_error(self, message: str):
        self.trading_detail_var.set(message)
        self._append_console("TRADING-ERR", message)
        self._trade_action_button.configure(state="normal")

    def _update_avatar(self):
        # Ensure canvas layout is settled before measuring
        try:
            self.ring_canvas.update_idletasks()
        except Exception:
            pass
        width = self.ring_canvas.winfo_width() or 520
        height = self.ring_canvas.winfo_height() or 520
        avatar_size = int(min(260, width - 120, height - 120))
        if avatar_size < 80:
            avatar_size = 80

        # Only recreate the avatar image when the computed size changes
        avatar_image = getattr(self, "_avatar_image", None)
        center_x = self.ring_canvas.winfo_width() // 2
        center_y = self.ring_canvas.winfo_height() // 2

        if avatar_image and ImageDraw and ImageTk:
            if getattr(self, "_avatar_size_cached", 0) != avatar_size or not getattr(self, "_avatar_photo", None):
                avatar = self._create_circular_avatar(avatar_image, avatar_size)
                if avatar is not None:
                    self._avatar_photo = ImageTk.PhotoImage(avatar)
                    self._avatar_size_cached = avatar_size
            # Draw or update image on the ring canvas at fixed center coords
            if self._avatar_canvas_id is not None:
                try:
                    self.ring_canvas.coords(self._avatar_canvas_id, center_x, center_y)
                    self.ring_canvas.itemconfigure(self._avatar_canvas_id, image=self._avatar_photo)
                except Exception:
                    # recreate if something went wrong with the canvas item
                    self._avatar_canvas_id = self.ring_canvas.create_image(center_x, center_y, image=self._avatar_photo, anchor="center")
            else:
                self._avatar_canvas_id = self.ring_canvas.create_image(center_x, center_y, image=self._avatar_photo, anchor="center")
            # Ensure avatar is exactly on top and positioned using integer center coords
            try:
                self.ring_canvas.coords(self._avatar_canvas_id, int(center_x), int(center_y))
                self.ring_canvas.tag_raise(self._avatar_canvas_id)
            except Exception:
                pass
            # remove any fallback text
            if self._avatar_text_id is not None:
                try:
                    self.ring_canvas.delete(self._avatar_text_id)
                except Exception:
                    pass
                self._avatar_text_id = None
        else:
            # No image available — draw centered text as fallback on the canvas
            text = "ANGELIQUE"
            font_size = max(18, min(32, int(min(width, height) / 18)))
            if self._avatar_text_id is not None:
                self.ring_canvas.coords(self._avatar_text_id, center_x, center_y)
                self.ring_canvas.itemconfigure(self._avatar_text_id, text=text, fill=self._theme("accent"))
            else:
                self._avatar_text_id = self.ring_canvas.create_text(center_x, center_y, text=text, fill=self._theme("accent"), font=("Consolas", font_size, "bold"))
        # old Label-based fallback removed; canvas text is used instead when no image is available

    def _build_right_panel(self):
        title = tk.Label(
            self.right_panel,
            text="COMMAND SUITE",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 14, "bold"),
        )
        title.pack(anchor="nw", padx=20, pady=(18, 12))

        self._build_mission_ticker()
        self._create_command_button(self.right_panel, "TRADING HUB", command=self._enter_trading_view)
        self._create_command_button(self.right_panel, "VOICE ASSIST", command=self._on_voice_command)
        self._create_command_button(self.right_panel, "SYSTEM DIAGNOSTICS")
        # Debug bridge button for quick diagnostics
        self._create_command_button(self.right_panel, "BRIDGE DEBUG", command=self._show_bridge_debug)
        self._create_command_button(self.right_panel, "EXIT ANGELIQUE", command=self._exit_angelique)

        divider = tk.Frame(self.right_panel, bg=self._theme("border"), height=1)
        divider.pack(fill="x", padx=20, pady=18)

        self._mode_label = tk.Label(
            self.right_panel,
            text="MODE CHECKING...",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 10, "bold"),
            justify="left",
        )
        self._mode_label.pack(anchor="nw", padx=20, pady=(0, 12))

    def _show_bridge_debug(self):
        try:
            from skills.trading.engine.connection_manager import bridge_manager
            from skills.trading.engine.mt5_bridge import bridge
            import socket

            connected = bridge_manager.get_status()
            last_err = bridge_manager.get_last_error()
            host = getattr(bridge_manager, 'host', '127.0.0.1')
            port = getattr(bridge_manager, 'port', config.MT5_BRIDGE_PORT)

            # Try to find local pid listening on port (best-effort)
            pid_info = 'unknown'
            try:
                import subprocess
                out = subprocess.check_output(['ss', '-ltnp']).decode('utf-8')
                lines = [l for l in out.splitlines() if f":{port} " in l or f":{port}\n" in l]
                pid_info = '\n'.join(lines) if lines else 'none'
            except Exception:
                pid_info = 'ss lookup failed'

            demo_info = bridge.get_account_info('demo')
            live_info = bridge.get_account_info('live')

            msg = (
                f"Connected: {connected}\n"
                f"Last error: {last_err}\n"
                f"Host: {host}\nPort: {port}\nPID info: {pid_info}\n\n"
                f"DEMO account info: {demo_info}\n\n"
                f"LIVE account info: {live_info}\n"
            )
            try:
                messagebox.showinfo("Bridge Debug", msg)
            except Exception:
                # fallback to appending to transcript
                self._append_trading_transcript(msg)
        except Exception as e:
            try:
                messagebox.showerror("Bridge Debug Error", f"Failed to collect bridge debug: {e}")
            except Exception:
                self._append_trading_transcript(f"Bridge debug failed: {e}")

        self._update_mission_ticker()

    def _create_command_button(self, parent, label, command=None):
        button = tk.Button(
            parent,
            text=label,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            font=("Consolas", 11, "bold"),
            relief="flat",
            padx=14,
            pady=12,
            command=command if command is not None else lambda: self._send_command(label),
        )
        button.pack(fill="x", padx=20, pady=8)

    def _build_bottom_panel(self):
        tk.Label(
            self.bottom_panel,
            text="COMMAND CONSOLE",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 14, "bold"),
        ).pack(anchor="nw", padx=20, pady=(18, 10))

        self.command_frame = tk.Frame(self.bottom_panel, bg=self._theme("panel"))
        self.command_frame.pack(fill="x", padx=20, pady=(0, 12))

        command_shell = tk.Frame(
            self.command_frame,
            bg=self._theme("panel"),
            highlightthickness=1,
            highlightbackground=self._theme("border"),
            highlightcolor=self._theme("accent"),
        )
        command_shell.pack(fill="x")

        tk.Label(
            command_shell,
            text="ENTER COMMAND",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 11, "bold"),
        ).pack(anchor="w", padx=16, pady=(12, 8))

        command_row = tk.Frame(command_shell, bg=self._theme("panel"))
        command_row.pack(fill="x", padx=16, pady=(0, 14))

        self.input_entry = tk.Entry(
            command_row,
            bg=self._theme("bg"),
            fg=self._theme("text"),
            insertbackground=self._theme("text"),
            font=("Consolas", 12),
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self._theme("border"),
            highlightcolor=self._theme("accent"),
        )
        self.input_entry.pack(side="left", fill="x", expand=True, ipady=10)
        self.input_entry.bind("<Return>", self._on_send)
        self.input_entry.bind("<FocusIn>", self._on_input_focus_in)
        self.input_entry.bind("<FocusOut>", self._on_input_focus_out)
        self._input_placeholder_text = "Type text command here and press EXECUTE"
        self._input_placeholder_active = False
        self._set_input_placeholder()

        self.mic_button = tk.Button(
            command_row,
            text="🎙️",
            command=self._toggle_audio_mode,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=14,
            pady=10,
            font=("Consolas", 12, "bold"),
        )
        self.mic_button.pack(side="left", padx=(12, 0))

        self._input_mode_label = tk.Label(
            command_row,
            text="VOICE MODE",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 10, "bold"),
        )
        self._input_mode_label.pack(side="left", padx=(10, 0), pady=2)

        self.training_toggle_button = tk.Button(
            command_row,
            text="TRAINING: OFF",
            command=self._toggle_training_mode,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=12,
            pady=10,
            font=("Consolas", 10, "bold"),
        )
        self.training_toggle_button.pack(side="left", padx=(10, 0))

        self.send_button = tk.Button(
            command_row,
            text="EXECUTE",
            command=self._on_send,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=18,
            pady=10,
            font=("Consolas", 11, "bold"),
        )
        self.send_button.pack(side="left", padx=(12, 0))

        self.console_text = tk.Text(
            self.bottom_panel,
            bg=self._theme("bg"),
            fg=self._theme("text"),
            insertbackground=self._theme("text"),
            bd=0,
            highlightthickness=0,
            font=("Consolas", 11),
            wrap="word",
        )
        self.console_text.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        self.console_text.configure(state="disabled")

        terminal_frame = tk.Frame(self.bottom_panel, bg=self._theme("panel"))
        terminal_frame.pack(fill="x", padx=20, pady=(0, 12))

        tk.Label(
            terminal_frame,
            text="TERMINAL COMMANDS",
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 11, "bold"),
        ).pack(anchor="nw")

        self.terminal_text = tk.Text(
            terminal_frame,
            height=4,
            bg=self._theme("bg"),
            fg=self._theme("text"),
            insertbackground=self._theme("text"),
            bd=0,
            highlightthickness=1,
            highlightbackground=self._theme("accent"),
            highlightcolor=self._theme("accent"),
            font=("Consolas", 11),
            wrap="word",
        )
        self.terminal_text.pack(fill="x", pady=(8, 10))
        self.terminal_text.bind("<Control-Return>", self._on_terminal_execute)
        self.terminal_text.bind("<FocusIn>", self._on_terminal_focus_in)
        self.terminal_text.bind("<FocusOut>", self._on_terminal_focus_out)
        self._terminal_placeholder_text = "Type shell command here and press EXECUTE TERMINAL COMMAND"
        self._terminal_placeholder_active = False
        self._set_terminal_placeholder()

        terminal_execute_button = tk.Button(
            terminal_frame,
            text="EXECUTE TERMINAL COMMAND",
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=18,
            pady=10,
            font=("Consolas", 11, "bold"),
            command=self._on_terminal_execute,
        )
        terminal_execute_button.pack(anchor="e")

    def _build_footer_bar(self):
        self.footer_label = tk.Label(
            self.footer_bar,
            text=self._footer_text(),
            fg=self._theme("accent"),
            bg=self._theme("panel"),
            font=("Consolas", 10),
        )
        self.footer_label.place(relx=0.02, rely=0.5, anchor="w")

        self.speech_toggle = tk.Button(
            self.footer_bar,
            text="VOICE OUTPUT ON",
            command=self._toggle_voice_output,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=12,
            pady=6,
            font=("Consolas", 9, "bold"),
        )
        self.speech_toggle.place(relx=0.93, rely=0.5, anchor="e")

        self.resize_handle = tk.Frame(
            self.footer_bar,
            bg=self._theme("button_bg"),
            cursor="bottom_right_corner",
            width=18,
            height=18,
        )
        self.resize_handle.place(relx=0.985, rely=0.5, anchor="e")
        self.resize_handle.bind("<ButtonPress-1>", self._start_resize)
        self.resize_handle.bind("<B1-Motion>", self._do_resize)

    def _bind_events(self):
        self.bind("<Configure>", self._on_resize)
        self.bind("<Escape>", lambda event: self.on_close())
        # allow Ctrl+M to toggle audio in the GUI
        self.bind_all("<Control-m>", lambda e: self._toggle_audio_mode())

    def _draw_ring_hud(self):
        # Only remove ring-related items so the avatar image (and other overlays)
        # are preserved during resizes/maximize. Using a specific tag prevents
        # deleting canvas items like the avatar which were previously lost.
        try:
            self.ring_canvas.delete('ring')
        except Exception:
            # Fallback to clearing all if delete by tag isn't supported for some reason
            try:
                self.ring_canvas.delete("all")
            except Exception:
                pass
        try:
            self.ring_canvas.update_idletasks()
        except Exception:
            pass
        width = self.ring_canvas.winfo_width() or 520
        height = self.ring_canvas.winfo_height() or 520
        size = min(width, height)
        center_x = width // 2
        center_y = height // 2
        radius = max(100, int(size * 0.34))
        # reset ring-specific state
        self._glow_items = []
        self._scanner_item: int | None = None
        self._scanner_dot: int | None = None

        theme = self._themes.get(self._theme_name, self._themes["blue"])
        ring_offsets = [int(size * 0.08), int(size * 0.05), 0, -int(size * 0.08)]
        ring_lines = [2, 2, 3, 2]
        ring_colors = [theme["border"], theme["accent"], theme["accent"], theme["border"]]

        for offset, width_line, color in zip(ring_offsets, ring_lines, ring_colors):
            ring = radius + offset
            self.ring_canvas.create_oval(
                center_x - ring,
                center_y - ring,
                center_x + ring,
                center_y + ring,
                outline=color,
                width=width_line,
                tags=("ring",),
            )

        for idx, angle in enumerate(range(0, 360, 30)):
            radians = math.radians(angle)
            x = center_x + (radius + int(size * 0.03)) * math.cos(radians)
            y = center_y + (radius + int(size * 0.03)) * math.sin(radians)
            dot = self.ring_canvas.create_oval(
                x - max(4, int(size * 0.012)),
                y - max(4, int(size * 0.012)),
                x + max(4, int(size * 0.012)),
                y + max(4, int(size * 0.012)),
                fill=self._theme("accent"),
                outline="",
                tags=("ring",),
            )
            self._glow_items.append(dot)

        self._scanner_item = self.ring_canvas.create_line(
            center_x,
            center_y,
            center_x + radius,
            center_y,
            fill=self._theme("accent"),
            width=max(2, int(size * 0.007)),
            capstyle="round",
            tags=("ring",),
        )

        self.ring_canvas.create_text(
            center_x,
            center_y - int(size * 0.18),
            text="ANGELIQUE",
            fill=self._theme("accent"),
            font=("Consolas", max(14, int(size * 0.035)), "bold"),
            tags=("ring",),
        )
        self.ring_canvas.create_text(
            center_x,
            center_y + int(size * 0.18),
            text="CORE ONLINE",
            fill=self._theme("accent"),
            font=("Consolas", max(8, int(size * 0.02))),
            tags=("ring",),
        )
        # Reposition avatar after drawing ring elements to guarantee exact center.
        # The avatar is intentionally not part of the 'ring' tag so it survives
        # canvas redraws and stays on top.
        avatar_canvas_id = getattr(self, "_avatar_canvas_id", None)
        if avatar_canvas_id is not None:
            try:
                self.ring_canvas.coords(avatar_canvas_id, center_x, center_y)
                self.ring_canvas.tag_raise(avatar_canvas_id)
            except Exception:
                pass
        # Ensure avatar exists on the canvas after drawing the ring; recreate if missing
        try:
            self._update_avatar()
        except Exception:
            pass

    def _animate_ring(self):
        self._animation_phase += 0.12
        self._scanner_angle = (self._scanner_angle + 3) % 360

        for idx, item in enumerate(self._glow_items):
            intensity = (math.sin(self._animation_phase + idx * 0.8) + 1) / 2
            color = self._theme("accent")
            self.ring_canvas.itemconfigure(item, fill=color)

        try:
            self.ring_canvas.update_idletasks()
        except Exception:
            pass
        width = self.ring_canvas.winfo_width() or 520
        height = self.ring_canvas.winfo_height() or 520
        size = min(width, height)
        center_x = width // 2
        center_y = height // 2
        radius = max(100, int(size * 0.34))

        radians = math.radians(self._scanner_angle)
        x = center_x + radius * math.cos(radians)
        y = center_y + radius * math.sin(radians)
        if self._scanner_item is not None:
            self.ring_canvas.coords(self._scanner_item, center_x, center_y, x, y)

        dot_size = max(6, int(size * 0.015))
        scanner_dot_id = getattr(self, "_scanner_dot", None)
        if scanner_dot_id is not None:
            self.ring_canvas.coords(scanner_dot_id, x - dot_size, y - dot_size, x + dot_size, y + dot_size)
        else:
            self._scanner_dot = self.ring_canvas.create_oval(
                x - dot_size,
                y - dot_size,
                x + dot_size,
                y + dot_size,
                fill=self._theme("accent"),
                outline="",
            )
        # Keep avatar above animated elements
        avatar_canvas_id = getattr(self, "_avatar_canvas_id", None)
        if avatar_canvas_id is not None:
            try:
                self.ring_canvas.tag_raise(avatar_canvas_id)
                # ensure precise center alignment while animating
                self.ring_canvas.coords(avatar_canvas_id, int(center_x), int(center_y))
            except Exception:
                pass

        self.after(80, self._animate_ring)

    def _build_mission_ticker(self):
        ticker_frame = tk.Frame(self.right_panel, bg=self._theme("panel_alt"), bd=1, relief="solid")
        ticker_frame.pack(fill="x", padx=20, pady=(0, 18))
        tk.Label(
            ticker_frame,
            text="MISSION STATUS",
            fg=self._theme("accent"),
            bg=self._theme("panel_alt"),
            font=("Consolas", 10, "bold"),
        ).pack(anchor="nw", padx=10, pady=(10, 4))

        self._ticker_labels = []
        for _ in range(3):
            label = tk.Label(
                ticker_frame,
                text="",
                fg=self._theme("text"),
                bg=self._theme("panel_alt"),
                font=("Consolas", 10),
                justify="left",
                anchor="w",
            )
            label.pack(fill="x", anchor="nw", padx=10)
            self._ticker_labels.append(label)

    def _update_mission_ticker(self):
        for idx, label in enumerate(self._ticker_labels):
            generator = self._mission_status_generators[(self._ticker_index + idx) % len(self._mission_status_generators)]
            label.configure(text=generator(self._system_stats))
        self._ticker_index = (self._ticker_index + 1) % len(self._mission_status_generators)
        self.after(2500, self._update_mission_ticker)

    def _update_background(self, event=None):
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 0 or height <= 0:
            return

        if self._background_image and Image is not None and ImageTk is not None:
            resample = _get_resampling_filter()
            if resample is not None:
                bg = self._background_image.resize((width, height), resample)
                self._background_photo = ImageTk.PhotoImage(bg)
            else:
                self._background_photo = None
            if self._background_photo is not None and self._bg_image_id is None:
                self._bg_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self._background_photo)
            elif self._background_photo is not None and self._bg_image_id is not None:
                self.canvas.itemconfig(self._bg_image_id, image=self._background_photo)

        if self._bg_overlay_id is None:
            self._bg_overlay_id = self.canvas.create_rectangle(
                0,
                0,
                width,
                height,
                fill=self._theme("bg"),
                stipple="gray25",
                outline="",
            )
        else:
            self.canvas.coords(self._bg_overlay_id, 0, 0, width, height)

        self._draw_scan_lines(width, height)

    def _draw_scan_lines(self, width, height):
        if hasattr(self, "_scan_line_ids") and self._scan_line_ids:
            for line_id in self._scan_line_ids:
                self.canvas.delete(line_id)
        self._scan_line_ids = []

        num_lines = 10
        spacing = height / (num_lines + 1)
        for i in range(1, num_lines + 1):
            intensity = int(64 + 64 * math.sin(self._animation_phase + i * 0.6))
            r = max(0, min(255, intensity))
            g = max(0, min(255, intensity + 80))
            b = max(0, min(255, intensity + 140))
            color = f"#{r:02x}{g:02x}{b:02x}"
            line_id = self.canvas.create_line(0, int(i * spacing), width, int(i * spacing), fill=color, width=1)
            self._scan_line_ids.append(line_id)

    def _create_circular_avatar(self, image, size):
        if Image is None or ImageDraw is None:
            return None

        source = image.copy()
        width, height = source.size
        min_dim = min(width, height)
        left = (width - min_dim) // 2
        top = (height - min_dim) // 2
        resample = _get_resampling_filter()
        source = source.crop((left, top, left + min_dim, top + min_dim)).resize((size, size), resample).convert("RGBA")

        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size, size), fill=255)
        source.putalpha(mask)

        output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        output.paste(source, (0, 0), source)

        border_draw = ImageDraw.Draw(output)
        border_width = max(4, size // 24)
        border_draw.ellipse(
            (border_width // 2, border_width // 2, size - border_width // 2 - 1, size - border_width // 2 - 1),
            outline=(112, 240, 255, 220),
            width=border_width,
        )
        return output

    def _format_uptime(self, uptime_seconds):
        minutes, seconds = divmod(int(uptime_seconds), 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m {seconds}s"

    def _read_temperature(self):
        if not psutil:
            return "N/A"
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for sensor_list in temps.values():
                    if sensor_list:
                        return int(sensor_list[0].current)
        except Exception:
            pass
        return "N/A"

    def _enable_wallpaper_mode(self):
        # Wallpaper mode is intentionally disabled so Angelique remains interactive.
        pass

    def _apply_wallpaper_layout(self):
        # Layout helper is disabled because full desktop wallpaper mode prevents button interaction.
        pass

    def _update_system_metrics(self):
        if not psutil:
            return

        cpu = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory().percent
        net = psutil.net_io_counters()
        now = time.time()
        delta = max(0.01, now - self._last_network_time)
        bytes_total = net.bytes_sent + net.bytes_recv
        network_mbps = max(0.0, ((bytes_total - self._last_network_bytes) * 8) / 1_000_000 / delta)

        self._last_network_bytes = bytes_total
        self._last_network_time = now

        temperature = self._read_temperature()
        uptime = self._format_uptime(time.time() - psutil.boot_time()) if hasattr(psutil, "boot_time") else "N/A"
        status = "READY" if cpu < 85 else "BUSY"

        self._system_stats.update({
            "cpu": int(cpu),
            "memory": int(memory),
            "network_mbps": network_mbps,
            "temperature": temperature,
            "uptime": uptime,
            "status": status,
        })
        self._refresh_online_status()

        if hasattr(self, "_cpu_label"):
            self._cpu_label.configure(text=f"{self._system_stats['cpu']}%")
        if hasattr(self, "_memory_label"):
            self._memory_label.configure(text=f"{self._system_stats['memory']}%")
        if hasattr(self, "_network_label"):
            self._network_label.configure(text=f"{self._system_stats['network_mbps']:.1f} Mbps")
        if hasattr(self, "_temperature_label"):
            temp_text = f"{self._system_stats['temperature']}°C" if isinstance(self._system_stats['temperature'], int) else self._system_stats['temperature']
            self._temperature_label.configure(text=temp_text)

        if hasattr(self, "footer_label"):
            self.footer_label.configure(
                text=f"CPU {self._system_stats['cpu']}%  |  MEMORY {self._system_stats['memory']}%  |  NETWORK {self._system_stats['network_mbps']:.1f} Mbps  | STATUS: {status}"
            )

        self.after(1000, self._update_system_metrics)
        self.after(3000, self._refresh_trading_bridge_status)

    def _append_console(self, source, message):
        timestamp = self._get_timestamp()
        if not hasattr(self, "console_text"):
            return
        self.console_text.configure(state="normal")
        self.console_text.insert(tk.END, f"[{timestamp}] {source}: {message}\n")
        self.console_text.see(tk.END)
        self.console_text.configure(state="disabled")

    def _enter_trading_view(self):
        self._show_trading_view()
        self._append_console("SYSTEM", "Trading hub opened in the center panel.")

    def _send_command(self, label: str):
        self._append_console("USER", label)
        self._append_console("ANGELIQUE", "Processing your request...")
        self.footer_label.configure(text=self._footer_text("PROCESSING"))
        threading.Thread(target=self._process_command, args=(label,), daemon=True).start()

    def _normalize_voice_command(self, text: str) -> str:
        if not text:
            return ""
        normalized = text.strip()
        if "angelique" in normalized.lower():
            normalized = re.sub(r"\bangelique\b", "", normalized, flags=re.IGNORECASE)
            normalized = re.sub(r"^[\s,;.:-]+|[\s,;.:-]+$", "", normalized)
        return normalized

    def _on_voice_command(self):
        if self._listen is None:
            self._append_console("SYSTEM", "Voice interface is unavailable.")
            return

        self._append_console("SYSTEM", "Listening for voice input...")
        self.footer_label.configure(text=self._footer_text("LISTENING"))

        def voice_thread():
            spoken = self._listen() if self._listen is not None else ""
            if not spoken:
                self.after(0, lambda: self._append_console("SYSTEM", "No speech detected."))
                self.after(0, lambda: self.footer_label.configure(text=self._footer_text("READY")))
                return

            cleaned = self._normalize_voice_command(spoken)
            if cleaned:
                spoken = cleaned

            self.after(0, lambda: self.input_entry.delete(0, tk.END))
            self.after(0, lambda: self.input_entry.insert(0, spoken))
            self.after(0, lambda: setattr(self, "_input_placeholder_active", False))
            self.after(0, lambda: self.input_entry.config(fg=self._theme("text")))
            self.after(0, lambda: self._append_console("USER", spoken))
            self.after(0, lambda: self._append_console("ANGELIQUE", "Processing your spoken command..."))
            self.after(0, lambda: self.footer_label.configure(text=self._footer_text("PROCESSING")))
            self._process_command(spoken)

        threading.Thread(target=voice_thread, daemon=True).start()

    def _toggle_audio_mode(self):
        self._audio_enabled = not getattr(self, "_audio_enabled", False)
        try:
            self.mic_button.configure(text="🎙️" if self._audio_enabled else "⌨️")
            self._input_mode_label.configure(text="VOICE MODE" if self._audio_enabled else "TEXT MODE")
        except Exception:
            pass
        if self._audio_enabled:
            self._append_console("SYSTEM", "Voice mode enabled. Starting continuous listening...")
            self.footer_label.configure(text=self._footer_text("LISTENING"))
            self._start_voice_listener()
        else:
            self._append_console("SYSTEM", "Text mode enabled. Voice listening stopped.")
            self.footer_label.configure(text=self._footer_text("READY"))
            self._stop_voice_listener()

    def _toggle_training_mode(self):
        self._training_mode_enabled = not getattr(self, "_training_mode_enabled", False)
        try:
            self.training_toggle_button.configure(text="TRAINING: ON" if self._training_mode_enabled else "TRAINING: OFF")
            self.training_toggle_button.configure(fg=self._theme("accent") if self._training_mode_enabled else self._theme("text"))
        except Exception:
            pass
        state = "enabled" if self._training_mode_enabled else "disabled"
        self._append_console("SYSTEM", f"Training mode {state}.")

    def _start_voice_listener(self):
        if getattr(self, "_listen", None) is None:
            return
        if self._voice_listener_thread is not None and self._voice_listener_thread.is_alive():
            return
        self._stop_listening.clear()
        self._voice_listener_thread = threading.Thread(target=self._voice_listener_loop, daemon=True)
        self._voice_listener_thread.start()

    def _stop_voice_listener(self):
        if getattr(self, "_stop_listening", None):
            self._stop_listening.set()
        if self._voice_listener_thread is not None:
            self._voice_listener_thread.join(timeout=0.5)

    def _voice_listener_loop(self):
        while not getattr(self, "_stop_listening", threading.Event()).is_set():
            self.after(0, lambda: self.footer_label.configure(text=self._footer_text("LISTENING")))
            spoken = self._listen() if self._listen is not None else ""
            if getattr(self, "_stop_listening", threading.Event()).is_set():
                break
            if not spoken:
                time.sleep(0.2)
                continue
            cleaned = self._normalize_voice_command(spoken)
            if cleaned:
                spoken = cleaned
            self.after(0, lambda: self.input_entry.delete(0, tk.END))
            self.after(0, lambda text=spoken: self.input_entry.insert(0, text))
            self.after(0, lambda: self._append_console("USER", spoken))
            self.after(0, lambda: self._append_console("ANGELIQUE", "Processing voice command..."))
            self.after(0, lambda: self.footer_label.configure(text=self._footer_text("PROCESSING")))
            self._process_command(spoken)
            time.sleep(0.2)
        self.after(0, lambda: self.footer_label.configure(text=self._footer_text("READY")))

    def _footer_text(self, status=None):
        status_text = status if status is not None else self._system_stats.get("status", "READY")
        return f"CPU {self._system_stats.get('cpu', 0)}%  |  MEMORY {self._system_stats.get('memory', 0)}%  |  NETWORK {self._system_stats.get('network_mbps', 0.0):.1f} Mbps  | STATUS: {status_text}"

    def _on_send(self, event=None):
        if getattr(self, "_input_placeholder_active", False):
            return
        text = self.input_entry.get().strip()
        if not text:
            return
        self.input_entry.delete(0, tk.END)
        if getattr(self, "_training_mode_enabled", False):
            text = f"[[TRAINING_MODE]] {text}"
        self._append_console("USER", text)
        self._append_console("ANGELIQUE", "Command received. Processing locally in the desktop interface.")
        self.footer_label.configure(text=self._footer_text("PROCESSING"))
        threading.Thread(target=self._process_command, args=(text,), daemon=True).start()

    def _on_terminal_execute(self, event=None):
        if event is not None:
            event.widget = None
        if getattr(self, "_terminal_placeholder_active", False):
            return
        command = self.terminal_text.get("1.0", tk.END).strip()
        if not command:
            return
        self.terminal_text.delete("1.0", tk.END)
        self._append_console("TERMINAL", command)
        self.footer_label.configure(text=self._footer_text("PROCESSING"))
        if self._terminal_backend_enabled:
            self._append_console("ANGELIQUE", "Processing terminal command through Angelique backend.")
            threading.Thread(target=self._process_command, args=(command,), daemon=True).start()
        else:
            self._append_console("ANGELIQUE", "Executing terminal command locally.")
            threading.Thread(target=self._run_shell_command, args=(command,), daemon=True).start()

    def _on_input_focus_in(self, event):
        if getattr(self, "_input_placeholder_active", False):
            self.input_entry.delete(0, tk.END)
            self.input_entry.config(fg=self._theme("text"))
            self._input_placeholder_active = False

    def _on_input_focus_out(self, event):
        if not self.input_entry.get().strip():
            self._set_input_placeholder()

    def _set_input_placeholder(self):
        self.input_entry.delete(0, tk.END)
        self.input_entry.insert(0, self._input_placeholder_text)
        self.input_entry.config(fg="#6f9bbd")
        self._input_placeholder_active = True

    def _on_terminal_focus_in(self, event):
        if getattr(self, "_terminal_placeholder_active", False):
            self.terminal_text.delete("1.0", tk.END)
            self.terminal_text.config(fg=self._theme("text"))
            self._terminal_placeholder_active = False

    def _on_terminal_focus_out(self, event):
        if not self.terminal_text.get("1.0", tk.END).strip():
            self._set_terminal_placeholder()

    def _set_terminal_placeholder(self):
        self.terminal_text.delete("1.0", tk.END)
        self.terminal_text.insert("1.0", self._terminal_placeholder_text)
        self.terminal_text.config(fg="#6f9bbd")
        self._terminal_placeholder_active = True

    def _is_privileged_command(self, command: str) -> bool:
        normalized = (command or "").strip().lower()
        if not normalized:
            return False
        privileged_prefixes = (
            "apt-get ",
            "apt ",
            "dnf ",
            "yum ",
            "pacman ",
            "zypper ",
            "systemctl ",
            "service ",
            "shutdown",
            "reboot",
            "mount ",
            "umount ",
            "useradd ",
            "usermod ",
            "userdel ",
        )
        return normalized.startswith(privileged_prefixes)

    def _needs_package_confirmation(self, command: str) -> bool:
        normalized = (command or "").strip().lower()
        return bool(re.match(r"^(apt-get|apt)\s+", normalized))

    def _prompt_for_sudo_password(self) -> str | None:
        password: str | None = None

        def ask_password():
            nonlocal password
            password = simpledialog.askstring(
                "Angelique authorization",
                "Enter your password to authorize this command:",
                show="*",
                parent=self,
            )

        if threading.current_thread() is threading.main_thread():
            ask_password()
            return password

        prompt_done = threading.Event()

        def ask_password_async():
            try:
                ask_password()
            finally:
                prompt_done.set()

        self.after(0, ask_password_async)
        prompt_done.wait()
        return password

    def _prompt_for_trade_symbol(self) -> str | None:
        result = {"symbol": None}
        dialog = tk.Toplevel(self)
        dialog.title("Trade Symbol")
        dialog.configure(bg=self._theme("panel"))
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        tk.Label(
            dialog,
            text="Enter the forex symbol you want to analyze:",
            wraplength=420,
            justify="left",
            fg=self._theme("text"),
            bg=self._theme("panel"),
            font=("Consolas", 11),
        ).pack(padx=18, pady=(18, 10), anchor="w")

        entry = tk.Entry(
            dialog,
            bg=self._theme("button_bg"),
            fg=self._theme("text"),
            insertbackground=self._theme("text"),
            bd=1,
            relief="solid",
            font=("Consolas", 11),
        )
        current_symbol, _ = self._get_selected_symbol_and_timeframe()
        entry.insert(0, current_symbol or config.DEFAULT_TRADING_SYMBOL)
        entry.pack(fill="x", padx=18, pady=(0, 18))
        entry.focus_set()

        button_row = tk.Frame(dialog, bg=self._theme("panel"))
        button_row.pack(fill="x", padx=18, pady=(0, 18), anchor="e")

        def submit():
            result["symbol"] = entry.get().strip().upper()
            dialog.destroy()

        def cancel():
            dialog.destroy()

        tk.Button(
            button_row,
            text="Cancel",
            command=cancel,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=16,
            pady=10,
            font=("Consolas", 11, "bold"),
        ).pack(side="right", padx=(0, 8))
        tk.Button(
            button_row,
            text="OK",
            command=submit,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=16,
            pady=10,
            font=("Consolas", 11, "bold"),
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        self._center_dialog(dialog)
        self.wait_window(dialog)
        return result["symbol"] if result["symbol"] else None

    def _confirm_dialog(self, title: str, message: str, confirm_text: str = "Yes", cancel_text: str = "No") -> bool:
        # Use the same visual style as the privileged password prompt
        result = {"confirmed": False}

        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.configure(bg=self._theme("panel"))
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        message_label = tk.Label(
            dialog,
            text=message,
            wraplength=520,
            justify="left",
            fg=self._theme("text"),
            bg=self._theme("panel"),
            font=("Consolas", 13),
        )
        message_label.pack(padx=18, pady=(18, 10), anchor="w")

        spacer = tk.Frame(dialog, bg=self._theme("panel"))
        spacer.pack(fill="x", padx=18)

        button_row = tk.Frame(dialog, bg=self._theme("panel"))
        button_row.pack(padx=18, pady=(12, 18), anchor="e")

        def submit():
            result["confirmed"] = True
            dialog.destroy()

        def cancel():
            dialog.destroy()

        tk.Button(
            button_row,
            text=cancel_text,
            command=cancel,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=16,
            pady=10,
            font=("Consolas", 11, "bold"),
        ).pack(side="right", padx=(10, 0))
        tk.Button(
            button_row,
            text=confirm_text,
            command=submit,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=16,
            pady=10,
            font=("Consolas", 11, "bold"),
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        self._center_dialog(dialog)
        self.wait_window(dialog)
        return result["confirmed"]

    def _prompt_for_privileged_command(self, command: str):
        result: dict[str, str | bool | None] = {"confirmed": False, "password": None, "auto_confirm": False}

        dialog = tk.Toplevel(self)
        dialog.title("Angelique authorization")
        dialog.configure(bg=self._theme("panel"))
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        message = tk.Label(
            dialog,
            text="This command requires authorization. Enter your password to continue.",
            wraplength=360,
            justify="left",
            fg=self._theme("text"),
            bg=self._theme("panel"),
            font=("Consolas", 11),
        )
        message.pack(padx=18, pady=(18, 10), anchor="w")

        password_var = tk.StringVar()
        password_entry = tk.Entry(
            dialog,
            textvariable=password_var,
            show="*",
            width=36,
            bg=self._theme("bg"),
            fg=self._theme("text"),
            insertbackground=self._theme("text"),
            relief="flat",
            bd=0,
        )
        password_entry.pack(padx=18, pady=(0, 14), fill="x")
        password_entry.focus_set()

        button_row = tk.Frame(dialog, bg=self._theme("panel"))
        button_row.pack(padx=18, pady=(0, 18), anchor="e")

        def submit():
            result["confirmed"] = True
            result["password"] = password_var.get()
            result["auto_confirm"] = True
            dialog.destroy()

        def cancel():
            result["confirmed"] = False
            dialog.destroy()

        tk.Button(
            button_row,
            text="Cancel",
            command=cancel,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=14,
            pady=8,
            font=("Consolas", 10, "bold"),
        ).pack(side="right", padx=(8, 0))
        tk.Button(
            button_row,
            text="Continue",
            command=submit,
            fg=self._theme("text"),
            bg=self._theme("button_bg"),
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            bd=0,
            padx=14,
            pady=8,
            font=("Consolas", 10, "bold"),
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        self._center_dialog(dialog)
        self.wait_window(dialog)
        if not result["confirmed"]:
            return None
        return result

    def _center_dialog(self, dialog):
        dialog.update_idletasks()
        width = dialog.winfo_width() or 460
        height = dialog.winfo_height() or 180
        x = self.winfo_x() + (self.winfo_width() - width) // 2
        y = self.winfo_y() + (self.winfo_height() - height) // 2
        dialog.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    def _register_shell_callbacks(self):
        try:
            from skills.os_control.system_cmds import set_privileged_command_callbacks

            set_privileged_command_callbacks(
                privileged_callback=self._prompt_for_privileged_command,
            )
        except Exception:
            pass

    def _run_shell_command(self, command: str):
        try:
            from skills.os_control.system_cmds import run_shell_command as system_run_shell_command

            result = system_run_shell_command(command)
            for line in str(result).splitlines():
                self.after(0, lambda l=line: self._append_console("TERMINAL", l))
        except Exception as exc:
            self.after(0, lambda: self._append_console("TERMINAL-ERR", f"Execution failed: {exc}"))
        finally:
            self.after(0, lambda: self.footer_label.configure(text=self._footer_text("READY")))

    def _process_command(self, text: str):
        if getattr(self, "_shutting_down", False):
            return

        normalized = text.strip().lower()
        if self._handle_local_control_command(normalized):
            self.after(0, lambda: self.footer_label.configure(text=self._footer_text("READY")))
            return
        if self.backend is None:
            self._load_backend()

        if not self.backend:
            response = "Unable to load Angelique runtime. Ensure the project is started from launcher.py."
        else:
            try:
                response = self.backend(text)
            except Exception as exc:
                response = f"Processing error: {exc}"

        self.after(0, lambda: self._finish_response(response))
        if self._speak_enabled and self._speak is not None:
            threading.Thread(target=self._speak_response, args=(response,), daemon=True).start()

    def _speak_response(self, response: str):
        if getattr(self, "_shutting_down", False):
            return
        try:
            if self._speak is not None:
                self._speak(response)
        except Exception:
            pass

    def _load_backend(self):
        try:
            from skills.conversation.chat_skill import handle_user_message, new_session
            # Ensure we have a session id for this GUI instance
            if not hasattr(self, "_session_id"):
                try:
                    self._session_id = new_session()
                except Exception:
                    self._session_id = "default"

            def _backend_wrapper(text: str) -> str:
                try:
                    res = handle_user_message(self._session_id, text)
                    answer = res.get("answer") if isinstance(res, dict) else res
                    if isinstance(answer, list):
                        return "\n".join(str(a) for a in answer)
                    return str(answer)
                except Exception as exc:
                    return f"Processing error: {exc}"

            self.backend = _backend_wrapper
        except Exception as exc:
            # Fallback to legacy cognitive loop if chat_skill unavailable
            try:
                from brain.cognitive_loop import run_cognitive_loop
                self.backend = run_cognitive_loop
            except Exception:
                self.backend = None
                self._append_console("SYSTEM", f"Backend load failed: {exc}")

    def _handle_local_control_command(self, normalized_text: str) -> bool:
        if not normalized_text:
            return False

        if any(cmd in normalized_text for cmd in ["exit angelique", "close angelique", "exit app", "quit angelique", "shutdown angelique"]):
            self._append_console("ANGELIQUE", "Okay. Closing Angelique now.")
            self.after(300, self.on_close)
            return True

        if "minimize" in normalized_text or "minimise" in normalized_text:
            self._minimize_window()
            self._append_console("ANGELIQUE", "Window minimized.")
            return True

        if "maximize" in normalized_text or "full screen" in normalized_text:
            self._toggle_maximize()
            self._append_console("ANGELIQUE", "Maximizing window.")
            return True

        if any(cmd in normalized_text for cmd in ["restore", "unminimize", "normalize window", "window back"]):
            self.deiconify()
            self._append_console("ANGELIQUE", "Window restored.")
            return True

        if any(cmd in normalized_text for cmd in ["shutdown computer", "power off", "turn off computer", "shut down computer"]):
            self._append_console("ANGELIQUE", "Shutting down the computer now.")
            threading.Thread(target=self._shutdown_computer, daemon=True).start()
            return True

        if any(cmd in normalized_text for cmd in ["restart computer", "reboot computer", "restart the system", "reboot the system"]):
            self._append_console("ANGELIQUE", "Restarting the computer now.")
            threading.Thread(target=self._restart_computer, daemon=True).start()
            return True

        return False

    def _shutdown_computer(self):
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["shutdown", "/s", "/t", "0"], check=False)
            elif sys.platform.startswith("darwin"):
                subprocess.run(["osascript", "-e", "tell app \"System Events\" to shut down"], check=False)
            else:
                subprocess.run(["sudo", "shutdown", "now"], check=False)
        except Exception as exc:
            self._append_console("SYSTEM", f"Failed to shutdown: {exc}")

    def _restart_computer(self):
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["shutdown", "/r", "/t", "0"], check=False)
            elif sys.platform.startswith("darwin"):
                subprocess.run(["osascript", "-e", "tell app \"System Events\" to restart"], check=False)
            else:
                subprocess.run(["sudo", "reboot"], check=False)
        except Exception as exc:
            self._append_console("SYSTEM", f"Failed to restart: {exc}")

    def _minimize_window(self):
        self.iconify()

    def _theme(self, key: str) -> str:
        return self._themes.get(self._theme_name, self._themes["blue"]).get(key, "#ffffff")

    def _set_theme(self, theme_name: str):
        if theme_name in self._themes:
            self._theme_name = theme_name
            self._append_console("SYSTEM", f"Theme set to {theme_name.upper()}.")
            self._apply_theme()

    def _apply_theme(self):
        theme = self._themes.get(self._theme_name, self._themes["blue"])
        self.configure(bg=theme["bg"])
        self.canvas.configure(bg=theme["bg"])
        if hasattr(self, "title_bar"):
            self.title_bar.configure(bg=theme["title_bg"])
        self.footer_bar.configure(bg=theme["panel"])

        for panel in [self.left_panel, self.center_panel, self.right_panel, self.bottom_panel]:
            panel.configure(bg=theme["panel"])

        if self._mode_label:
            self._mode_label.configure(bg=theme["panel"], fg=theme["accent"])
        self.footer_label.configure(fg=theme["accent"], bg=theme["panel"])
        self.speech_toggle.configure(
            fg=theme["text"],
            bg=theme["button_bg"],
            activebackground=theme["button_active"],
            activeforeground=theme["accent"],
        )
        self.resize_handle.configure(bg=theme["button_bg"])
        if hasattr(self, "command_frame"):
            self.command_frame.configure(bg=theme["panel"])
        self.input_entry.configure(
            bg=theme["bg"],
            fg=theme["text"],
            insertbackground=theme["text"],
            highlightbackground=theme["border"],
            highlightcolor=theme["accent"],
        )
        self.terminal_text.configure(
            bg=theme["bg"],
            fg=theme["text"],
            insertbackground=theme["text"],
            highlightbackground=theme["border"],
            highlightcolor=theme["accent"],
        )
        self.console_text.configure(bg=theme["bg"], fg=theme["text"], insertbackground=theme["text"])
        self._update_background()

    def _check_online(self) -> bool:
        try:
            with socket.create_connection((config.NETWORK_CHECK_HOST, config.NETWORK_CHECK_PORT), timeout=2):
                return True
        except Exception:
            return False

    def _refresh_trading_bridge_status(self):
        try:
            from skills.trading.engine.connection_manager import bridge_manager
            active = bridge_manager.get_status()
        except Exception:
            active = False

        if self._trading_bridge_dot is not None:
            color = self._theme("accent") if active else self._theme("border")
            try:
                self._trading_bridge_dot.delete("all")
                self._trading_bridge_dot.create_oval(2, 2, 10, 10, fill=color, outline="")
            except Exception:
                pass
        if self._trading_bridge_status_label is not None:
            try:
                self._trading_bridge_status_label.configure(
                    fg=self._theme("accent") if active else self._theme("text")
                )
            except Exception:
                pass

        if self._active_center_view == "trading":
            symbol, timeframe = self._get_selected_symbol_and_timeframe()
            status_text = "connected" if active else "disconnected"
            self.trading_status_var.set(
                f"{symbol} • {timeframe} • trading bridge {status_text}"
            )
        self.after(3000, self._refresh_trading_bridge_status)

    def _refresh_online_status(self):
        if self._network_status_locked:
            return
        online = self._check_online()
        self._is_online = online
        self._update_mode_label()
        state = "REMOTE MODE ENABLED" if online else "LOCAL MODE ENABLED"
        self._append_console("SYSTEM", f"{state}.")
        self._network_status_locked = True

    def _update_mode_label(self):
        if self._mode_label:
            label_text = "REMOTE MODE ENABLED" if self._is_online else "LOCAL MODE ENABLED"
            self._mode_label.configure(text=label_text, fg=self._theme("accent"), bg=self._theme("panel"))

    def _initialize_runtime(self):
        self._load_backend()
        self._listen = listen
        self._speak = speak
        self._voice_available = False
        self._speak_available = False

        if self._listen is None or self._speak is None:
            try:
                from skills.voice.voice_interface import listen as _listen, speak as _speak
                self._listen = _listen
                self._speak = _speak
                self._voice_available = True
                self._speak_available = True
            except Exception as exc:
                self._voice_available = False
                self._speak_available = False
                self._append_console("SYSTEM", f"Voice engine load failed: {exc}")
        else:
            self._voice_available = True
            self._speak_available = True

        if not self._voice_available:
            self._append_console("SYSTEM", "Voice input unavailable. Microphone commands will not work.")
        if not self._speak_available:
            self._append_console("SYSTEM", "Voice output unavailable. Responses will not remain silent.")

        try:
            from main import launch_mt5_bridge_if_needed
            from skills.trading.engine.connection_manager import bridge_manager as _bridge_manager

            self._append_console("SYSTEM", "Bootstrapping MT5 bridge for GUI mode...")
            bridge_launched = launch_mt5_bridge_if_needed()
            if bridge_launched:
                self._append_console("SYSTEM", "MT5 bridge process started successfully.")
            else:
                self._append_console("SYSTEM", "MT5 bridge bootstrap failed or bridge already unavailable.")

            self._bridge_manager = _bridge_manager
            self._bridge_manager.start()
            if self._bridge_manager.get_status():
                self._append_console("SYSTEM", "MT5 bridge connected successfully.")
            else:
                last_error = self._bridge_manager.get_last_error() or "unknown"
                self._append_console("SYSTEM", f"MT5 bridge not connected yet: {last_error}")
        except Exception as exc:
            self._append_console("SYSTEM", f"MT5 trading bridge initialization error: {exc}")

        if not self._check_online():
            self._voice_available = False
            self._speak_available = False
            self._append_console("SYSTEM", "Offline mode detected. Voice input/output disabled; using text-only mode.")

    def _toggle_voice_output(self):
        self._speak_enabled = not self._speak_enabled
        label = "VOICE OUTPUT ON" if self._speak_enabled else "VOICE OUTPUT OFF"
        self.speech_toggle.configure(text=label)
        status = "enabled" if self._speak_enabled else "disabled"
        self._append_console("SYSTEM", f"Voice output {status}.")

    def _finish_response(self, response: str):
        if getattr(self, "_shutting_down", False):
            return
        self._append_console("ANGELIQUE", response)
        self.footer_label.configure(text=self._footer_text("READY"))

    def _start_move(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _do_move(self, event):
        x = self.winfo_x() + event.x - self._drag_x
        y = self.winfo_y() + event.y - self._drag_y
        self.geometry(f"+{x}+{y}")

    def _toggle_maximize(self):
        if self._is_maximized:
            if self._last_geometry:
                self.geometry(self._last_geometry)
            self._is_maximized = False
        else:
            self._last_geometry = self.geometry()
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
            self._is_maximized = True

    def _start_resize(self, event):
        self._resize_start_x = event.x_root
        self._resize_start_y = event.y_root
        self._resize_start_width = self.winfo_width()
        self._resize_start_height = self.winfo_height()

    def _do_resize(self, event):
        delta_x = event.x_root - self._resize_start_x
        delta_y = event.y_root - self._resize_start_y
        new_width = max(1000, self._resize_start_width + delta_x)
        new_height = max(700, self._resize_start_height + delta_y)
        self.geometry(f"{new_width}x{new_height}")

    def _on_resize(self, event):
        if event.widget is self:
            self._update_background()
            self._draw_ring_hud()
            self._update_avatar()

    def _on_center_panel_resize(self, event):
        self._draw_ring_hud()
        self._update_avatar()

    def _get_timestamp(self):
        from datetime import datetime

        return datetime.now().strftime("%H:%M:%S")

    def on_close(self):
        if getattr(self, "_shutting_down", False):
            return
        self._shutting_down = True
        try:
            self._stop_voice_listener()
        except Exception:
            pass
        try:
            release_lock = getattr(self, "_release_lock", None)
            if callable(release_lock):
                try:
                    release_lock()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            from skills.conversation.chat_skill import close_session
            close_session("default")
        except Exception:
            pass
        self.destroy()

    def _exit_angelique(self):
        self._append_console("USER", "EXIT ANGELIQUE")
        self._append_console("ANGELIQUE", "Shutting down the Angelique desktop interface...")
        self.after(100, self.on_close)


def main():
    try:
        app = AngeliqueDesktopApp()
        app.mainloop()
    except tk.TclError as exc:
        print(f"GUI startup failed: {exc}")
        print("No usable display is available in this environment. Launch from a desktop session or with a virtual display.")
    except Exception as exc:
        print(f"GUI startup failed: {exc}")


if __name__ == "__main__":
    if os.environ.get(config.ANGELIQUE_LAUNCHED_ENV) == "1":
        main()
    else:
        print("Please start Angelique via launcher.py. Run: python3 launcher.py")
