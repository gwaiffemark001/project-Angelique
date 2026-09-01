import math
import json
import os
import re
import socket
import subprocess
import wave
import struct
import sys
import threading
import time
from datetime import datetime, timezone
import tkinter as tk
from collections import deque
from tkinter import simpledialog, messagebox, scrolledtext, ttk
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import config
from gui.trading_hub_controller import TradingHubController
#[main 44abb76] restore point
#[main 53c3b9b] new restore
#[main ba52bb9] reversal
#[main 1081cdc] report
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
    from skills.wifi_control.router_client import allow_device_forever, allow_device_for_duration, disconnect_device, list_connected_devices, list_disconnected_devices
except ImportError:
    list_connected_devices = None
    allow_device_forever = None
    allow_device_for_duration = None
    disconnect_device = None
    list_disconnected_devices = None

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


def _fmt_signal_value(value: Any, digits: int = 5) -> str:
    try:
        return f"{float(value):.{max(0, int(digits))}f}"
    except (TypeError, ValueError):
        return "--"


def _fmt_signal_spread(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "--"


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
        self._ring_animation_job = None
        self._button_hover_cache = {}
        self._ring_particles = []
        self._ring_arc_ids = []
        self._ring_arc_config = []
        self._ring_particle_ids = []
        self._ring_node_ids = []
        self._ring_node_meta = {}
        self._ring_state = {}
        self._ring_focus = None
        self._trading_scan_stop_event = threading.Event()
        self._avatar_status_text_id = None
        self._avatar_status_blink_job = None
        self._avatar_status_mode = None
        self._avatar_status_dot_count = 0
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
            "_avatar_status_text_id": None,
            "_avatar_status_blink_job": None,
            "_avatar_status_mode": None,
            "_avatar_status_dot_count": 0,
            "_trading_chart_view_count": 80,
            "_trading_chart_view_offset": 0,
            "_chart_selection_rect_id": None,
            "_last_chart_data": None,
            "_chart_tooltip": None,
            "_last_full_candles": None,
            "_trading_monitor_running": False,
            "_trading_monitor_signature": None,
            "_trading_monitor_popup_open": False,
            "_trading_monitor_status_var": None,
            "_trading_monitor_scan_active": False,
            "_trading_refresh_pending": False,
            "_trading_refresh_generation": 0,
            "_signal_refresh_job": None,
            "_signal_refresh_running": False,
            "_signal_generation": 0,
            "_signal_notifications": [],
            "_signal_plan_history": {},
            "_signal_symbol_var": None,
            "_signal_status_var": None,
            "_signal_route_var": None,
            "_signal_notification_var": None,
            "_signal_card_vars": {},
            "_signal_plan_text": None,
            "_signal_report": None,
            "_signal_evidence_tree": None,
            "_signal_smc_text": None,
            "_signal_ict_text": None,
            "_signal_structure_text": None,
            "_signal_news_tree": None,
            "_signal_calendar_tree": None,
            "_chart_tool_var": "CROSSHAIR",
            "_chart_crosshair_ids": [],
            "_chart_tool_points": [],
            "_chart_drawing_ids": [],
            "_chart_drawings": [],
            "_chart_drag_active": False,
            "_volume_profile_enabled": True,
            "_volume_profile_rows": 30,
            "_volume_profile_value_area": 0.70,
            "_calculator_specs": {},
            "_command_in_progress": False,
            "_pending_command_queue": deque(),
            "_speak_enabled": True,
            "_voice_listener_thread": None,
            "_stop_listening": None,
            "_trading_status_var": None,
            "_trading_detail_var": None,
            "_wifi_refresh_pending": False,
            "_wifi_generation": 0,
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
        self._speak_enabled = True
        self._gui_settings_path = Path.home() / ".config" / "angelique" / "gui_settings.json"
        self._gui_settings = self._load_gui_settings()
        self._voice_listener_thread = None
        self._stop_listening = None
        self.center_title_label = None
        self.center_status_label = None
        self.ring_canvas = None
        self.trading_view_frame = None
        self.trading_status_var = None
        self.trading_detail_var = None
        self._trading_hub_controller = TradingHubController(self._gui_settings.get("trading_mode", "DAY_TRADING"))
        self.wifi_view_frame = None
        self._wifi_status_var = None
        self._wifi_detail_var = None
        self.signal_view_frame = None

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
        # overrideredirect title bars can make Tk's "zoomed" state a no-op on
        # Ubuntu. Set an explicit screen-sized geometry after widgets exist so
        # the original panels/buttons are not clipped into the default 400x300
        # window.
        try:
            self.update_idletasks()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            width, height = max(1200, sw), max(760, sh)
            self.geometry(f"{width}x{height}+0+0")
            self.minsize(1200, 760)
        except tk.TclError:
            pass
        self.attributes("-topmost", False)
        self._bind_events()
        # Do not block the Tk event loop while loading model/voice/network subsystems.
        threading.Thread(target=self._initialize_runtime, daemon=True).start()
        self._update_system_metrics()
        # Start mission ticker updates so the right-panel 'MISSION STATUS' shows live info
        try:
            self._update_mission_ticker()
        except Exception:
            pass
        self._refresh_trading_bridge_status()
        self._start_trading_monitor()
        self._start_position_management_loop()
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

    def _apply_button_style(self, button, active=False, hover=False):
        bg = self._theme("button_active") if active else self._theme("button_bg")
        if hover:
            bg = self._theme("button_active")
        button.configure(
            fg=self._theme("accent") if hover or active else self._theme("text"),
            bg=bg,
            activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"),
            highlightthickness=0,
            cursor="hand2",
        )

    def _bind_button_feedback(self, button, command=None):
        def _run():
            if command is not None:
                self.after_idle(command)

        def _enter(event):
            self._apply_button_style(button, hover=True)

        def _leave(event):
            self._apply_button_style(button, active=False, hover=False)

        def _press(event):
            self._apply_button_style(button, active=True)

        def _release(event):
            self._apply_button_style(button, active=False, hover=False)

        button.bind("<Enter>", _enter)
        button.bind("<Leave>", _leave)
        button.bind("<ButtonPress-1>", _press)
        button.bind("<ButtonRelease-1>", _release)
        if command is not None:
            button.configure(command=_run)
        return button

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
            relief="flat",
            highlightthickness=0,
            cursor="hand2",
        )
        self._bind_button_feedback(button, command)
        button.pack(side="right", padx=(4, 0))
        return button


    def _create_frames(self):
        """Build the system-wide home shell.

        The home page is intentionally not trading-centric.  The centre is a
        large interactive Angelique core, while the side rails expose system
        telemetry and command/navigation controls without the old four-card
        matrix.  Trading/Signals/Wi-Fi views continue to reuse these panels.
        """
        self.left_panel = self._create_panel(self._theme("panel"))
        self.center_panel = self._create_panel(self._theme("panel"))
        self.right_panel = self._create_panel(self._theme("panel"))
        self.bottom_panel = self._create_panel(self._theme("panel"))
        self.footer_bar = tk.Frame(self, bg=self._theme("panel"), height=34)

        # Home: dominant centre core with slimmer utility rails.
        self.left_panel.place(relx=0.018, rely=0.055, relwidth=0.205, relheight=0.68)
        self.center_panel.place(relx=0.235, rely=0.055, relwidth=0.53, relheight=0.68)
        self.right_panel.place(relx=0.782, rely=0.055, relwidth=0.20, relheight=0.68)
        self.bottom_panel.place(relx=0.018, rely=0.755, relwidth=0.964, relheight=0.19)
        self.footer_bar.place(relx=0, rely=0.95, relwidth=1, height=34)

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
            self.left_panel, text="SYSTEM INTEL", fg=self._theme("accent"),
            bg=self._theme("panel"), font=("Consolas", 14, "bold")
        )
        header.pack(anchor="nw", padx=16, pady=(16, 10))

        # Compact live telemetry, intentionally free of large card blocks.
        self._temperature_label = self._create_status_row(self.left_panel, "CORE TEMPERATURE", "N/A")
        self._cpu_label = self._create_status_row(self.left_panel, "NEURAL LOAD", "0%")
        self._memory_label = self._create_status_row(self.left_panel, "MEMORY STABILITY", "0%")
        self._network_label = self._create_status_row(self.left_panel, "NETWORK BANDWIDTH", "0 Mbps")

        divider = tk.Frame(self.left_panel, bg=self._theme("border"), height=1)
        divider.pack(fill="x", padx=16, pady=12)

        tk.Label(
            self.left_panel, text="ACTIVE SUBSYSTEMS", fg=self._theme("accent"),
            bg=self._theme("panel"), font=("Consolas", 10, "bold")
        ).pack(anchor="nw", padx=16, pady=(0, 4))
        for label, active, store in [
            ("Vision Matrix", True, None),
            ("Voice Layer", True, None),
            ("Trading Bridge", False, "trading_bridge"),
            ("Memory Vault", True, None),
        ]:
            self._create_subsystem_label(self.left_panel, label, active, store_as=store)

        divider2 = tk.Frame(self.left_panel, bg=self._theme("border"), height=1)
        divider2.pack(fill="x", padx=16, pady=12)
        tk.Label(
            self.left_panel, text="SYSTEM SIGNAL", fg=self._theme("accent"),
            bg=self._theme("panel"), font=("Consolas", 10, "bold")
        ).pack(anchor="nw", padx=16, pady=(0, 6))
        self._home_signal_label = tk.Label(
            self.left_panel,
            text="CORE NOMINAL\nWaiting for subsystem input...",
            fg=self._theme("text"), bg=self._theme("panel"),
            font=("Consolas", 9), justify="left", anchor="nw"
        )
        self._home_signal_label.pack(fill="x", padx=16)
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
            self.center_panel, text="ANGELIQUE CORE", fg=self._theme("accent"),
            bg=self._theme("panel"), font=("Consolas", 17, "bold")
        )
        self.center_title_label.pack(anchor="n", pady=(14, 4))

        self.ring_canvas = tk.Canvas(
            self.center_panel, bg=self._theme("panel"), highlightthickness=0
        )
        self.ring_canvas.pack(fill="both", expand=True, padx=6, pady=(4, 4))
        self.center_panel.bind("<Configure>", self._on_center_panel_resize)
        self._draw_ring_hud()
        self._animate_ring()

        self.avatar_label = None
        self._update_avatar()

        self.center_status_label = tk.Label(
            self.center_panel,
            text="SYSTEM-WIDE SYNTHESIS CONTROL",
            fg=self._theme("accent"), bg=self._theme("panel"),
            font=("Consolas", 10, "bold")
        )
        self.center_status_label.pack(anchor="s", pady=(4, 12))

        self._build_trading_view()
        self._build_signal_view()
        self._build_wifi_view()
        self._show_home_view()
    def _build_trading_view(self):
        """Build a space-efficient Trading Hub dashboard.

        The old layout stacked many long status labels above the chart, which
        consumed most of the vertical viewport and left the actionable controls
        visually disconnected from the chart.  This version uses a compact
        header, a single control/status rail, a three-column market workspace,
        and a fixed-height position monitor so the important controls remain
        visible at 900p/1080p without overlap.
        """
        self.trading_view_frame = tk.Frame(self, bg=self._theme("panel"))
        self.trading_view_frame.place_forget()

        frame = self.trading_view_frame
        for col, weight in ((0, 0), (1, 1), (2, 0)):
            frame.grid_columnconfigure(col, weight=weight)
        for row, weight in ((0, 0), (1, 0), (2, 0), (3, 1), (4, 0), (5, 0)):
            frame.grid_rowconfigure(row, weight=weight)

        # ---------- Header ----------
        header = tk.Frame(frame, bg=self._theme("title_bg"), bd=1, relief="solid")
        header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=14, pady=(8, 5))
        header.grid_columnconfigure(1, weight=1)

        tk.Label(header, text="TRADING HUB", fg=self._theme("accent"),
                 bg=self._theme("title_bg"), font=("Consolas", 16, "bold")).grid(
                     row=0, column=0, sticky="w", padx=12, pady=7)
        self.trading_status_var = tk.StringVar(value="Trading status initializing...")
        tk.Label(header, textvariable=self.trading_status_var, fg=self._theme("text"),
                 bg=self._theme("title_bg"), font=("Consolas", 9), anchor="w").grid(
                     row=0, column=1, sticky="ew", padx=10)
        self._trading_bridge_error_var = tk.StringVar(value="Bridge status unknown.")
        tk.Label(header, textvariable=self._trading_bridge_error_var, fg=self._theme("text"),
                 bg=self._theme("title_bg"), font=("Consolas", 8, "italic"), anchor="e").grid(
                     row=0, column=2, sticky="e", padx=12)

        self._trading_mode_banner_var = tk.StringVar(value="Preparing trading status...")
        self._strategy_mode_var = tk.StringVar(value=f"ACTIVE MODE: {self._trading_hub_controller.trading_mode}")
        self._strategy_profile_var = tk.StringVar(value="")
        self._risk_policy_var = tk.StringVar(value="RISK 1.00% | MAX 1.00% | HIGH IMPACT → MANUAL")

        # ---------- Compact control rail ----------
        controls = tk.Frame(frame, bg=self._theme("panel_alt"), bd=1, relief="solid")
        controls.grid(row=1, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 5))
        controls.grid_columnconfigure(5, weight=1)

        def label(parent, text, col, **kw):
            opts = dict(fg=self._theme("text"), bg=self._theme("panel_alt"), font=("Consolas", 9, "bold"))
            opts.update(kw)
            tk.Label(parent, text=text, **opts).grid(row=0, column=col, padx=6, pady=6, sticky="w")

        label(controls, "MODE", 0)
        for idx, (mode, txt) in enumerate((("DAY_TRADING", "DAY"), ("SWING_TRADING", "SWING")), start=1):
            tk.Button(controls, text=txt,
                      command=lambda selected=mode: self._on_strategy_mode_change(selected),
                      fg=self._theme("text"), bg=self._theme("button_bg"),
                      activebackground=self._theme("button_active"), activeforeground=self._theme("accent"),
                      bd=0, padx=10, pady=4, font=("Consolas", 8, "bold")).grid(
                          row=0, column=idx, padx=2, pady=4)
        tk.Label(controls, textvariable=self._strategy_mode_var, fg=self._theme("accent"),
                 bg=self._theme("panel_alt"), font=("Consolas", 8, "bold")).grid(
                     row=0, column=3, padx=(7, 12), sticky="w")

        label(controls, "SYMBOL", 4)
        symbols = self._get_market_symbols()
        self._symbol_var = tk.StringVar(value=symbols[0] if symbols else config.DEFAULT_TRADING_SYMBOL)
        self._symbol_var.trace_add("write", lambda *args: self._refresh_trading_view())
        self._symbol_menu = tk.OptionMenu(controls, self._symbol_var, *(symbols or [config.DEFAULT_TRADING_SYMBOL]))
        self._symbol_menu.configure(bg=self._theme("button_bg"), fg=self._theme("text"),
                                    activebackground=self._theme("button_active"), activeforeground=self._theme("accent"),
                                    bd=0, highlightthickness=0, font=("Consolas", 9))
        self._symbol_menu.grid(row=0, column=5, padx=2, pady=4, sticky="w")

        label(controls, "TF", 6)
        self._timeframe_var = tk.StringVar(value=config.DEFAULT_TRADING_TIMEFRAME)
        self._timeframe_var.trace_add("write", lambda *args: self._refresh_trading_view())
        timeframe_menu = tk.OptionMenu(controls, self._timeframe_var, *config.TRADING_TIMEFRAMES)
        timeframe_menu.configure(bg=self._theme("button_bg"), fg=self._theme("text"),
                                 activebackground=self._theme("button_active"), activeforeground=self._theme("accent"),
                                 bd=0, highlightthickness=0, font=("Consolas", 9))
        timeframe_menu.grid(row=0, column=7, padx=2, pady=4)

        label(controls, "ACCOUNT", 8)
        account_mode = self._gui_settings.get("account_mode", "demo")
        self._account_mode_var = tk.StringVar(value=account_mode)
        account_mode_menu = tk.OptionMenu(controls, self._account_mode_var, "demo", "real", command=self._on_account_mode_change)
        account_mode_menu.configure(bg=self._theme("button_bg"), fg=self._theme("text"),
                                     activebackground=self._theme("button_active"), activeforeground=self._theme("accent"),
                                     bd=0, highlightthickness=0, font=("Consolas", 9))
        account_mode_menu.grid(row=0, column=9, padx=2, pady=4)

        # Live MT5 badge sits in the same rail instead of floating over the header.
        self._mt5_data_badge_var = tk.StringVar(value="")
        self._mt5_data_badge_label = tk.Label(controls, textvariable=self._mt5_data_badge_var,
                                              fg="#ffffff", bg="#16a34a",
                                              font=("Consolas", 8, "bold"), padx=7, pady=3)
        self._mt5_data_badge_label.grid(row=0, column=10, padx=(10, 7), pady=3, sticky="e")
        self._mt5_tooltip = None
        self._mt5_data_badge_label.bind("<Enter>", lambda e: self._show_mt5_tooltip(e))
        self._mt5_data_badge_label.bind("<Leave>", lambda e: self._hide_mt5_tooltip(e))

        # ---------- Context/status strip ----------
        status_strip = tk.Frame(frame, bg=self._theme("panel"))
        status_strip.grid(row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 5))
        status_strip.grid_columnconfigure(0, weight=4, uniform="status")
        status_strip.grid_columnconfigure(1, weight=5, uniform="status")
        status_strip.grid_columnconfigure(2, weight=3, uniform="status")

        def status_box(column, title, var, accent=False):
            box = tk.Frame(status_strip, bg=self._theme("panel_alt"), bd=1, relief="solid")
            box.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 4, 4 if column < 2 else 0))
            tk.Label(box, text=title, fg=self._theme("text"), bg=self._theme("panel_alt"),
                     font=("Consolas", 7, "bold"), anchor="w").pack(anchor="w", padx=8, pady=(4, 0))
            tk.Label(box, textvariable=var, fg=self._theme("accent" if accent else "text"),
                     bg=self._theme("panel_alt"), font=("Consolas", 8, "bold" if accent else "normal"),
                     anchor="w", justify="left").pack(fill="x", padx=8, pady=(1, 5))

        self._trading_health_var = tk.StringVar(value="TRADING HEALTH: CHECKING...")
        self._trading_monitor_status_var = tk.StringVar(value="ANGELIQUE MONITOR: STARTING...")
        self.trading_detail_var = tk.StringVar(value="Awaiting trading actions...")
        status_box(0, "SYSTEM HEALTH", self._trading_health_var)
        status_box(1, "MONITOR", self._trading_monitor_status_var)
        status_box(2, "EXECUTION / PLAN", self._trading_mode_banner_var, True)

        # ---------- Main market workspace ----------
        workspace = tk.Frame(frame, bg=self._theme("panel"))
        workspace.grid(row=3, column=0, columnspan=3, sticky="nsew", padx=14, pady=(0, 6))
        workspace.grid_columnconfigure(0, weight=0, minsize=270)
        workspace.grid_columnconfigure(1, weight=1, minsize=520)
        workspace.grid_columnconfigure(2, weight=0, minsize=270)
        workspace.grid_rowconfigure(0, weight=1)
        workspace.grid_propagate(False)

        # Account rail
        account_frame = tk.Frame(workspace, bg=self._theme("panel"), bd=1, relief="solid", width=270)
        account_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        account_frame.pack_propagate(False)
        account_frame.grid_propagate(False)
        tk.Label(account_frame, text="ACCOUNT\nSUMMARY", fg=self._theme("accent"), bg=self._theme("panel"),
                 font=("Consolas", 9, "bold"), justify="left", anchor="w").pack(anchor="w", padx=8, pady=(7, 4))
        self._account_labels = {}
        account_summary_body = tk.Frame(account_frame, bg=self._theme("panel"))
        account_summary_body.pack(fill="both", expand=True, padx=5, pady=(0, 5), anchor="n")
        account_grid = tk.Frame(account_summary_body, bg=self._theme("panel"))
        account_grid.pack(fill="x", anchor="n")
        account_grid.grid_columnconfigure(0, weight=1)
        account_fields = [
            "Balance", "Equity", "Used Margin", "Free Margin", "Margin Level", "Leverage",
            "Currency", "Risk %", "Risk Amount", "Daily Loss", "Weekly Loss", "Drawdown",
            "Consecutive Losses", "Max Risk", "Current Open Risk",
        ]
        for index, field_name in enumerate(account_fields):
            cell = tk.Frame(account_grid, bg=self._theme("panel_alt"), bd=0)
            cell.grid(row=index, column=0, sticky="ew", padx=2, pady=2)
            cell.grid_columnconfigure(0, weight=1)
            cell.grid_columnconfigure(1, weight=1)
            tk.Label(cell, text=field_name, fg=self._theme("text"), bg=self._theme("panel_alt"),
                     font=("Consolas", 6, "bold"), anchor="w", justify="left").grid(row=0, column=0, sticky="w", padx=6, pady=3)
            value_label = tk.Label(cell, text="—", fg=self._theme("accent"), bg=self._theme("panel_alt"),
                                   font=("Consolas", 8, "bold"), anchor="e")
            value_label.grid(row=0, column=1, sticky="e", padx=6, pady=3)
            key = field_name.lower().replace(" ", "_").replace("%", "percent")
            self._account_labels[key] = value_label

        # Chart rail
        chart_frame = tk.Frame(workspace, bg=self._theme("panel"), bd=1, relief="solid")
        chart_frame.grid(row=0, column=1, sticky="nsew")
        chart_frame.grid_rowconfigure(2, weight=1)
        chart_frame.grid_columnconfigure(0, weight=1)
        chart_head = tk.Frame(chart_frame, bg=self._theme("panel"))
        chart_head.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 4))
        chart_head.grid_columnconfigure(0, weight=1)
        tk.Label(chart_head, text="MARKET CHART", fg=self._theme("accent"), bg=self._theme("panel"),
                 font=("Consolas", 11, "bold")).grid(row=0, column=0, sticky="w")
        tk.Button(chart_head, text="−", command=self._zoom_out_chart, fg=self._theme("text"), bg=self._theme("button_bg"),
                  activebackground=self._theme("button_active"), bd=0, padx=8, pady=1, font=("Consolas", 10, "bold")).grid(row=0, column=1, padx=2)
        tk.Button(chart_head, text="+", command=self._zoom_in_chart, fg=self._theme("text"), bg=self._theme("button_bg"),
                  activebackground=self._theme("button_active"), bd=0, padx=8, pady=1, font=("Consolas", 10, "bold")).grid(row=0, column=2, padx=2)
        tools = tk.Frame(chart_frame, bg=self._theme("panel"))
        tools.grid(row=1, column=0, sticky="ew", padx=9, pady=(0, 3))
        tk.Label(tools, text="TOOLS", fg=self._theme("text"), bg=self._theme("panel"), font=("Consolas", 7, "bold")).pack(side="left", padx=(0, 4))
        self._chart_tool_var = tk.StringVar(value="CROSSHAIR")
        for tool in ("CROSSHAIR", "VLINE", "HLINE"):
            tk.Radiobutton(tools, text=tool, variable=self._chart_tool_var, value=tool,
                           indicatoron=False, fg=self._theme("text"), bg=self._theme("button_bg"),
                           selectcolor=self._theme("button_active"), activebackground=self._theme("button_active"),
                           activeforeground=self._theme("accent"), bd=0, padx=5, pady=2,
                           font=("Consolas", 7, "bold")).pack(side="left", padx=1)
        self._volume_profile_var = tk.BooleanVar(value=True)
        tk.Checkbutton(tools, text="VOL PROFILE", variable=self._volume_profile_var,
                       command=lambda: self._redraw_chart_view(), indicatoron=False,
                       fg=self._theme("text"), bg=self._theme("button_bg"), selectcolor=self._theme("button_active"),
                       activebackground=self._theme("button_active"), activeforeground=self._theme("accent"),
                       bd=0, padx=5, pady=2, font=("Consolas", 7, "bold")).pack(side="left", padx=2)
        self.trading_chart_canvas = tk.Canvas(chart_frame, bg=self._theme("panel_alt"), highlightthickness=0)
        self.trading_chart_canvas.grid(row=2, column=0, sticky="nsew", padx=9, pady=(0, 9))
        self.trading_chart_canvas.bind("<Configure>", self._on_trading_chart_resize)
        self._draw_trading_placeholder_chart()

        # Right rail: MT5 Data Window ABOVE Market Context.
        right_rail = tk.Frame(workspace, bg=self._theme("panel"), width=270)
        right_rail.grid(row=0, column=2, sticky="nsew", padx=(7, 0))
        right_rail.pack_propagate(False)
        right_rail.grid_propagate(False)
        right_rail.grid_rowconfigure(0, weight=0, minsize=132)
        right_rail.grid_rowconfigure(1, weight=1)
        right_rail.grid_columnconfigure(0, weight=1)

        data_window = tk.Frame(right_rail, bg=self._theme("panel"), bd=1, relief="solid")
        data_window.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        tk.Label(data_window, text="DATA WINDOW", fg=self._theme("accent"), bg=self._theme("panel"),
                 font=("Consolas", 9, "bold")).pack(anchor="w", padx=8, pady=(6, 3))
        self._data_window_text = tk.Text(data_window, bg="#07131f", fg=self._theme("text"),
                                         insertbackground=self._theme("text"), bd=0, relief="flat",
                                         font=("Consolas", 8), padx=6, pady=5, wrap="none")
        self._data_window_text.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self._data_window_text.insert("1.0", "Move the cursor over a candle to inspect it.\n\nLive quote: --\nSpread: --")
        self._data_window_text.configure(state="disabled")

        context_frame = tk.Frame(right_rail, bg=self._theme("panel"), bd=1, relief="solid")
        context_frame.grid(row=1, column=0, sticky="nsew")
        tk.Label(context_frame, text="MARKET\nCONTEXT", fg=self._theme("accent"), bg=self._theme("panel"),
                 font=("Consolas", 9, "bold"), justify="left", anchor="w").pack(anchor="w", padx=9, pady=(7, 4))
        tk.Label(context_frame, text="STRATEGY PROFILE", fg=self._theme("text"), bg=self._theme("panel"),
                 font=("Consolas", 7, "bold")).pack(anchor="w", padx=9)
        tk.Label(context_frame, textvariable=self._strategy_profile_var, fg=self._theme("text"), bg=self._theme("panel"),
                 font=("Consolas", 7), justify="left", anchor="w", wraplength=255).pack(fill="x", padx=9, pady=(1, 5))
        tk.Label(context_frame, text="RISK POLICY", fg=self._theme("text"), bg=self._theme("panel"),
                 font=("Consolas", 7, "bold")).pack(anchor="w", padx=9)
        tk.Label(context_frame, textvariable=self._risk_policy_var, fg=self._theme("accent"), bg=self._theme("panel"),
                 font=("Consolas", 7, "bold"), justify="left", anchor="w", wraplength=255).pack(fill="x", padx=9, pady=(1, 5))
        tk.Label(context_frame, text="CURRENT PLAN STATUS", fg=self._theme("text"), bg=self._theme("panel"),
                 font=("Consolas", 7, "bold")).pack(anchor="w", padx=9)
        tk.Label(context_frame, textvariable=self._trading_mode_banner_var, fg=self._theme("accent"), bg=self._theme("panel"),
                 font=("Consolas", 7, "bold"), justify="left", anchor="w", wraplength=255).pack(fill="x", padx=9, pady=(1, 5))
        tk.Label(context_frame, text="BRIDGE", fg=self._theme("text"), bg=self._theme("panel"),
                 font=("Consolas", 7, "bold")).pack(anchor="w", padx=9)
        tk.Label(context_frame, textvariable=self._trading_bridge_error_var, fg=self._theme("text"), bg=self._theme("panel"),
                 font=("Consolas", 7), justify="left", anchor="w", wraplength=255).pack(fill="x", padx=9, pady=(1, 4))
        nav = tk.Frame(context_frame, bg=self._theme("panel"))
        nav.pack(fill="x", side="bottom", padx=7, pady=7)
        self._signal_button = tk.Button(nav, text="SIGNALS", command=self._show_signal_view,
            fg=self._theme("text"), bg=self._theme("button_bg"), activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"), bd=0, padx=8, pady=6, font=("Consolas", 8, "bold"))
        self._signal_button.pack(fill="x")

        self._update_strategy_profile_display()

        # Chart bindings. VLINE/HLINE are one-click tools; clicking an
        # existing VLINE/HLINE removes it so drawings remain directly editable.
        self._chart_tooltip = tk.Label(self.trading_chart_canvas, bg=self._theme("panel"), fg=self._theme("text"),
                                       bd=1, relief="solid", font=("Consolas", 8), padx=5, pady=3)
        self.trading_chart_canvas.bind("<Motion>", self._on_chart_motion, add="+")
        self.trading_chart_canvas.bind("<Leave>", lambda e: self._hide_chart_tooltip(), add="+")
        self.trading_chart_canvas.bind("<ButtonPress-1>", self._on_chart_button_press, add="+")
        self.trading_chart_canvas.bind("<B1-Motion>", self._on_chart_button_motion, add="+")
        self.trading_chart_canvas.bind("<ButtonRelease-1>", self._on_chart_button_release, add="+")
        self.trading_chart_canvas.bind("<Escape>", lambda e: self._reset_chart_tool_state(), add="+")
        self.trading_chart_canvas.focus_set()
        # ---------- Position monitor ----------
        positions_frame = tk.Frame(frame, bg=self._theme("panel"), bd=1, relief="solid")
        positions_frame.grid(row=4, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 5))
        positions_frame.grid_columnconfigure(0, weight=1)
        head = tk.Frame(positions_frame, bg=self._theme("panel"))
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=(5, 3))
        head.grid_columnconfigure(1, weight=1)
        tk.Label(head, text="POSITION MONITORING", fg=self._theme("accent"), bg=self._theme("panel"),
                 font=("Consolas", 10, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(head, text="P&L | SL/TP | R | STATUS", fg=self._theme("text"), bg=self._theme("panel"),
                 font=("Consolas", 7), anchor="e").grid(row=0, column=1, sticky="e")
        position_columns = ("position", "prices", "stop", "target", "profit", "expected_profit", "r", "status")
        self._positions_tree = ttk.Treeview(positions_frame, columns=position_columns, show="headings", height=2, style="Hotspot.Treeview")
        headings = (
            ("position", "POSITION", 150), ("prices", "CURRENT | ENTRY", 150),
            ("stop", "SL REMAIN | TOTAL", 155), ("target", "TP REMAIN | TOTAL", 155),
            ("profit", "P/L", 85), ("expected_profit", "TP PROFIT", 100),
            ("r", "R", 55), ("status", "STATUS", 100),
        )
        for column, heading, width in headings:
            self._positions_tree.heading(column, text=heading)
            self._positions_tree.column(column, width=width, minwidth=55, anchor="center", stretch=True)
        self._positions_tree.tag_configure("profit", foreground="#22c55e")
        self._positions_tree.tag_configure("loss", foreground="#ef4444")
        self._positions_tree.tag_configure("neutral", foreground=self._theme("text"))
        self._positions_tree.bind("<<TreeviewSelect>>", self._on_position_selected)
        self._positions_tree.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 7))

        # ---------- Action bar ----------
        button_row = tk.Frame(frame, bg=self._theme("panel"))
        button_row.grid(row=5, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 5))
        self._trade_action_button = None
        self._manual_exit_trade_button = tk.Button(button_row, text="EXIT ACTIVE TRADE", command=self._manual_exit_trade,
            fg=self._theme("text"), bg="#7f1d1d", activebackground="#991b1b", activeforeground="#ffffff",
            bd=0, padx=13, pady=6, font=("Consolas", 8, "bold"))
        self._manual_exit_trade_button.pack(side="left", padx=(0, 6))
        self._close_all_positions_button = tk.Button(button_row, text="CLOSE ALL POSITIONS", command=self._close_all_positions,
            fg=self._theme("text"), bg="#7f1d1d", activebackground="#991b1b", activeforeground="#ffffff",
            bd=0, padx=13, pady=6, font=("Consolas", 8, "bold"))
        self._close_all_positions_button.pack(side="left", padx=(0, 6))
        self._back_to_home_button = tk.Button(button_row, text="BACK TO HOME", command=self._show_home_view,
            fg=self._theme("text"), bg=self._theme("button_bg"), activebackground=self._theme("button_active"),
            activeforeground=self._theme("accent"), bd=0, padx=13, pady=6, font=("Consolas", 8, "bold"))
        self._back_to_home_button.pack(side="left")

    def _update_strategy_profile_display(self):
        from core.price_units import spread_policy

        profile = self._trading_hub_controller.get_trading_profile()
        symbol = self._symbol_var.get() if hasattr(self, "_symbol_var") else config.DEFAULT_TRADING_SYMBOL
        policy = spread_policy(symbol, {}, self._trading_hub_controller.trading_mode)
        max_value = float(policy.get("max_value", 0.0) or 0.0)
        max_unit = str(policy.get("max_unit", "ticks"))
        self._strategy_mode_var.set(f"ACTIVE MODE: {profile['mode']}")
        self._strategy_profile_var.set(
            f"MAX SPREAD {max_value:.2f} {max_unit.upper()} | "
            f"{profile['trend_timeframe']} > {profile['setup_timeframe']} > {profile['entry_timeframe']} | "
            "PLAN GENERATION AUTO | NEWS-CONFLICT PLANS REQUIRE APPROVAL"
        )

    def _on_strategy_mode_change(self, mode: str):
        profile = self._trading_hub_controller.set_trading_mode(mode)
        self._save_gui_settings(trading_mode=profile["mode"])
        self._update_strategy_profile_display()
        self._append_trading_transcript(
            f"Trading mode changed to {profile['mode']}. Existing positions retain their opening mode."
        )

    def _build_wifi_view(self):
        wifi_style = ttk.Style(self)
        try:
            wifi_style.theme_use("clam")
        except tk.TclError:
            pass
        wifi_style.configure(
            "Hotspot.Treeview",
            background=self._theme("panel_alt"),
            fieldbackground=self._theme("panel_alt"),
            foreground=self._theme("text"),
            bordercolor=self._theme("border"),
            lightcolor=self._theme("border"),
            darkcolor=self._theme("border"),
            rowheight=28,
            font=("Consolas", 10),
        )
        wifi_style.configure(
            "Hotspot.Treeview.Heading",
            background=self._theme("button_bg"),
            foreground=self._theme("accent"),
            bordercolor=self._theme("border"),
            relief="flat",
            font=("Consolas", 10, "bold"),
        )
        wifi_style.map(
            "Hotspot.Treeview",
            background=[("selected", self._theme("button_active"))],
            foreground=[("selected", self._theme("accent"))],
        )
        self.wifi_view_frame = tk.Frame(self, bg=self._theme("panel"))
        self.wifi_view_frame.place_forget()
        tk.Label(
            self.wifi_view_frame, text="HOTSPOT HUB", fg=self._theme("accent"),
            bg=self._theme("panel"), font=("Consolas", 16, "bold"),
        ).pack(anchor="nw", padx=20, pady=(16, 8))

        self._wifi_status_var = tk.StringVar(value="Router status initializing...")
        tk.Label(
            self.wifi_view_frame, textvariable=self._wifi_status_var,
            fg=self._theme("text"), bg=self._theme("panel"),
            font=("Consolas", 11), justify="left",
        ).pack(anchor="nw", padx=20, pady=(0, 6))
        self._wifi_detail_var = tk.StringVar(value="The router is the enforcement layer. Angelique is the control panel.")
        tk.Label(
            self.wifi_view_frame, textvariable=self._wifi_detail_var,
            fg=self._theme("accent"), bg=self._theme("panel"),
            font=("Consolas", 10, "italic"), justify="left", wraplength=1100,
        ).pack(anchor="nw", padx=20, pady=(0, 14))

        content = tk.Frame(self.wifi_view_frame, bg=self._theme("panel"))
        content.pack(fill="both", expand=True, padx=20, pady=(0, 14))
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=0, minsize=430)
        device_frame = tk.Frame(content, bg=self._theme("panel"), bd=1, relief="solid")
        device_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        tk.Label(device_frame, text="CONNECTED DEVICES", fg=self._theme("accent"), bg=self._theme("panel"), font=("Consolas", 12, "bold")).pack(anchor="nw", padx=14, pady=(14, 8))
        columns = ("device", "mac", "ip", "status")
        self._wifi_device_tree = ttk.Treeview(device_frame, columns=columns, show="headings", height=8, style="Hotspot.Treeview")
        for column, heading, width in (("device", "DEVICE", 190), ("mac", "MAC", 150), ("ip", "IP", 130), ("status", "STATUS", 90)):
            self._wifi_device_tree.heading(column, text=heading)
            self._wifi_device_tree.column(column, width=width, anchor="w")
        self._wifi_device_tree.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        tk.Label(device_frame, text="DISCONNECTED DEVICES", fg=self._theme("accent"), bg=self._theme("panel"), font=("Consolas", 12, "bold")).pack(anchor="nw", padx=14, pady=(4, 8))
        self._wifi_disconnected_tree = ttk.Treeview(device_frame, columns=("device", "mac", "status"), show="headings", height=5, style="Hotspot.Treeview")
        for column, heading, width in (("device", "DEVICE", 220), ("mac", "MAC", 180), ("status", "STATUS", 130)):
            self._wifi_disconnected_tree.heading(column, text=heading)
            self._wifi_disconnected_tree.column(column, width=width, anchor="w")
        self._wifi_disconnected_tree.pack(fill="x", padx=14, pady=(0, 14))

        action_frame = tk.Frame(content, bg=self._theme("panel"), bd=1, relief="solid", width=410)
        action_frame.grid(row=0, column=1, sticky="nsew")
        action_frame.pack_propagate(False)
        tk.Label(action_frame, text="ACCESS CONTROL", fg=self._theme("accent"), bg=self._theme("panel"), font=("Consolas", 12, "bold")).pack(anchor="nw", padx=14, pady=(14, 12))
        tk.Label(action_frame, text="Selected device", fg=self._theme("text"), bg=self._theme("panel"), font=("Consolas", 10)).pack(anchor="w", padx=14)
        self._wifi_selected_var = tk.StringVar(value="Select a device")
        tk.Label(action_frame, textvariable=self._wifi_selected_var, fg=self._theme("accent"), bg=self._theme("panel_alt"), font=("Consolas", 10, "bold"), wraplength=370, justify="left").pack(fill="x", padx=14, pady=(4, 14))
        duration_label_frame = tk.Frame(action_frame, bg=self._theme("panel"))
        duration_label_frame.pack(fill="x", padx=14)
        tk.Label(duration_label_frame, text="Access duration", fg=self._theme("text"), bg=self._theme("panel"), font=("Consolas", 10)).pack(side="left")
        self._wifi_duration_unit_var = tk.StringVar(value="Minutes")
        duration_unit_menu = tk.OptionMenu(duration_label_frame, self._wifi_duration_unit_var, "Minutes", "Hours")
        duration_unit_menu.configure(bg=self._theme("button_bg"), fg=self._theme("accent"), activebackground=self._theme("button_active"), activeforeground=self._theme("accent"), bd=0, highlightthickness=0, font=("Consolas", 9))
        duration_unit_menu.pack(side="right")
        self._wifi_duration_var = tk.StringVar(value="60")
        self._wifi_duration_spinbox = tk.Spinbox(action_frame, from_=1, to=1440, textvariable=self._wifi_duration_var, bg=self._theme("button_bg"), fg=self._theme("text"), insertbackground=self._theme("text"), buttonbackground=self._theme("button_bg"), font=("Consolas", 10), width=8)
        self._wifi_duration_spinbox.pack(anchor="w", padx=14, pady=(4, 14))
        tk.Button(action_frame, text="ALLOW FOR DURATION", command=self._wifi_allow_for_duration, fg=self._theme("text"), bg=self._theme("button_bg"), activebackground=self._theme("button_active"), bd=0, padx=10, pady=9, font=("Consolas", 10, "bold")).pack(fill="x", padx=14, pady=4)
        tk.Button(action_frame, text="ALLOW FOREVER", command=self._wifi_allow_forever, fg=self._theme("text"), bg=self._theme("button_bg"), activebackground=self._theme("button_active"), bd=0, padx=10, pady=9, font=("Consolas", 10, "bold")).pack(fill="x", padx=14, pady=4)
        tk.Button(action_frame, text="CONNECT DEVICE", command=self._wifi_allow_forever, fg=self._theme("text"), bg=self._theme("button_bg"), activebackground=self._theme("button_active"), bd=0, padx=10, pady=9, font=("Consolas", 10, "bold")).pack(fill="x", padx=14, pady=4)
        tk.Button(action_frame, text="DISCONNECT NOW", command=self._wifi_disconnect_now, fg=self._theme("text"), bg="#7f1d1d", activebackground="#991b1b", bd=0, padx=10, pady=9, font=("Consolas", 10, "bold")).pack(fill="x", padx=14, pady=4)
        tk.Label(action_frame, text="Timed access is enforced by the router. Disconnected devices stay blocked until Connect Device is used.", fg=self._theme("text"), bg=self._theme("panel"), font=("Consolas", 9, "italic"), wraplength=370, justify="left").pack(anchor="w", padx=14, pady=(16, 8))

        self._wifi_device_tree.bind("<<TreeviewSelect>>", self._on_wifi_device_select)
        self._wifi_disconnected_tree.bind("<<TreeviewSelect>>", self._on_wifi_disconnected_select)
        buttons = tk.Frame(self.wifi_view_frame, bg=self._theme("panel"))
        buttons.pack(anchor="nw", padx=20, pady=(0, 8))
        tk.Button(buttons, text="REFRESH DEVICES", command=self._refresh_wifi_view, fg=self._theme("text"), bg=self._theme("button_bg"), activebackground=self._theme("button_active"), bd=0, padx=16, pady=10, font=("Consolas", 10, "bold")).pack(side="left", padx=(0, 12))
        tk.Button(buttons, text="BACK TO HOME", command=self._show_home_view, fg=self._theme("text"), bg=self._theme("button_bg"), activebackground=self._theme("button_active"), bd=0, padx=16, pady=10, font=("Consolas", 10, "bold")).pack(side="left")

    def _on_wifi_device_select(self, _event=None):
        selected = self._wifi_device_tree.selection()
        if selected:
            values = self._wifi_device_tree.item(selected[0], "values")
            self._wifi_selected_var.set(f"{values[0]}\n{values[1]}\n{values[2]}")
            self._wifi_selected_device = {"name": values[0], "mac": values[1], "ip": values[2]}

    def _on_wifi_disconnected_select(self, _event=None):
        selected = self._wifi_disconnected_tree.selection()
        if selected:
            values = self._wifi_disconnected_tree.item(selected[0], "values")
            self._wifi_selected_var.set(f"{values[0]}\n{values[1]}\nDISCONNECTED")
            self._wifi_selected_device = {"name": values[0], "mac": values[1], "ip": "--"}

    def _wifi_selected_mac(self):
        return getattr(self, "_wifi_selected_device", {}).get("mac", "")

    def _wifi_run_action(self, action, success_text):
        mac = self._wifi_selected_mac()
        if not mac:
            self._wifi_detail_var.set("Select a device first.")
            return
        self._wifi_detail_var.set("Sending router command...")
        threading.Thread(target=self._wifi_action_worker, args=(action, success_text), daemon=True).start()

    def _wifi_action_worker(self, action, success_text):
        try:
            action()
            self.after(0, lambda: (self._wifi_detail_var.set(success_text), self._refresh_wifi_view()))
        except Exception as exc:
            self.after(0, lambda: self._wifi_detail_var.set(f"Router command failed: {exc}"))

    def _wifi_allow_for_duration(self):
        try:
            duration = int(self._wifi_duration_var.get())
        except ValueError:
            self._wifi_detail_var.set("Duration must be a whole number.")
            return
        unit = self._wifi_duration_unit_var.get()
        minutes = duration * 60 if unit == "Hours" else duration
        if minutes > 1440:
            self._wifi_detail_var.set("Access duration cannot exceed 24 hours.")
            return
        self._wifi_run_action(lambda: allow_device_for_duration(self._wifi_selected_mac(), minutes), f"Device allowed for {duration} {unit.lower()}; the router will enforce the restriction afterward.")

    def _wifi_allow_forever(self):
        self._wifi_run_action(lambda: allow_device_forever(self._wifi_selected_mac()), "Device is permanently allowed; its blacklist entry and timed restrictions were removed.")

    def _wifi_disconnect_now(self):
        device = getattr(self, "_wifi_selected_device", {})
        self._wifi_run_action(lambda: disconnect_device(device.get("mac", ""), name=device.get("name", "")), "Device disconnected and blocked by the router until Allow Forever is used.")

    def _show_wifi_view(self):
        self._active_center_view = "wifi"
        self.center_title_label.configure(text="HOTSPOT HUB")
        self.center_status_label.configure(text="MODE: LOCAL WI-FI ACCESS CONTROL")
        if self.ring_canvas is not None:
            self.ring_canvas.pack_forget()
        self.center_status_label.pack_forget()
        self._hide_main_panels()
        self.wifi_view_frame.place(relx=0.02, rely=0.055, relwidth=0.96, relheight=0.88)
        self._refresh_wifi_view()

    def _refresh_wifi_view(self):
        if self._wifi_refresh_pending:
            return
        self._wifi_refresh_pending = True
        self._wifi_generation += 1
        generation = self._wifi_generation
        self._wifi_status_var.set("Router status: SCANNING...")
        threading.Thread(target=self._refresh_wifi_worker, args=(generation,), daemon=True).start()

    def _refresh_wifi_worker(self, generation):
        try:
            devices = list_connected_devices() if list_connected_devices else []
            disconnected = list_disconnected_devices() if list_disconnected_devices else []
            self.after(0, lambda: self._apply_wifi_devices(generation, devices, disconnected, None))
        except Exception as exc:
            self.after(0, lambda: self._apply_wifi_devices(generation, [], [], str(exc)))

    def _apply_wifi_devices(self, generation, devices, disconnected, error):
        if generation != self._wifi_generation:
            return
        self._wifi_refresh_pending = False
        for item in self._wifi_device_tree.get_children():
            self._wifi_device_tree.delete(item)
        for device in devices:
            self._wifi_device_tree.insert("", "end", values=(device["name"], device["mac"], device["ip"], device["status"]))
        for item in self._wifi_disconnected_tree.get_children():
            self._wifi_disconnected_tree.delete(item)
        for device in disconnected:
            self._wifi_disconnected_tree.insert("", "end", values=(device["name"], device["mac"], device["status"]))
        if error:
            self._wifi_status_var.set("Router status: OFFLINE")
            self._wifi_detail_var.set(f"Could not read the MF296A at the configured host: {error}")
            self._append_console("HOTSPOT", f"Router scan failed: {error}")
        else:
            self._wifi_status_var.set(f"Router status: ONLINE  |  connected devices: {len(devices)}")
            detail = "Read-only device discovery is active. Select a device to prepare an access-control action."
            if not devices:
                detail = "Router responded, but returned no wireless station records. Refresh after confirming the device is connected."
            self._wifi_detail_var.set(detail)

    def _hide_main_panels(self):
        for panel in [self.left_panel, self.center_panel, self.right_panel, self.bottom_panel]:
            if panel is not None:
                try:
                    panel.place_forget()
                except Exception:
                    pass

    def _show_main_panels(self):
        self.left_panel.place(relx=0.018, rely=0.055, relwidth=0.205, relheight=0.68)
        self.center_panel.place(relx=0.235, rely=0.055, relwidth=0.53, relheight=0.68)
        self.right_panel.place(relx=0.782, rely=0.055, relwidth=0.20, relheight=0.68)
        self.bottom_panel.place(relx=0.018, rely=0.755, relwidth=0.964, relheight=0.19)
    def _show_home_view(self):
        self._active_center_view = "home"
        position_job = getattr(self, "_position_refresh_job", None)
        if position_job is not None:
            try:
                self.after_cancel(position_job)
            except Exception:
                pass
            self._position_refresh_job = None
        signal_job = getattr(self, "_signal_refresh_job", None)
        if signal_job is not None:
            try:
                self.after_cancel(signal_job)
            except Exception:
                pass
            self._signal_refresh_job = None
        self.center_title_label.configure(text="ANGELIQUE CORE")
        self.center_status_label.configure(text="SYSTEM-WIDE SYNTHESIS CONTROL")
        if self.trading_view_frame is not None:
            self.trading_view_frame.place_forget()
        if self.signal_view_frame is not None:
            self.signal_view_frame.place_forget()
        if self.wifi_view_frame is not None:
            self.wifi_view_frame.place_forget()
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
            self.trading_view_frame.place(relx=0.01, rely=0.035, relwidth=0.98, relheight=0.94)
        if self.signal_view_frame is not None:
            self.signal_view_frame.place_forget()
        self._refresh_trading_view()

    def _build_signal_view(self):
        """Build the populated Signals / Notifications workspace.

        The page is presentation-only: every value is derived from the same
        canonical workflow report used by execution. It separates technical
        signal evidence (SMC / ICT / structure) from notices and the economic
        calendar so the operator can read the complete decision chain without
        hunting through the main dashboard.
        """
        frame = tk.Frame(self, bg=self._theme("panel"), bd=1, relief="solid")
        frame.place_forget()
        self.signal_view_frame = frame
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=5)
        frame.grid_rowconfigure(2, weight=4)
        frame.grid_rowconfigure(3, weight=0)

        header = tk.Frame(frame, bg=self._theme("title_bg"))
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 6))
        header.grid_columnconfigure(2, weight=1)
        tk.Label(header, text="SIGNALS / NOTIFICATIONS", fg=self._theme("accent"), bg=self._theme("title_bg"),
                 font=("Consolas", 12, "bold")).grid(row=0, column=0, padx=(8, 12), pady=6, sticky="w")
        self._signal_symbol_var = self._symbol_var if hasattr(self, "_symbol_var") else tk.StringVar(value=config.DEFAULT_TRADING_SYMBOL)
        signal_symbols = self._get_market_symbols()
        self._signal_symbol_var.set(self._signal_symbol_var.get() or (signal_symbols[0] if signal_symbols else config.DEFAULT_TRADING_SYMBOL))
        menu = tk.OptionMenu(header, self._signal_symbol_var, *(signal_symbols or [config.DEFAULT_TRADING_SYMBOL]), command=lambda _=None: self._on_signal_symbol_changed())
        menu.configure(bg=self._theme("button_bg"), fg=self._theme("text"), activebackground=self._theme("button_active"),
                       activeforeground=self._theme("accent"), bd=0, highlightthickness=0, font=("Consolas", 8))
        menu.grid(row=0, column=1, padx=2)
        self._signal_symbol_menu = menu
        self._signal_route_var = tk.StringVar(value="ROUTE: BROKER PENDING")
        tk.Label(header, textvariable=self._signal_route_var, fg=self._theme("text"), bg=self._theme("title_bg"),
                 font=("Consolas", 8, "bold"), anchor="e").grid(row=0, column=2, sticky="e", padx=8)
        self._signal_status_var = tk.StringVar(value="Waiting for signal analysis...")
        tk.Label(header, textvariable=self._signal_status_var, fg=self._theme("accent"), bg=self._theme("title_bg"),
                 font=("Consolas", 8), anchor="e").grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 5))

        signal_section = tk.LabelFrame(frame, text="SIGNAL", fg=self._theme("accent"), bg=self._theme("panel"),
                                       bd=1, relief="solid", font=("Consolas", 9, "bold"))
        signal_section.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 5))
        for c in range(3):
            signal_section.grid_columnconfigure(c, weight=1, uniform="signal_cols")
        signal_section.grid_rowconfigure(1, weight=1)

        self._signal_card_vars = {key: tk.StringVar(value="--") for key in ("state", "score", "risk", "rr", "news", "broker")}
        cards = tk.Frame(signal_section, bg=self._theme("panel"))
        cards.grid(row=0, column=0, columnspan=3, sticky="ew", padx=7, pady=6)
        for c in range(6):
            cards.grid_columnconfigure(c, weight=1, uniform="sigcard")
        for col, title, key in ((0,"STATE","state"),(1,"CONFLUENCE","score"),(2,"RISK","risk"),(3,"RR","rr"),(4,"NEWS","news"),(5,"ROUTE","broker")):
            cell=tk.Frame(cards,bg=self._theme("panel_alt"),bd=1,relief="solid")
            cell.grid(row=0,column=col,sticky="ew",padx=2)
            tk.Label(cell,text=title,fg=self._theme("text"),bg=self._theme("panel_alt"),font=("Consolas",7,"bold")).pack(pady=(4,0))
            tk.Label(cell,textvariable=self._signal_card_vars[key],fg=self._theme("accent"),bg=self._theme("panel_alt"),font=("Consolas",8,"bold"),wraplength=150).pack(fill="x",padx=3,pady=(1,4))

        section_names = ((0, "SMC", "_signal_smc_text"), (1, "ICT", "_signal_ict_text"), (2, "MARKET STRUCTURE", "_signal_structure_text"))
        for col, title, attr in section_names:
            box=tk.Frame(signal_section,bg=self._theme("panel_alt"),bd=1,relief="solid")
            box.grid(row=1,column=col,sticky="nsew",padx=3,pady=(0,7))
            tk.Label(box,text=title,fg=self._theme("accent"),bg=self._theme("panel_alt"),font=("Consolas",8,"bold")).pack(anchor="w",padx=6,pady=(6,3))
            widget=scrolledtext.ScrolledText(box, bg="#07131f", fg=self._theme("text"), insertbackground=self._theme("text"),
                                                bd=0, relief="flat", font=("Consolas",8), wrap="word", height=12)
            widget.pack(fill="both",expand=True,padx=4,pady=(0,4)); widget.configure(state="disabled")
            setattr(self, attr, widget)

        # Execution-gate detail is kept visible below the three strategy panels.
        gate_frame = tk.Frame(signal_section, bg=self._theme("panel"))
        gate_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=3, pady=(0, 6))
        gate_frame.grid_columnconfigure(0, weight=48); gate_frame.grid_columnconfigure(1, weight=52); gate_frame.grid_rowconfigure(1, weight=1)
        tk.Label(gate_frame, text="EXECUTION GATES", fg=self._theme("text"), bg=self._theme("panel"), font=("Consolas",7,"bold")).grid(row=0,column=0,sticky="w",padx=4,pady=3)
        tk.Label(gate_frame, text="PLAN", fg=self._theme("text"), bg=self._theme("panel"), font=("Consolas",7,"bold")).grid(row=0,column=1,sticky="w",padx=4,pady=3)
        self._signal_evidence_tree = ttk.Treeview(gate_frame, columns=("stage","status","detail"), show="headings", height=6, style="Hotspot.Treeview")
        self._signal_evidence_tree.heading("stage", text="STAGE"); self._signal_evidence_tree.heading("status", text="STATUS"); self._signal_evidence_tree.heading("detail", text="DETAIL")
        self._signal_evidence_tree.column("stage", width=105); self._signal_evidence_tree.column("status", width=70); self._signal_evidence_tree.column("detail", width=400)
        self._signal_evidence_tree.grid(row=1,column=0,sticky="nsew",padx=(4,2),pady=(0,4))
        for tag, fg in (("ok", "#22c55e"), ("bad", "#ef4444"), ("wait", self._theme("text"))):
            self._signal_evidence_tree.tag_configure(tag, foreground=fg)
        self._signal_plan_text = scrolledtext.ScrolledText(gate_frame, bg="#07131f", fg=self._theme("text"), insertbackground=self._theme("text"), bd=0, font=("Consolas",8), wrap="word")
        self._signal_plan_text.grid(row=1,column=1,sticky="nsew",padx=(8,4),pady=(0,4))
        self._signal_plan_text.configure(state="disabled")
        self._signal_report = self._signal_plan_text

        notifications = tk.LabelFrame(frame, text="NOTIFICATIONS", fg=self._theme("accent"), bg=self._theme("panel"), bd=1, relief="solid", font=("Consolas",9,"bold"))
        notifications.grid(row=2,column=0,sticky="nsew", padx=10,pady=(0,8))
        notifications.grid_columnconfigure(0,weight=1); notifications.grid_columnconfigure(1,weight=1); notifications.grid_rowconfigure(1,weight=1)
        tk.Label(notifications,text="SYSTEM / EXECUTION EVENTS",fg=self._theme("text"),bg=self._theme("panel"),font=("Consolas",8,"bold")).grid(row=0,column=0,sticky="w",padx=8,pady=6)
        tk.Label(notifications,text="NEWS & CALENDAR",fg=self._theme("text"),bg=self._theme("panel"),font=("Consolas",8,"bold")).grid(row=0,column=1,sticky="w",padx=8,pady=6)
        self._signal_notification_var = tk.StringVar(value="No notifications yet.")
        notif_box = scrolledtext.ScrolledText(notifications, bg="#07131f", fg=self._theme("text"), insertbackground=self._theme("text"), bd=0, font=("Consolas",8), wrap="word")
        notif_box.grid(row=1,column=0,sticky="nsew",padx=(5,3),pady=(0,5)); notif_box.configure(state="disabled")
        self._signal_notification_text = notif_box
        news_frame = tk.Frame(notifications,bg=self._theme("panel_alt"),bd=1,relief="solid")
        news_frame.grid(row=1,column=1,sticky="nsew",padx=(3,5),pady=(0,5)); news_frame.grid_rowconfigure(1,weight=1); news_frame.grid_columnconfigure(0,weight=1)
        self._signal_news_tree = ttk.Treeview(news_frame, columns=("time","impact","event"), show="headings", style="Hotspot.Treeview", height=6)
        for c,h,w in (("time","TIME",110),("impact","IMPACT",70),("event","EVENT",360)):
            self._signal_news_tree.heading(c,text=h); self._signal_news_tree.column(c,width=w,stretch=True)
        self._signal_news_tree.tag_configure("high", foreground="#ef4444"); self._signal_news_tree.tag_configure("medium", foreground="#f59e0b"); self._signal_news_tree.tag_configure("normal", foreground=self._theme("text"))
        self._signal_news_tree.grid(row=0,column=0,sticky="nsew",padx=3,pady=3)
        tk.Label(news_frame,text="Calendar events are informational; a detected high-impact event switches execution to manual approval.",fg=self._theme("text"),bg=self._theme("panel_alt"),font=("Consolas",7),wraplength=500,justify="left").grid(row=1,column=0,sticky="w",padx=6,pady=4)

        signal_nav = tk.Frame(frame, bg=self._theme("panel"))
        signal_nav.grid(row=3, column=0, sticky="ew", padx=10, pady=(0, 8))
        tk.Button(signal_nav, text="BACK TO TRADING HUB", command=self._show_trading_view,
                  fg=self._theme("text"), bg=self._theme("button_bg"), activebackground=self._theme("button_active"),
                  activeforeground=self._theme("accent"), bd=0, padx=13, pady=6,
                  font=("Consolas", 8, "bold")).pack(side="left")

    def _set_readonly_text(self, widget, text):
        if widget is None:
            return
        try:
            widget.configure(state="normal"); widget.delete("1.0","end"); widget.insert("1.0", str(text)); widget.configure(state="disabled")
        except Exception:
            pass

    def _format_signal_panels(self, report):
        analysis = report.get("structure", {}) or {}
        smc = report.get("smc", {}) or {}
        profile = self._trading_hub_controller.get_trading_profile()
        setup_tf = profile.get("setup_timeframe", "M15")
        entry_tf = profile.get("entry_timeframe", "M5")
        setup = smc.get(setup_tf, {}) if isinstance(smc.get(setup_tf), dict) else {}
        entry = smc.get(entry_tf, {}) if isinstance(smc.get(entry_tf), dict) else {}
        assessment = analysis.get("setup_assessment", {}) or {}
        news = analysis.get("news_context", {}) or {}
        htf = analysis.get("htf_alignment", {}) or {}
        session = analysis.get("session_context", {}) or {}
        ict_setup = setup.get("ict", {}) or {}
        ote = ict_setup.get("ote", {}) or {}
        amd = setup.get("amd", {}) or {}
        kz = ict_setup.get("kill_zone", {}) or {}

        smc_lines = [
            f"Direction: {report.get('direction') or 'WAIT'}",
            f"Setup model: {assessment.get('model') or analysis.get('strategy_name') or 'NONE'}",
            f"Setup TF: {setup_tf} | Entry TF: {entry_tf}",
            f"Liquidity sweep: {setup.get('liquidity_sweep') or 'none'}",
            f"Structure shift: {setup.get('structure_shift') or 'none'}",
            f"Displacement: {'YES' if setup.get('displacement') else 'NO'}",
            f"Tradeable FVGs: {sum(1 for x in setup.get('fair_value_gaps',[]) if isinstance(x,dict) and x.get('classification') in {'QUALIFIED_FVG','TRADEABLE_FVG'})}",
            f"Order block: {'TRADEABLE' if isinstance(setup.get('order_block'),dict) and setup.get('order_block',{}).get('classification')=='TRADEABLE_OB' else 'none/candidate'}",
            f"Location: {setup.get('location') or 'unknown'}",
            f"Missing stages: {', '.join(assessment.get('missing', [])) or 'none'}",
            f"Signal rationale: {assessment.get('reason') or report.get('reason') or 'Waiting for a complete model.'}",
        ]
        ict_lines = [
            f"HTF daily bias: {str(htf.get('daily_bias') or analysis.get('trends',{}).get('D1') or 'unknown').upper()}",
            f"HTF alignment: {'ALIGNED' if not htf.get('countertrend') else 'COUNTERTREND'}",
            f"OTE: {'IN' if ote.get('in_bullish_ote') or ote.get('in_bearish_ote') else 'OUT'}",
            f"OTE range: {ote.get('low','--')} → {ote.get('high','--')}",
            f"AMD phase: {str(amd.get('phase') or amd.get('status') or '--').upper()}",
            f"Kill zone: {str(kz.get('status') or session.get('session') or '--').upper()}",
            f"Session: {str(session.get('session') or '--').upper()}",
            f"Target liquidity: {(setup.get('target_liquidity') or {}).get('price','--') if isinstance(setup.get('target_liquidity'),dict) else '--'}",
            f"News bias: {news.get('bias','neutral').upper()}",
            f"High-impact imminent: {'YES' if news.get('high_impact_imminent') else 'NO'}",
        ]
        structure_lines = ["TIMEFRAME  TREND  STRUCTURE  SHIFT  LAST CLOSE"]
        trends = report.get("trends", {}) or {}
        for tf in profile.get("analysis_required_timeframes", []):
            row = smc.get(tf, {}) if isinstance(smc.get(tf), dict) else {}
            structure = row.get("structure", {}) or {}
            candles = self._last_full_candles if tf == self._get_selected_symbol_and_timeframe()[1].upper() else []
            last_close = "--"
            if isinstance(row.get("last"),dict): last_close = row.get("last",{}).get("close","--")
            structure_lines.append(f"{tf:<5}     {str(trends.get(tf,'mixed')).upper():<7} {str(structure.get('bias','unknown')).upper():<9} {str(row.get('structure_shift') or '--'):<24} {last_close}")
        return "\n".join(smc_lines), "\n".join(ict_lines), "\n".join(structure_lines)

    def _show_signal_view(self):
        self._active_center_view = "signals"
        self.center_title_label.configure(text="SIGNALS / NOTIFICATIONS")
        self.center_status_label.configure(text="ADVISORY MULTI-TIMEFRAME MARKET ANALYSIS")
        if self.ring_canvas is not None:
            self.ring_canvas.pack_forget()
        if self.center_status_label is not None:
            self.center_status_label.pack_forget()
        self._hide_main_panels()
        if self.trading_view_frame is not None:
            self.trading_view_frame.place_forget()
        self.signal_view_frame.place(relx=0.02, rely=0.055, relwidth=0.96, relheight=0.88)
        self._refresh_signal_view()

    def _refresh_signal_view(self):
        if self._active_center_view != "signals" or self._signal_refresh_running:
            return
        if self._signal_refresh_job is not None:
            try:
                self.after_cancel(self._signal_refresh_job)
            except Exception:
                pass
            self._signal_refresh_job = None
        symbol = self._signal_symbol_var.get() or config.DEFAULT_TRADING_SYMBOL
        account_mode = self._get_selected_account_mode()
        timeframes = list(config.TRADING_TIMEFRAMES)
        self._signal_refresh_running = True
        self._signal_generation += 1
        generation = self._signal_generation
        self._signal_request = {"symbol": symbol, "account_mode": account_mode, "generation": generation}
        # News/calendar is an independent operator feed. Fetch it in parallel
        # with strategy analysis so a blocked/slow trade workflow cannot leave
        # the calendar pane blank.
        self._signal_news_generation = generation
        self._set_signal_news_loading()
        threading.Thread(target=self._signal_news_calendar_worker, args=(symbol, generation), daemon=True).start()
        from skills.trading_skill.profiles import get_trading_profile
        profile = get_trading_profile(self._trading_hub_controller.trading_mode)
        self._signal_status_var.set(f"{symbol} | [{account_mode.upper()}] | fetching fresh market data... Refresh {profile.monitor_interval_seconds}s.")
        threading.Thread(
            target=self._signal_analysis_worker,
            args=(symbol, account_mode, timeframes, self._trading_hub_controller.trading_mode, generation),
            daemon=True,
        ).start()
        # Never leave the UI in a permanent loading state if a bridge/MT5 call hangs.
        self._signal_timeout_generation = generation
        self.after(15000, lambda g=generation: self._signal_analysis_timeout(g))

    def _set_signal_news_loading(self):
        tree = getattr(self, "_signal_news_tree", None)
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)
        tree.insert("", "end", values=("--", "INFO", "LOADING NEWS & CALENDAR..."), tags=("normal",))

    def _signal_news_calendar_worker(self, symbol, generation):
        try:
            from skills.trading_skill.news import get_forex_news, get_market_calendar
            headlines = get_forex_news(symbol) or []
            calendar = get_market_calendar(symbol=symbol) or []
            payload = {
                "headlines": [x for x in headlines if x.get("freshness") != "unavailable"],
                "calendar": [x for x in calendar if x.get("freshness") != "unavailable"],
                "headline_feed_available": bool(headlines and not all(x.get("freshness") == "unavailable" for x in headlines)),
                "calendar_feed_available": bool(calendar and not all(x.get("freshness") == "unavailable" for x in calendar)),
            }
        except Exception as exc:
            payload = {"headlines": [], "calendar": [], "headline_feed_available": False, "calendar_feed_available": False, "error": str(exc)}
        if not getattr(self, "_shutting_down", False):
            self.after(0, lambda p=payload, g=generation: self._apply_signal_news_calendar(p, g))

    def _apply_signal_news_calendar(self, payload, generation):
        if generation != getattr(self, "_signal_generation", -1):
            return
        tree = getattr(self, "_signal_news_tree", None)
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)
        headlines = list(payload.get("headlines", []) or [])
        calendar = list(payload.get("calendar", []) or [])
        for item in headlines[:8]:
            title = item.get("title") or item.get("event") or "News update"
            tree.insert("", "end", values=(item.get("retrieved_at") or item.get("time") or "--", "NEWS", title), tags=("normal",))
        for item in calendar[:12]:
            title = item.get("event") or item.get("title") or "Calendar event"
            impact = str(item.get("impact") or "unknown").upper()
            tag = "high" if impact.lower() in {"high", "red", "3"} else "medium" if impact.lower() in {"medium", "yellow", "2"} else "normal"
            tree.insert("", "end", values=(item.get("scheduled_at") or item.get("time") or "--", impact, title), tags=(tag,))
        if not headlines:
            tree.insert("", "end", values=("--", "INFO", "NEWS FEED UNAVAILABLE" if not payload.get("headline_feed_available") else "NO RELEVANT HEADLINES"), tags=("normal",))
        if not calendar:
            tree.insert("", "end", values=("--", "INFO", "CALENDAR FEED UNAVAILABLE" if not payload.get("calendar_feed_available") else "NO RELEVANT CALENDAR EVENTS"), tags=("normal",))
        if payload.get("error"):
            tree.insert("", "end", values=("--", "INFO", payload["error"]), tags=("normal",))

    def _signal_analysis_timeout(self, generation):
        if generation != self._signal_generation or not self._signal_refresh_running:
            return
        request = getattr(self, "_signal_request", {})
        self._signal_refresh_running = False
        self._signal_status_var.set(
            f"{request.get('symbol', self._signal_symbol_var.get())} | "
            f"[{str(request.get('account_mode', self._get_selected_account_mode())).upper()}] | "
            "SIGNAL ANALYSIS TIMEOUT — bridge/MT5 did not return fresh data within 15s."
        )
        self._schedule_signal_refresh()

    def _on_signal_symbol_changed(self):
        self._signal_generation += 1
        if not self._signal_refresh_running:
            self._refresh_signal_view()

    def _signal_analysis_worker(self, symbol, account_mode, timeframes, trading_mode, generation):
        try:
            # A mode switch invalidates this worker. Never let an old DEMO/REAL
            # result paint over the newly selected account.
            if getattr(self, "_shutting_down", False) or generation != getattr(self, "_signal_generation", -1):
                return
            from gui.signal_analysis import analyze_symbol
            report = analyze_symbol(symbol, account_mode, timeframes, trading_mode)
            if not getattr(self, "_shutting_down", False):
                self.after(0, lambda r=report: self._apply_signal_report(r, generation))
        except Exception as exc:
            if not getattr(self, "_shutting_down", False):
                self.after(0, lambda e=str(exc): self._apply_signal_error(e, generation))

    def _calculate_signal_position_size(self):
        try:
            from gui.signal_analysis import calculate_position_size
            if not self._calculator_specs or any(self._calculator_specs.get(key) is None for key in ("tick_size", "tick_value", "pip_size", "volume_min", "volume_step")):
                raise ValueError("Market data is not loaded yet.")
            values = {key: float(self._calculator_vars[key].get()) for key in ("balance", "risk", "stop")}
            values.update({key: float(self._calculator_specs[key]) for key in ("tick_size", "tick_value", "pip_size", "volume_min", "volume_step")})
            values["volume_max"] = float(self._calculator_specs.get("volume_max") or 0)
            result = calculate_position_size(
                values["balance"], values["risk"], values["stop"],
                values["tick_size"], values["tick_value"], values["pip_size"],
                values["volume_min"], values["volume_step"], values["volume_max"],
            )
            if result["volume"] <= 0:
                message = f"Raw size {result['raw_volume']:.4f} is below MT5 minimum {result['volume_min']:.4f}; no accepted lot size."
            else:
                message = f"Risk budget ${result['risk_amount']:.2f} | Lot size {result['volume']:.4f} | Actual risk ${result['actual_risk']:.2f}"
            self._calculator_result_var.set(message)
        except (TypeError, ValueError) as exc:
            self._calculator_result_var.set(f"Calculator: {exc}")

    def _apply_signal_error(self, error_text, generation):
        if generation != self._signal_generation:
            return
        self._signal_refresh_running = False
        account_mode = self._get_selected_account_mode()
        symbol = self._signal_symbol_var.get() or config.DEFAULT_TRADING_SYMBOL
        self._signal_status_var.set(f"{symbol} | [{account_mode.upper()}] | SIGNAL ERROR: {error_text}")
        try:
            for item in self._signal_evidence_tree.get_children():
                self._signal_evidence_tree.delete(item)
            self._signal_evidence_tree.insert("", "end", values=("Account mode", "CHECK", f"Requested {account_mode.upper()} — live analysis unavailable"), tags=("wait",))
            self._signal_evidence_tree.insert("", "end", values=("Market data", "BLOCK", str(error_text)), tags=("bad",))
            self._signal_evidence_tree.insert("", "end", values=("Decision", "BLOCK", "No trade decision until fresh data is available"), tags=("bad",))
            self._signal_plan_text.configure(state="normal")
            self._signal_plan_text.delete("1.0", "end")
            self._signal_plan_text.insert("1.0", f"{symbol}   DATA BLOCKED\n\nAccount mode: {account_mode.upper()}\n\nReason:\n{error_text}\n\nExecution: NO TRADE")
            self._signal_plan_text.configure(state="disabled")
        except Exception:
            pass
        self._schedule_signal_refresh()

    def _signal_spread_gate_status(self, report, spread, unit):
        if spread in (None, "--", "-"):
            return "CHECK"
        try:
            symbol = report.get("symbol") or self._signal_symbol_var.get()
            max_value = report.get("maximum_spread_value")
            max_unit = report.get("maximum_spread_unit")
            if max_value is None or not max_unit:
                from core.price_units import spread_policy
                profile = self._trading_hub_controller.get_trading_profile()
                max_policy = spread_policy(symbol, report.get("symbol_specs") or {}, profile.get("mode", self._trading_hub_controller.trading_mode))
                max_value, max_unit = max_policy.get("max_value"), max_policy.get("max_unit")
            if unit != max_unit or max_value is None:
                return "CHECK"
            return "PASS" if float(spread) <= float(max_value) else "BLOCK"
        except Exception:
            return "CHECK"

    def _signal_spread_gate_detail(self, report, spread, unit):
        if spread in (None, "--", "-"):
            return "Awaiting live spread"
        try:
            max_value = report.get("maximum_spread_value")
            max_unit = report.get("maximum_spread_unit")
            if max_value is None or not max_unit:
                from core.price_units import spread_policy
                profile = self._trading_hub_controller.get_trading_profile()
                symbol = report.get("symbol") or self._signal_symbol_var.get()
                max_policy = spread_policy(symbol, report.get("symbol_specs") or {}, profile.get("mode", self._trading_hub_controller.trading_mode))
                max_value, max_unit = max_policy.get("max_value"), max_policy.get("max_unit")
            if max_unit:
                return f"{_fmt_signal_spread(spread)} {unit} / max {float(max_value):.2f} {max_unit}"
            return f"{_fmt_signal_spread(spread)} {unit}"
        except Exception:
            return f"{_fmt_signal_spread(spread)} {unit}"

    def _apply_signal_report(self, report, generation):
        if generation != self._signal_generation:
            self._signal_refresh_running = False
            self._refresh_signal_view()
            return
        self._signal_refresh_running = False
        if not isinstance(report, dict) or not report:
            report = {
                "signal": "WAIT",
                "decision_state": "BLOCKED_BY_DATA",
                "reason": "No signal report received.",
                "structure": {},
                "confluence": {},
                "latest": {},
                "advisory_plan": {},
                "data_blockers": ["Market data unavailable"],
            }
        from gui.signal_analysis import signal_ui_contract

        display = signal_ui_contract(report)
        # Never display a result from a different account environment than the
        # one currently selected in the GUI.
        selected_mode = self._get_selected_account_mode()
        report_mode = str(report.get("account_mode") or "").lower()
        actual_mode = str(report.get("actual_account_mode") or "").lower()
        if report_mode != selected_mode or not bool(report.get("mode_match")) or actual_mode != selected_mode:
            self._signal_status_var.set(
                f"{self._signal_symbol_var.get() or config.DEFAULT_TRADING_SYMBOL} | "
                f"[{selected_mode.upper()}] | ACCOUNT MODE NOT VERIFIED — waiting for matching MT5 account"
            )
            self._signal_refresh_running = False
            self._schedule_signal_refresh()
            return
        signal = report.get("signal", "WAIT")
        plan = report.get("advisory_plan", {}) or {}
        score = display.get("score")
        latest = report.get("latest", {}) or {}
        spread = display.get("spread_pips")
        spread_unit = display.get("spread_unit") or "pips"
        if spread is None:
            if latest.get("spread_ticks") is not None and spread_unit == "ticks":
                spread = latest.get("spread_ticks")
            elif latest.get("spread_unit") == "price":
                spread = latest.get("spread_price", latest.get("spread", "--"))
                spread_unit = "price"
            else:
                spread = latest.get("spread_points", latest.get("spread", "--"))
                spread_unit = latest.get("spread_unit") or "points"
        symbol = display.get("symbol") or self._signal_symbol_var.get()
        account_backend = report.get("account", {}) or {}
        broker = str(account_backend.get("broker") or "VALETAX").strip()
        route = f"{broker.upper()} (All Pairs)"
        self._signal_route_var.set(f"ROUTE: {route}")
        specs = report.get("symbol_specs", {}) or {}
        try:
            signal_digits = int(specs.get("digits", 5) or 5)
        except (TypeError, ValueError):
            signal_digits = 5

        state = display.get("state", signal)
        news_context = report.get("news_context") or (report.get("structure", {}) or {}).get("news_context", {}) or {}
        if plan.get("requires_manual_approval") or news_context.get("high_impact"):
            news_label = "MANUAL • HIGH IMPACT"
        elif news_context.get("status") == "unavailable":
            news_label = "INFO • UNAVAILABLE"
        else:
            news_label = "AUTO • NO HIGH IMPACT"
        try:
            score_text = f"{float(score):.0f}/100" if score is not None else "--"
        except (TypeError, ValueError):
            score_text = "--"
        risk_amount = plan.get("risk_amount")
        risk_pct = plan.get("risk_percent")
        risk_text = f"{float(risk_pct):.2f}%" if risk_pct is not None else f"{float(config.TRADING_RISK_PER_TRADE_PERCENT):.2f}%"
        rr = display.get("reward_to_risk")
        rr_text = f"1:{float(rr):.2f}" if rr is not None else "--"
        broker_text = route.replace(" ONLY", "")
        self._signal_card_vars["state"].set(str(state).replace("_", " "))
        self._signal_card_vars["score"].set(score_text)
        self._signal_card_vars["risk"].set(risk_text + (f" / ${float(risk_amount):.2f}" if risk_amount is not None else ""))
        self._signal_card_vars["rr"].set(rr_text)
        self._signal_card_vars["news"].set(news_label)
        self._signal_card_vars["broker"].set(broker_text)

        # Strategy-specific live intelligence panels.
        try:
            smc_text, ict_text, structure_text = self._format_signal_panels(report)
            self._set_readonly_text(self._signal_smc_text, smc_text)
            self._set_readonly_text(self._signal_ict_text, ict_text)
            self._set_readonly_text(self._signal_structure_text, structure_text)
        except Exception as exc:
            self._set_readonly_text(self._signal_smc_text, f"Signal panel unavailable: {exc}")

        analysis_news = report.get("news_context") or (report.get("structure", {}) or {}).get("news_context", {}) or {}
        news_events = list(analysis_news.get("headlines", []) or [])
        # Display the complete relevant calendar independently of execution
        # gating. High-impact events are marked by the backend, but lower-
        # impact events must remain visible to the operator too.
        calendar_events = list(analysis_news.get("calendar_events", []) or analysis_news.get("calendar", []) or [])
        news_tree = self._signal_news_tree
        for item in news_tree.get_children(): news_tree.delete(item)
        for event in news_events[:8]:
            title = event.get("title") or event.get("event") or "News update"
            impact = event.get("impact") or ("high" if event in calendar_events else "info")
            news_tree.insert("", "end", values=(event.get("retrieved_at") or event.get("time") or "--", str(impact).upper(), title), tags=("high" if str(impact).lower() in {"high","red","3"} else "normal",))
        for event in calendar_events[:12]:
            title = event.get("event") or event.get("title") or "Calendar event"
            impact = event.get("impact") or "HIGH"
            news_tree.insert("", "end", values=(event.get("scheduled_at") or event.get("time") or "--", str(impact).upper(), title), tags=("high" if str(impact).lower() in {"high","red","3"} else "medium" if str(impact).lower() in {"medium","yellow","2"} else "normal",))
        if not news_events and not calendar_events:
            status = "NEWS UNAVAILABLE" if news_context.get("data_quality", {}).get("headlines") == "unavailable" else "NO NEWS ITEMS"
            news_tree.insert("", "end", values=("--", "INFO", status), tags=("normal",))
            news_tree.insert("", "end", values=("--", "INFO", "CALENDAR DATA UNAVAILABLE" if news_context.get("data_quality", {}).get("calendar") == "unavailable" else "NO CALENDAR EVENTS"), tags=("normal",))
        elif not calendar_events:
            news_tree.insert("", "end", values=("--", "INFO", "NO CALENDAR EVENTS"), tags=("normal",))
        elif not news_events:
            news_tree.insert("", "end", values=("--", "INFO", "NO NEWS HEADLINES"), tags=("normal",))

        # Evidence table: only the important decision gates. Full diagnostics
        # remain available through Angelique's console and journal.
        tree = self._signal_evidence_tree
        for item in tree.get_children():
            tree.delete(item)
        analysis = report.get("structure", {}) or {}
        smc = report.get("smc", {}) or {}
        required = report.get("required_timeframes", []) or []
        blockers = report.get("data_blockers") or []
        rows = [
            ("Market data", "BLOCK" if blockers else "PASS",
             ", ".join(blockers) if blockers else "Required timeframes fresh"),
            ("HTF bias", "INFO", str(report.get("htf_bias", "UNAVAILABLE"))),
            ("Execution bias", "INFO", str(report.get("execution_bias", "UNAVAILABLE"))),
            ("Setup model", "PASS" if plan.get("direction") in {"BUY", "SELL"} else "WAIT",
             str(display.get("model") or "No complete model")),
            ("Structure", "PASS" if analysis.get("valid") else "WAIT", str(analysis.get("reason") or report.get("reason") or "No confirmed structure")),
            ("Confluence", "PASS" if score is not None and score >= (display.get("minimum_score") or 70) else "WAIT", f"Score {score_text}"),
            ("Spread", self._signal_spread_gate_status(report, spread, spread_unit), self._signal_spread_gate_detail(report, spread, spread_unit)),
            ("Entry", "PASS" if plan.get("direction") in {"BUY", "SELL"} else "WAIT", "Executable direction confirmed" if plan.get("direction") in {"BUY", "SELL"} else "Waiting for complete entry"),
            ("News", "REVIEW" if plan.get("requires_manual_approval") else "PASS", plan.get("manual_approval_reason") or "No high-impact/news conflict flagged"),
        ]
        for stage, status, detail in rows:
            tag = "ok" if status == "PASS" else "bad" if status == "BLOCK" else "wait"
            tree.insert("", "end", values=(stage, status, detail), tags=(tag,))

        direction = plan.get("direction")
        executable = bool(report.get("trade_allowed")) and str(state) in {"BUY_PLAN_READY", "SELL_PLAN_READY"} and direction in {"BUY", "SELL"}
        plan_lines = [
            f"{symbol}   {direction if executable else 'WAIT'}",
            f"Model: {display.get('model') or 'Not confirmed'}",
            f"Score: {score_text}   RR: {rr_text}",
            f"Entry: {_fmt_signal_value(plan.get('entry'), signal_digits)}",
            f"Stop:  {_fmt_signal_value(plan.get('stop_loss'), signal_digits)}",
            f"Target:{_fmt_signal_value(plan.get('take_profit'), signal_digits)}",
            f"Spread: {_fmt_signal_spread(spread)} {spread_unit}" if spread not in (None, "--", "-") else "Spread: awaiting live feed",
            f"Risk: {risk_text}" + (f"   Budget: ${float(risk_amount):.2f}" if risk_amount is not None else ""),
            f"Stop basis: {plan.get('stop_basis') or 'Not available'}",
            f"Target basis: {plan.get('target_basis') or 'Not available'}",
            "",
            "EXECUTION:",
            str(display.get("execution_state") or ("AUTO_ENABLED" if executable else "NO_EXECUTION")).replace("_", " "),
            plan.get("manual_approval_reason") or report.get("reason") or "Waiting for additional evidence.",
        ]
        self._signal_plan_text.configure(state="normal")
        self._signal_plan_text.delete("1.0", "end")
        self._signal_plan_text.insert("1.0", "\n".join(plan_lines))
        self._signal_plan_text.configure(state="disabled")

        stamp = report.get("generated_at", "now")
        notice = f"{stamp} | {symbol} | {str(state).replace('_', ' ')} | {report.get('reason', 'analysis updated')}"
        history = list(getattr(self, "_signal_notifications", []))
        history.append(notice)
        self._signal_notifications = history[-3:]
        self._signal_notification_var.set("\n".join(self._signal_notifications))

        if spread in (None, "--", "-"):
            self._signal_status_var.set(f"{symbol} • {str(state).replace('_', ' ')} • {stamp} • waiting for live market data")
        else:
            self._signal_status_var.set(
                f"{symbol} • {str(state).replace('_', ' ')} • {stamp} • spread {_fmt_signal_spread(spread)} {spread_unit}"
            )
        # Preserve a terse machine-readable snapshot for compatibility and logs.
        self._signal_report.configure(state="normal")
        self._signal_report.delete("1.0", "end")
        self._signal_report.insert("1.0", "\n".join(plan_lines + ["", report.get("reason", "")]))
        self._signal_report.configure(state="disabled")
        self._schedule_signal_refresh()

    def _schedule_signal_refresh(self):
        if self._active_center_view == "signals" and not getattr(self, "_shutting_down", False):
            from skills.trading_skill.profiles import get_trading_profile
            interval_ms = max(5000, int(get_trading_profile(self._trading_hub_controller.trading_mode).monitor_interval_seconds * 1000))
            self._signal_refresh_job = self.after(interval_ms, self._refresh_signal_view)

    def _refresh_trading_view(self):
        if self._trading_refresh_pending:
            return
        self._trading_refresh_pending = True
        self.after(100, self._begin_trading_view_refresh)

    def _begin_trading_view_refresh(self):
        self._trading_refresh_pending = False
        symbol, timeframe = self._get_selected_symbol_and_timeframe()
        account_mode = self._get_selected_account_mode()
        self._trading_refresh_generation += 1
        generation = self._trading_refresh_generation
        self.trading_status_var.set(f"{symbol} • {timeframe} • loading account and market data...")
        self.trading_detail_var.set(f"Loading trading data for {symbol} {timeframe}...")
        self._draw_trading_placeholder_chart()
        threading.Thread(target=self._refresh_trading_view_data, args=(symbol, timeframe, account_mode, generation), daemon=True).start()

    def _start_trading_monitor(self):
        if self._trading_monitor_running:
            return
        self._trading_monitor_running = True
        self.after(5000, self._monitor_trading_opportunities)

    def _start_position_management_loop(self):
        """Runs continuously in the background regardless of which GUI
        view is active -- open positions get break-even/trailing/
        invalidation-exit management on a timer, not just when you
        happen to be looking at the Position Monitor screen."""
        if getattr(self, "_position_management_running", False):
            return
        self._position_management_running = True
        self.after(8000, self._run_position_management_cycle)

    def _run_position_management_cycle(self):
        if not getattr(self, "_position_management_running", False) or self._trading_scan_stop_event.is_set():
            return
        if getattr(self, "_position_management_active", False):
            self.after(20000, self._run_position_management_cycle)
            return
        try:
            account_mode = self._get_selected_account_mode()
            self._position_management_active = True
            threading.Thread(target=self._run_position_management_worker, args=(account_mode,), daemon=True).start()
        finally:
            self.after(20000, self._run_position_management_cycle)

    def _run_position_management_worker(self, account_mode):
        if self._trading_scan_stop_event.is_set() or getattr(self, "_shutting_down", False):
            return
        try:
            if str(account_mode).lower() != self._get_selected_account_mode().lower():
                return
            report = self._trading_hub_controller.run_position_management(account_mode)
            applied = report.get("applied", []) if isinstance(report, dict) else []
            for action in applied:
                text = (
                    f"Position {action.get('symbol')} #{action.get('ticket')}: {action.get('action')}"
                    + (f" -> stop {action.get('new_stop')}" if action.get("new_stop") is not None else "")
                    + (f" ({action.get('reason')})" if action.get("reason") else "")
                )
                if getattr(self, "_shutting_down", False):
                    return
                self.after(0, lambda t=text: self._append_console("TRADING", t))
            if applied and not getattr(self, "_shutting_down", False):
                self.after(0, lambda: self._refresh_trading_view() if self._active_center_view == "trading" else None)
        except Exception as exc:
            if not getattr(self, "_shutting_down", False):
                self.after(0, lambda error=str(exc): self._append_console("TRADING-ERR", f"Position management cycle failed: {error}"))
        finally:
            if not getattr(self, "_shutting_down", False):
                self.after(0, lambda: setattr(self, "_position_management_active", False))

    def _monitor_trading_opportunities(self):
        if not self._trading_monitor_running or self._trading_scan_stop_event.is_set():
            return
        if self._trading_monitor_scan_active:
            self.after(15000, self._monitor_trading_opportunities)
            return
        try:
            account_mode = self._get_selected_account_mode()
            self._trading_monitor_allowed_symbols = self._get_trading_dropdown_symbols()
            self._trading_monitor_scan_active = True
            self._trading_monitor_status_var.set("ANGELIQUE MONITOR: SCANNING ELIGIBLE MT5 SYMBOLS...")
            threading.Thread(target=self._monitor_trading_opportunity_worker, args=(account_mode,), daemon=True).start()
        finally:
            self.after(15000, self._monitor_trading_opportunities)

    def _monitor_trading_opportunity_worker(self, account_mode):
        if self._trading_scan_stop_event.is_set():
            return
        try:
            if getattr(self, "_shutting_down", False):
                return
            if str(account_mode).lower() != self._get_selected_account_mode().lower():
                return
            allowed_symbols = list(getattr(self, "_trading_monitor_allowed_symbols", []) or [])
            self.after(0, lambda: self._trading_monitor_status_var.set("ANGELIQUE MONITOR: CANDIDATE FOUND | ANGELIQUE IS REVIEWING MARKET CONTEXT AND PRIOR TRADES..."))
            scan = self._trading_hub_controller.decide_and_act(
                account_mode,
                allowed_symbols=allowed_symbols or None,
            )
            if str(account_mode).lower() != self._get_selected_account_mode().lower():
                return
            candidates = scan.get("candidates", [])
            state = scan.get("state")

            if state == "AUTO_EXECUTED":
                execution = scan.get("execution", {})
                plan = execution.get("plan") or {}
                message = f"AUTO-EXECUTED {plan.get('direction')} {plan.get('mt5_symbol')} | {execution.get('message')}"
                if getattr(self, "_shutting_down", False):
                    return
                self.after(0, lambda text=message: self._trading_monitor_status_var.set(f"ANGELIQUE MONITOR: {text}"))
                self.after(0, lambda text=message: self._append_console("TRADING", text))
                self.after(0, lambda: self._refresh_trading_view() if self._active_center_view == "trading" else None)
                return

            if isinstance(state, str) and state.startswith("AUTO_EXECUTE_FAILED"):
                execution = scan.get("execution", {})
                message = f"Auto-execution did not go through: {execution.get('message')}"
                if getattr(self, "_shutting_down", False):
                    return
                self.after(0, lambda text=message: self._trading_monitor_status_var.set(f"ANGELIQUE MONITOR: {text}"))
                self.after(0, lambda text=message: self._append_console("TRADING-ERR", text))
                return

            if state == "KILL_ZONE_BLOCKED":
                execution = scan.get("execution", {})
                reason = execution.get("reason") or "Automatic execution is restricted to the configured ICT kill zones."
                if getattr(self, "_shutting_down", False):
                    return
                self.after(0, lambda text=reason: self._trading_monitor_status_var.set(f"ANGELIQUE MONITOR: AUTO BLOCKED BY KILL ZONE | {text}"))
                return

            if state != "PENDING_APPROVAL":
                if getattr(self, "_shutting_down", False):
                    return
                self.after(0, lambda: self._trading_monitor_status_var.set(f"ANGELIQUE MONITOR: WAITING FOR OPPORTUNITY | SCANNED {len(candidates)} ELIGIBLE SYMBOLS | NO VALID SETUP YET"))
                return

            # PENDING_APPROVAL: a high-impact news event or a directional
            # news conflict is present. Every other gate already passed --
            # this is the one case that stops for your explicit sign-off.
            result = scan["opportunity"]
            plan = result["plan"]
            signature = plan.get("confirmation_phrase")
            if not signature or signature == self._trading_monitor_signature or self._trading_monitor_popup_open:
                return
            self._trading_monitor_signature = signature
            if getattr(self, "_shutting_down", False):
                return
            reason = plan.get("manual_approval_reason") or "High-impact news risk."
            self.after(0, lambda: self._trading_monitor_status_var.set(f"ANGELIQUE MONITOR: APPROVAL REQUIRED ON {plan.get('mt5_symbol')} | {reason}"))
            self.after(0, lambda: self._show_trade_plan_popup(result))
        except Exception as exc:
            error_text = str(exc)
            self.after(0, lambda error=error_text: self._trading_monitor_status_var.set(f"ANGELIQUE MONITOR: BLOCKED | {error}"))
            self.after(0, lambda error=error_text: self._append_console("TRADING-ERR", f"Opportunity monitor: {error}"))
        finally:
            if not self._trading_scan_stop_event.is_set():
                self.after(0, lambda: setattr(self, "_trading_monitor_scan_active", False))

    def _get_selected_account_mode(self) -> str:
        return (getattr(self, "_account_mode_var", None).get() if getattr(self, "_account_mode_var", None) is not None else "demo")

    def _on_account_mode_change(self, selected_mode: str):
        """Switch the requested account environment and invalidate every stale UI result."""
        selected_mode = "real" if str(selected_mode).lower() in {"real", "live"} else "demo"
        self._selected_position_ticket = None
        self._save_gui_settings(account_mode=selected_mode)

        # Invalidate in-flight signal/trading workers so results from the old
        # DEMO/REAL environment can never paint the new selection.
        self._signal_generation += 1
        self._signal_refresh_running = False
        if self._signal_refresh_job is not None:
            try:
                self.after_cancel(self._signal_refresh_job)
            except Exception:
                pass
            self._signal_refresh_job = None
        self._trading_refresh_generation += 1
        self._trading_refresh_pending = False

        if self._active_center_view == "signals":
            symbol = self._signal_symbol_var.get() or config.DEFAULT_TRADING_SYMBOL
            self._signal_status_var.set(f"ACCOUNT MODE CHANGED → {selected_mode.upper()}\nVerifying matching MT5 account and fetching fresh market data...")

            def sync_worker(generation):
                try:
                    snapshot = self._trading_hub_controller.synchronize_account_mode(selected_mode)
                    if getattr(self, "_shutting_down", False):
                        return
                    self.after(0, lambda s=snapshot, g=generation: self._finish_account_mode_switch(selected_mode, symbol, s, g))
                except Exception as exc:
                    if not getattr(self, "_shutting_down", False):
                        self.after(0, lambda e=str(exc), g=generation: self._finish_account_mode_switch(selected_mode, symbol, {"connected": False, "error": e}, g))

            generation = self._signal_generation
            threading.Thread(target=sync_worker, args=(generation,), daemon=True).start()
            self.after(5000, lambda g=generation, m=selected_mode, s=symbol: self._account_mode_switch_timeout(m, s, g))
        else:
            self._refresh_trading_view()

    def _account_mode_switch_timeout(self, selected_mode: str, symbol: str, generation: int):
        if generation != self._signal_generation or self._active_center_view != "signals" or not self._signal_refresh_running:
            return
        self._signal_refresh_running = False
        self._signal_status_var.set(f"{symbol} | [{selected_mode.upper()}] | ACCOUNT MODE TIMEOUT\nMT5 account verification did not complete within 5s. No trade plan is trusted.")
        for item in self._signal_evidence_tree.get_children():
            self._signal_evidence_tree.delete(item)
        self._signal_evidence_tree.insert("", "end", values=("Account mode", "BLOCK", "Verification timeout; stale account data suppressed"), tags=("bad",))
        self._signal_plan_text.configure(state="normal")
        self._signal_plan_text.delete("1.0", "end")
        self._signal_plan_text.insert("1.0", f"{symbol}   ACCOUNT MODE TIMEOUT\n\nRequested: {selected_mode.upper()}\n\nNo trade plan will be displayed until MT5 account verification succeeds.")
        self._signal_plan_text.configure(state="disabled")
        self._schedule_signal_refresh()

    def _finish_account_mode_switch(self, selected_mode: str, symbol: str, snapshot: dict, generation: int):
        if generation != self._signal_generation or self._active_center_view != "signals":
            return
        connected = bool(snapshot.get("connected"))
        actual = str(snapshot.get("actual_mode") or "").lower()
        requested = str(snapshot.get("requested_mode") or selected_mode).lower()
        mode_match = connected and actual == requested == selected_mode
        if not mode_match:
            reason = snapshot.get("error") or f"MT5 is connected to {actual or 'unknown'}, requested {selected_mode}."
            self._signal_refresh_running = False
            self._signal_status_var.set(f"{symbol} | [{selected_mode.upper()}] | ACCOUNT MODE MISMATCH\n{reason}")
            for item in self._signal_evidence_tree.get_children():
                self._signal_evidence_tree.delete(item)
            self._signal_evidence_tree.insert("", "end", values=("Account mode", "BLOCK", reason), tags=("bad",))
            self._signal_evidence_tree.insert("", "end", values=("Market data", "BLOCK", "No data from the wrong account is displayed"), tags=("bad",))
            self._signal_plan_text.configure(state="normal")
            self._signal_plan_text.delete("1.0", "end")
            self._signal_plan_text.insert("1.0", f"{symbol}   ACCOUNT MODE MISMATCH\n\nRequested: {selected_mode.upper()}\nActual MT5: {actual.upper() or 'UNKNOWN'}\n\nNo trade plan will be displayed until the MT5 account matches the selected mode.\n\nEXECUTION: NO TRADE")
            self._signal_plan_text.configure(state="disabled")
            self._schedule_signal_refresh()
            return
        self._signal_refresh_running = False
        self._refresh_signal_view()

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

    def _refresh_trading_view_data(self, symbol: str, timeframe: str, account_mode: str, generation: int):
        try:
            result = self._trading_hub_controller.load_refresh(symbol, timeframe, account_mode)
            if result.instruments is not None and not getattr(self, "_shutting_down", False):
                self.after(0, lambda: self._update_symbol_menu(result.instruments))
            if not getattr(self, "_shutting_down", False):
                self.after(0, lambda: self._apply_trading_view_data_if_current(
                    generation,
                    result.symbol,
                    result.account,
                    result.market_data,
                    result.bridge_active,
                    result.bridge_error,
                    result.account_mode,
                    result.health,
                    result.positions,
                    result.analysis,
                ))
        except Exception as exc:
            error_text = str(exc)
            if not getattr(self, "_shutting_down", False):
                self.after(0, lambda error=error_text: self._apply_trading_view_data_if_current(generation, symbol, {}, {}, False, error, account_mode))

    def _apply_trading_view_data_if_current(self, generation, *args):
        if generation != self._trading_refresh_generation:
            return
        self._apply_trading_view_data(*args)

    def _apply_trading_view_data(self, symbol: str, account: dict, market_data: dict, active: bool, bridge_error: str | None, account_mode: str, health: dict | None = None, positions: dict | None = None, analysis: dict | None = None):
        positions = positions or {}
        position_rows = positions.get("positions", []) if isinstance(positions, dict) else []
        account = {
            **(account or {}),
            "current_open_risk_percent": sum(
                float(row.get("risk_percent", 0) or 0)
                for row in position_rows
                if isinstance(row, dict)
            ),
        }
        self._update_position_monitor(positions, market_data or {})
        if self._active_center_view == "trading" and not getattr(self, "_shutting_down", False):
            existing_job = getattr(self, "_position_refresh_job", None)
            if existing_job is None:
                self._position_refresh_job = self.after(5000, self._refresh_position_monitor)
        health = health or {}
        health_state = "ENABLED" if health.get("trading_enabled") else "DISABLED"
        self._trading_health_var.set(
            f"TRADING {health_state} | MT5 {health.get('mt5', 'UNKNOWN')} | "
            f"BRIDGE {health.get('bridge', 'UNKNOWN')} | ACCOUNT {health.get('account', 'UNKNOWN')} | "
            f"MARKET {health.get('market_data', 'UNKNOWN')} | SYMBOL {health.get('symbol', 'UNKNOWN')} | "
            f"MONITOR {health.get('monitor', 'UNKNOWN')}"
        )
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
        display_actual_mode = "REAL" if actual_mode in ("live", "real") else "DEMO"
        display_requested_mode = "REAL" if account_mode in ("live", "real") else "DEMO"
        actual_login = account.get("login") or "unavailable"

        # A mode mismatch must not expose the other account's figures.
        if not account.get("login") or not account_mode_match:
            # Ensure the summary shows zero values for the requested account
            balance = 0
            account = {**(account or {}), "balance": 0, "equity": 0, "free_margin": 0, "margin_level": 0, "login": None}
            if account_mode in ("live", "real"):
                self.trading_status_var.set(f"{symbol} • [{display_requested_mode} MODE] • BRIDGE CONNECTED • REAL ACCOUNT NOT CONNECTED")
            else:
                self.trading_status_var.set(f"{symbol} • [{display_requested_mode} MODE] • bridge {status} • balance ${balance:,.2f}")
            self._update_account_summary(account)
            self._update_trading_mode_banner(account_mode, active, bridge_error, balance, account_mode_match, account_login_exists=False)
            # Keep last account response for badge and diagnostics
            self._last_account = account or {}
            self._last_account_error = account.get("error") or bridge_error
            # Continue so market data can render independently of account login.

        if active and not account_mode_match:
            self.trading_status_var.set(
                f"{symbol} • [{display_actual_mode} MODE] • bridge connected to {display_actual_mode} account • login {actual_login}"
            )
            bridge_error = f"Bridge is connected to {display_actual_mode} account, not {display_requested_mode}."
        elif account_mode in ("live", "real") and not active:
            self.trading_status_var.set(f"{symbol} • [{display_requested_mode} MODE] • BRIDGE OFFLINE • REAL ACCOUNT NOT CONNECTED")
        else:
            self.trading_status_var.set(f"{symbol} • [{display_requested_mode} MODE] • bridge {status} • balance ${balance:,.2f}")

        self._update_account_summary(account)
        self._update_trading_mode_banner(account_mode, active, bridge_error, balance, account_mode_match, account_login_exists=bool(account.get("login")))

        # Keep last account response for badge and diagnostics
        self._last_account = account or {}
        self._last_account_error = account.get("error") or bridge_error

        if active and account.get("login"):
            self._append_trading_transcript(
                f"Bridge connected. Account: {account.get('login')} | Balance: ${account.get('balance', 0):,.2f} | Mode: {display_actual_mode}"
            )

        self._last_chart_market_data = market_data or {}
        # The bridge normally returns candles under market_data["timeframes"].
        # Older/alternate bridge responses may instead provide top-level
        # "candles". Normalize both shapes here so a healthy MT5 connection is
        # never incorrectly rendered as "Market chart unavailable".
        chart_candles = None
        selected_symbol, selected_timeframe = self._get_selected_symbol_and_timeframe()
        chart_timeframe = str(selected_timeframe).upper()
        if isinstance(market_data, dict):
            direct_candles = market_data.get("candles")
            if isinstance(direct_candles, list) and direct_candles:
                chart_candles = direct_candles
                chart_timeframe = market_data.get("timeframe") or chart_timeframe
            else:
                timeframe_map = market_data.get("timeframes")
                if isinstance(timeframe_map, dict):
                    selected_candles = timeframe_map.get(str(chart_timeframe).upper())
                    if isinstance(selected_candles, list) and selected_candles:
                        chart_candles = selected_candles


        if chart_candles:
            self._draw_trading_chart(chart_candles)
            actual_count = len(chart_candles)
            if chart_timeframe == str(selected_timeframe).upper():
                self.trading_detail_var.set(
                    f"Live {chart_timeframe} market data loaded • {actual_count} completed candles available for the chart."
                )
            else:
                self.trading_detail_var.set(
                    f"{str(timeframe).upper()} data was not returned; displaying live {chart_timeframe} data instead • {actual_count} candles."
                )
            self._append_trading_transcript(
                f"Market data loaded for {market_data.get('symbol', symbol)} ({actual_count} candles on {chart_timeframe})."
            )
        else:
            self._draw_trading_placeholder_chart()
            error_text = market_data.get("error") if isinstance(market_data, dict) else None
            suggestions = market_data.get("suggestions") if isinstance(market_data, dict) else None
            if suggestions:
                self._append_trading_transcript(f"Symbol '{symbol}' not found. Broker suggests: {suggestions}")
            elif error_text:
                self._append_trading_transcript(f"Market data error for {symbol}: {error_text}")
            else:
                self._append_trading_transcript(
                    f"No usable candle data returned for {symbol} on {str(timeframe).upper()} in {display_requested_mode} mode."
                )
            self.trading_detail_var.set(
                f"No usable market candles returned{': ' + error_text if error_text else '. MT5 is connected, but this timeframe currently has no usable data.'}"
            )

        self._last_chart_market_data = dict(market_data or {})
        self._last_chart_account = dict(account or {})
        self._update_bridge_error(active, bridge_error)

    def _refresh_position_monitor(self):
        self._position_refresh_job = None
        if self._active_center_view == "trading" and not getattr(self, "_shutting_down", False):
            self._refresh_trading_view()

    def _update_position_monitor(self, positions_response: dict, market_data: dict):
        if not hasattr(self, "_positions_tree"):
            return
        from skills.trading_skill.position_display import format_position_row

        trees = [self._positions_tree]
        for tree in trees:
            for item in tree.get_children():
                tree.delete(item)
        positions = positions_response.get("positions", []) if isinstance(positions_response, dict) else []
        if not positions:
            for tree in trees:
                tree.insert("", "end", values=("No open positions", "-", "-", "-", "$0.00", "-", "-", "WAITING"), tags=("neutral",))
            if getattr(self, "_position_monitor_status_var", None) is not None:
                self._position_monitor_status_var.set("No open positions. Live MT5 position data is synchronized.")
            return

        for index, position in enumerate(positions):
            try:
                row = format_position_row(position, position.get("_market_data", market_data))
            except (TypeError, ValueError, KeyError):
                continue
            def display_price(value):
                return "-" if not value else f"{value:.5f}"

            def display_pips(value):
                return "-" if value is None else f"{value:.1f}"

            profit = row["profit"]
            r_multiple = row["r_multiple"]
            tag = "profit" if profit > 0 else "loss" if profit < 0 else "neutral"
            row_id = str(row["ticket"])
            if row_id in self._positions_tree.get_children() or row_id in {"-", "None"}:
                row_id = f"position-{index}"
            values = (
                f"#{row['ticket']}  {row['symbol']} {row['direction']}",
                f"{display_price(row['current'])} / {display_price(row['entry'])}",
                f"{display_pips(row['to_stop'])} / {display_pips(row['total_stop'])} {row.get('distance_unit', 'pips')}",
                f"{display_pips(row['to_target'])} / {display_pips(row['total_target'])} {row.get('distance_unit', 'pips')}",
                f"${profit:,.2f}",
                "-" if row["expected_profit"] is None else f"+${row['expected_profit']:,.2f}",
                "-" if r_multiple is None else f"{r_multiple:.2f}R", row["status"],
            )
            self._positions_tree.insert("", "end", iid=row_id, values=values, tags=(tag,))
        if getattr(self, "_position_monitor_status_var", None) is not None:
            self._position_monitor_status_var.set(f"{len(positions)} open position(s). Live MT5 position data is synchronized.")

    def _on_position_selected(self, _event=None):
        source = getattr(self, "_positions_tree", None)
        selected = source.selection() if source is not None else ()
        self._selected_position_ticket = None
        self._selected_position_symbol = None
        if selected and source is not None:
            item_id = selected[0]
            values = source.item(item_id, "values")
            try:
                self._selected_position_ticket = int(str(item_id).removeprefix("#"))
            except ValueError:
                pass
            fields = str(values[0]).split() if values else []
            if len(fields) >= 2:
                self._selected_position_symbol = fields[1]

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

    def _get_manual_exit_payload(self) -> dict | None:
        symbol, timeframe = self._get_selected_symbol_and_timeframe()
        symbol = getattr(self, "_selected_position_symbol", None) or symbol
        account_mode = self._get_selected_account_mode()
        if not symbol:
            self._append_console("TRADING-ERR", "Manual exit failed: no trading symbol selected.")
            self.trading_detail_var.set("Manual exit failed: no symbol selected.")
            return None
        if account_mode not in {"demo", "real", "live"}:
            self._append_console("TRADING-ERR", f"Manual exit failed: invalid account mode '{account_mode}'.")
            self.trading_detail_var.set(f"Manual exit failed: invalid account mode '{account_mode}'.")
            return None
        payload = {"symbol": symbol, "account_mode": account_mode, "timeframe": timeframe}
        selected_ticket = getattr(self, "_selected_position_ticket", None)
        if selected_ticket is not None:
            payload["ticket"] = selected_ticket
        return payload

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
        from skills.trading_skill.profiles import get_trading_profile
        profile = get_trading_profile(self._trading_hub_controller.trading_mode)
        equity = float(account.get("equity", 0) or 0) if isinstance(account, dict) else 0.0
        risk_percent = float(config.TRADING_RISK_PER_TRADE_PERCENT) if equity > 0 else 0.0

        # Only show figures for the account mode selected in the Trading Hub.
        if not account or not account.get("login") or account.get("mode_match") is False:
            values = {
                "balance": 0,
                "equity": 0,
                "used_margin": 0,
                "free_margin": 0,
                "margin_level": 0,
                "leverage": "—",
                "currency": account.get("currency", "USD") if isinstance(account, dict) else "USD",
                "account_mode": display_mode,
                "login": "—",
                "risk_percent": risk_percent,
                "risk_amount": 0,
                "daily_loss": 0,
                "weekly_loss": 0,
                "drawdown": 0,
                "consecutive_losses": 0,
                "max_risk": config.TRADING_MAX_RISK_PERCENT,
                "current_open_risk": 0,
            }
        else:
            values = {
                "balance": account.get("balance", 0),
                "equity": account.get("equity", 0),
                "used_margin": account.get("used_margin", account.get("margin", 0)),
                "free_margin": account.get("free_margin", 0),
                "margin_level": account.get("margin_level", 0),
                "leverage": account.get("leverage", "—"),
                "currency": account.get("currency", "USD"),
                "account_mode": display_mode,
                "login": account.get("login", "—"),
                "risk_percent": risk_percent,
                "risk_amount": equity * risk_percent / 100,
                "daily_loss": account.get("daily_loss_percent", 0),
                "weekly_loss": account.get("weekly_loss_percent", 0),
                "drawdown": account.get("drawdown_percent", 0),
                "consecutive_losses": account.get("consecutive_losses", 0),
                "max_risk": config.TRADING_MAX_RISK_PERCENT,
                "current_open_risk": account.get("current_open_risk_percent", 0),
            }
        currency_keys = {"balance", "equity", "used_margin", "free_margin", "risk_amount"}
        percent_keys = {"risk_percent", "daily_loss", "weekly_loss", "drawdown", "max_risk", "current_open_risk"}
        for key, label in self._account_labels.items():
            value = values.get(key, "—")
            if isinstance(value, (int, float)):
                if key in percent_keys:
                    display_value = f"{float(value):.2f}%"
                elif key in currency_keys:
                    display_value = f"${float(value):,.2f}"
                elif key == "margin_level":
                    display_value = f"{float(value):,.2f}%"
                else:
                    display_value = f"{value:,}"
            else:
                display_value = str(value)
            label.configure(text=display_value)

    def _draw_trading_placeholder_chart(self):
        if self.trading_chart_canvas is None:
            return
        self.trading_chart_canvas.delete("all")
        self._last_chart_data = None
        self._last_full_candles = None
        self._chart_selection_rect_id = None
        self._selection_handle_ids = []
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
            self._draw_trading_placeholder_chart(); return

        valid_candles=[]
        for candle in candles:
            if not isinstance(candle, dict): continue
            try:
                o=float(candle.get("open", candle.get("o", candle.get("Open", 0))))
                h=float(candle.get("high", candle.get("h", candle.get("High", o))))
                l=float(candle.get("low", candle.get("l", candle.get("Low", o))))
                c=float(candle.get("close", candle.get("c", candle.get("Close", o))))
            except (TypeError,ValueError): continue
            if min(o,h,l,c) <= 0: continue
            valid_candles.append(candle)
        if not valid_candles:
            self._draw_trading_placeholder_chart(); return
        self._last_full_candles=valid_candles
        # Preserve the canonical market metadata used by the Data Window and
        # chart formatting. Do not invent symbol precision in the GUI.
        self._last_chart_market_data = getattr(self, "_last_chart_market_data", {}) or {}
        self.trading_chart_canvas.delete("all")
        self._chart_crosshair_ids=[]
        width=self.trading_chart_canvas.winfo_width() or 900
        height=self.trading_chart_canvas.winfo_height() or 360
        left,right,top,bottom=54,78,18,32
        plot_w=max(20,width-left-right); plot_h=max(20,height-top-bottom)
        total=len(valid_candles)
        view_count=min(int(getattr(self,'_trading_chart_view_count',80)),total)
        offset=max(0,int(getattr(self,'_trading_chart_view_offset',0)))
        start_idx=max(0,total-view_count-offset); end_idx=min(total,start_idx+view_count)
        selected=valid_candles[start_idx:end_idx]
        prices=[]
        for c in selected:
            try:
                o=float(c.get('open',c.get('o',0))); h=float(c.get('high',c.get('h',o))); l=float(c.get('low',c.get('l',o))); cl=float(c.get('close',c.get('c',o)))
            except (TypeError,ValueError): continue
            prices.append({'open':o,'high':h,'low':l,'close':cl,'time':c.get('time') or c.get('timestamp') or c.get('t'),'tick_volume':c.get('tick_volume') or c.get('volume') or c.get('v'),'raw':c})
        if not prices:
            self._draw_trading_placeholder_chart(); return
        min_price=min(x['low'] for x in prices); max_price=max(x['high'] for x in prices); span=max_price-min_price or 1.0
        def x_for_i(i): return left + (i/max(1,len(prices)-1))*plot_w
        def y_for(price): return top + (max_price-price)/span*plot_h
        self._chart_transform={'left':left,'right':right,'top':top,'bottom':bottom,'plot_w':plot_w,'plot_h':plot_h,'min_price':min_price,'max_price':max_price,'start_idx':start_idx,'end_idx':end_idx,'prices':prices,'height':height}
        # Gridlines and axes, matching the MT5 Data Window feel without obscuring candles.
        h_steps=6
        for j in range(h_steps+1):
            frac=j/h_steps; y=top+frac*plot_h; price=max_price-frac*span
            self.trading_chart_canvas.create_line(left,y,width-right,y,fill=self._theme('border'),width=1,dash=(2,5))
            self.trading_chart_canvas.create_text(width-right+5,y,text=self._format_chart_price(price),fill=self._theme('text'),font=('Consolas',7),anchor='w')
        v_steps=min(10,max(4,len(prices)//20 or 4))
        for j in range(v_steps+1):
            frac=j/v_steps; x=left+frac*plot_w
            self.trading_chart_canvas.create_line(x,top,x,height-bottom,fill=self._theme('border'),width=1,dash=(2,5))
            idx=min(len(prices)-1,round(frac*(len(prices)-1))); label=self._format_chart_time(prices[idx].get('time'))
            self.trading_chart_canvas.create_text(x,height-bottom+6,text=label,fill=self._theme('text'),font=('Consolas',7),anchor='n')
        self.trading_chart_canvas.create_rectangle(left,top,width-right,height-bottom,outline=self._theme('text'),width=1)
        self._draw_volume_profile(prices, left, top, plot_w, plot_h, min_price, max_price)
        candle_w=max(2.5,min(14,plot_w/max(24,len(prices))*0.72))
        points_x=[]
        for idx,p in enumerate(prices):
            x=x_for_i(idx); points_x.append(x)
            yo,yc,yh,yl=map(y_for,(p['open'],p['close'],p['high'],p['low']))
            self.trading_chart_canvas.create_line(x,yh,x,yl,fill=self._theme('text'),width=1)
            up=p['close']>=p['open']; body_fill='#22c55e' if up else '#ef4444'
            self.trading_chart_canvas.create_rectangle(x-candle_w/2,min(yo,yc),x+candle_w/2,max(yo,yc),fill=body_fill,outline=body_fill)
        latest=prices[-1]
        self.trading_chart_canvas.create_line(left,y_for(latest['close']),width-right,y_for(latest['close']),fill=self._theme('accent'),width=1,dash=(4,3))
        self.trading_chart_canvas.create_text(width-right+5,y_for(latest['close']),text=self._format_chart_price(latest['close']),fill=self._theme('accent'),font=('Consolas',7,'bold'),anchor='w')
        self.trading_chart_canvas.create_text(left+4,top+4,text=f"{len(prices)}-period OHLC  |  {str(self._get_selected_symbol_and_timeframe()[1]).upper()}",fill=self._theme('text'),font=('Consolas',8),anchor='nw')
        self._last_chart_data={'prices':prices,'points_x':points_x,'start_idx':start_idx}
        self._redraw_chart_tools()
        self._update_data_window(prices[-1], latest_index=len(prices)-1)

    def _format_chart_price(self, price):
        try:
            digits = None
            market = getattr(self, "_last_chart_market_data", {}) or {}
            specs = market.get("symbol_specs", {}) if isinstance(market, dict) else {}
            if isinstance(specs, dict) and specs.get("digits") is not None:
                digits = int(specs.get("digits") or 0)
            if digits is None:
                symbol = str(self._get_selected_symbol_and_timeframe()[0]).upper()
                digits = 3 if "JPY" in symbol else 5
                if any(token in symbol for token in ("XAU", "XAG", "XPT", "XPD", "GOLD", "SILVER")):
                    digits = 2
            return f"{float(price):.{max(0, digits)}f}"
        except (TypeError, ValueError):
            return "--"

    def _format_chart_time(self, value):
        if value is None:
            return "--"
        try:
            if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().isdigit()):
                stamp=float(value)
                # MT5 bridge timestamps are normally Unix seconds.
                return datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%d %b %H:%M")
        except (TypeError, ValueError, OverflowError, OSError):
            pass
        text=str(value).replace("T", " ")
        return text[:16] if len(text) > 16 else text

    def _update_data_window(self, candle, latest_index=None):
        if not getattr(self,'_data_window_text',None) or not isinstance(candle,dict): return
        market=getattr(self,'_last_chart_market_data',{}) or {}
        bid=market.get('bid','--'); ask=market.get('ask','--')
        spread=market.get('spread_pips') if market.get('spread_pips') is not None else market.get('spread_points',market.get('spread','--'))
        unit=market.get('spread_unit') or ('pips' if market.get('spread_pips') is not None else 'points')
        specs=market.get('symbol_specs',{}) if isinstance(market,dict) else {}
        symbol, timeframe = self._get_selected_symbol_and_timeframe()
        rows=[('Symbol',symbol),('Timeframe',timeframe),('Date',self._format_chart_time(candle.get('time') or candle.get('timestamp') or '--')),
              ('Open',self._format_chart_price(candle.get('open'))),('High',self._format_chart_price(candle.get('high'))),
              ('Low',self._format_chart_price(candle.get('low'))),('Close',self._format_chart_price(candle.get('close'))),
              ('Tick Volume',candle.get('tick_volume','--')),('Bid',self._format_chart_price(bid)),('Ask',self._format_chart_price(ask)),
              ('Spread',f"{spread:.1f} {unit}" if isinstance(spread,(int,float)) else f"{spread} {unit}"),
              ('Candle',f"{(latest_index if latest_index is not None else 0)+1} / {len(getattr(self,'_last_chart_data',{}).get('prices',[]) or [])}"),
              ('Digits',specs.get('digits','--')),('Point',self._format_chart_price(specs.get('point')) if specs.get('point') else '--')]
        text='\n'.join(f"{k:<12} {v}" for k,v in rows)
        self._data_window_text.configure(state='normal'); self._data_window_text.delete('1.0','end'); self._data_window_text.insert('1.0',text); self._data_window_text.configure(state='disabled')

    def _redraw_chart_view(self):
        if getattr(self, "_last_full_candles", None):
            self._draw_trading_chart(self._last_full_candles)

    def _draw_volume_profile(self, prices, left, top, plot_w, plot_h, min_price, max_price):
        """Draw a TradingView-style visible-range volume profile overlay.

        The bridge supplies tick volume for FX symbols, so rows are built from
        candle typical prices and split into up/down volume. The Point of
        Control and a 70% Value Area are then derived from the same rows.
        """
        if not getattr(self, "_volume_profile_var", tk.BooleanVar(value=False)).get() or not prices:
            return
        rows = max(12, min(48, int(getattr(self, "_volume_profile_rows", 30))))
        span = max_price - min_price or 1.0
        row_height = span / rows
        bins = [{"total": 0.0, "up": 0.0, "down": 0.0} for _ in range(rows)]
        for p in prices:
            vol = p.get("tick_volume")
            try:
                vol = float(vol) if vol is not None else 0.0
            except (TypeError, ValueError):
                vol = 0.0
            if vol <= 0:
                continue
            typical = (p["high"] + p["low"] + p["close"]) / 3.0
            idx = max(0, min(rows - 1, int((typical - min_price) / row_height)))
            bins[idx]["total"] += vol
            if p["close"] >= p["open"]:
                bins[idx]["up"] += vol
            else:
                bins[idx]["down"] += vol
        total_volume = sum(b["total"] for b in bins)
        if total_volume <= 0:
            return
        poc = max(range(rows), key=lambda i: bins[i]["total"])
        target = total_volume * float(getattr(self, "_volume_profile_value_area", 0.70))
        included = {poc}
        accumulated = bins[poc]["total"]
        while accumulated < target and len(included) < rows:
            candidates = []
            if poc - 1 >= 0:
                candidates.append(poc - 1)
            if poc + 1 < rows:
                candidates.append(poc + 1)
            candidates = [i for i in candidates if i not in included]
            if not candidates:
                break
            nxt = max(candidates, key=lambda i: bins[i]["total"])
            included.add(nxt)
            accumulated += bins[nxt]["total"]
        val_row, vah_row = min(included), max(included)
        vah = min_price + (vah_row + 1) * row_height
        val = min_price + val_row * row_height
        poc_price = min_price + (poc + 0.5) * row_height

        profile_w = max(85, min(plot_w * 0.22, 165))
        x_right = left + plot_w - 4
        max_bar = max(b["total"] for b in bins) or 1.0
        # Draw before candles so bars remain a backdrop, like TradingView.
        for i, b in enumerate(bins):
            y0 = top + (max_price - (min_price + (i + 1) * row_height)) / span * plot_h
            y1 = top + (max_price - (min_price + i * row_height)) / span * plot_h
            width = profile_w * (b["total"] / max_bar)
            if width <= 0:
                continue
            base_x = x_right - width
            total = b["total"] or 1.0
            up_w = width * (b["up"] / total)
            in_va = i in included
            fill = self._theme("accent") if in_va else self._theme("border")
            self.trading_chart_canvas.create_rectangle(base_x, y0, x_right, y1, fill=fill, outline="", stipple="gray25" if in_va else "gray50", tags=("volume_profile",))
            if b["up"] and b["down"]:
                self.trading_chart_canvas.create_rectangle(base_x, y0, base_x + up_w, y1, fill=self._theme("accent"), outline="", stipple="gray50", tags=("volume_profile",))
        # Key levels.
        y_poc = top + (max_price - poc_price) / span * plot_h
        y_vah = top + (max_price - vah) / span * plot_h
        y_val = top + (max_price - val) / span * plot_h
        for y, label in ((y_poc, "POC"), (y_vah, "VAH"), (y_val, "VAL")):
            self.trading_chart_canvas.create_line(left, y, left + plot_w, y, fill=self._theme("accent"), width=1, dash=(4, 3), tags=("volume_profile",))
            self.trading_chart_canvas.create_text(left + 5, y - 2, text=f"{label} {self._format_chart_price((max_price - (y-top)/plot_h*span))}", fill=self._theme("accent"), font=("Consolas", 6, "bold"), anchor="sw", tags=("volume_profile",))

    def _reset_chart_tool_state(self):
        self._chart_tool_points = []
        self._chart_drag_active = False
        self.trading_chart_canvas.delete("chart_preview")
        self.trading_chart_canvas.delete("chart_drag_select")

    def _chart_point_from_event(self, event):
        data = getattr(self, "_last_chart_data", None)
        t = getattr(self, "_chart_transform", None)
        if not data or not t or not data.get("points_x"):
            return None
        points = data["points_x"]
        idx = min(range(len(points)), key=lambda i: abs(points[i] - event.x))
        y = max(t["top"], min(t["top"] + t["plot_h"], event.y))
        price = t["max_price"] - ((y - t["top"]) / (t["plot_h"] or 1)) * (t["max_price"] - t["min_price"])
        return idx, price

    def _redraw_chart_tools(self):
        data=getattr(self,'_chart_transform',None)
        if not data: return
        prices=data['prices']; n=len(prices)
        def xp(idx): return data['left'] + (max(0,min(n-1,idx))/max(1,n-1))*data['plot_w']
        def yp(price): return data['top'] + (data['max_price']-price)/(data['max_price']-data['min_price'] or 1)*data['plot_h']
        self.trading_chart_canvas.delete('chart_drawings')
        for item in getattr(self,'_chart_drawings',[]):
            kind=item.get('kind'); pts=item.get('points',[])
            if kind=='VLINE' and pts:
                x=xp(pts[0][0]); self.trading_chart_canvas.create_line(x,data['top'],x,data['top']+data['plot_h'],fill=self._theme('accent'),width=1,dash=(4,3),tags=('chart_drawings',))
            elif kind=='HLINE' and pts:
                y=yp(pts[0][1]); self.trading_chart_canvas.create_line(data['left'],y,data['left']+data['plot_w'],y,fill=self._theme('accent'),width=1,dash=(4,3),tags=('chart_drawings',))
            elif kind=='TREND' and len(pts)>=2:
                continue
            elif kind=='CHANNEL' and len(pts)>=3:
                (i1,p1),(i2,p2),(i3,p3)=pts[:3]; dx=i2-i1
                if abs(dx)<1: continue
                slope=(p2-p1)/dx; base_at_3=p1+slope*(i3-i1); off=p3-base_at_3
                y0a=p1+slope*(0-i1); y1a=p1+slope*((n-1)-i1)
                y0b=y0a+off; y1b=y1a+off
                self.trading_chart_canvas.create_line(xp(0),yp(y0a),xp(n-1),yp(y1a),fill=self._theme('accent'),width=1,tags=('chart_drawings',))
                self.trading_chart_canvas.create_line(xp(0),yp(y0b),xp(n-1),yp(y1b),fill=self._theme('accent'),width=1,dash=(6,3),tags=('chart_drawings',))

    def _delete_chart_line_at_point(self, idx, price):
        """Delete the nearest existing horizontal/vertical guide under a click."""
        transform = getattr(self, "_chart_transform", None)
        if not transform:
            return False
        n = len(transform.get("prices", [])) or 1
        x = transform["left"] + (max(0, min(n - 1, idx)) / max(1, n - 1)) * transform["plot_w"]
        y = transform["top"] + (transform["max_price"] - price) / (transform["max_price"] - transform["min_price"] or 1) * transform["plot_h"]
        tolerances = []
        for pos, item in enumerate(getattr(self, "_chart_drawings", [])):
            kind = item.get("kind")
            pts = item.get("points", [])
            if not pts or kind not in {"VLINE", "HLINE"}:
                continue
            di, dp = pts[0]
            if kind == "VLINE":
                lx = transform["left"] + (max(0, min(n - 1, di)) / max(1, n - 1)) * transform["plot_w"]
                tolerances.append((abs(lx - x), pos))
            else:
                ly = transform["top"] + (transform["max_price"] - dp) / (transform["max_price"] - transform["min_price"] or 1) * transform["plot_h"]
                tolerances.append((abs(ly - y), pos))
        if tolerances:
            distance, pos = min(tolerances, key=lambda pair: pair[0])
            if distance <= 7:
                self._chart_drawings.pop(pos)
                self._redraw_chart_tools()
                return True
        return False

    def _on_chart_motion(self, event):
        try:
            data=getattr(self,'_last_chart_data',None)
            if not data or not data.get('prices'): return
            point=self._chart_point_from_event(event)
            if point is None: return
            idx, _price = point; p=data['prices'][idx]; self._update_data_window(p,idx)
            for item in getattr(self,'_chart_crosshair_ids',[]):
                try: self.trading_chart_canvas.delete(item)
                except Exception: pass
            self._chart_crosshair_ids=[]
            t=getattr(self,'_chart_transform',{})
            if self._chart_tool_var.get()=='CROSSHAIR':
                self._chart_crosshair_ids.append(self.trading_chart_canvas.create_line(event.x,t.get('top',0),event.x,t.get('top',0)+t.get('plot_h',0),fill=self._theme('accent'),width=1,dash=(2,2)))
                self._chart_crosshair_ids.append(self.trading_chart_canvas.create_line(t.get('left',0),event.y,t.get('left',0)+t.get('plot_w',0),event.y,fill=self._theme('accent'),width=1,dash=(2,2)))
        except Exception:
            pass

    def _on_chart_button_press(self,event):
        try:
            point=self._chart_point_from_event(event)
            if point is None: return
            idx, price=point
            self.trading_chart_canvas.focus_set()
            # Existing guide objects are directly deletable by clicking them.
            if self._delete_chart_line_at_point(idx, price):
                return 'break'
            tool=self._chart_tool_var.get()
            if tool == 'VLINE':
                self._chart_drawings.append({'kind':'VLINE','points':[(idx,price)]}); self._redraw_chart_tools(); return 'break'
            if tool == 'HLINE':
                self._chart_drawings.append({'kind':'HLINE','points':[(idx,price)]}); self._redraw_chart_tools(); return 'break'
        except Exception:
            pass

    def _on_chart_button_motion(self,event):
        # All previews are handled by _on_chart_motion so that normal canvas
        # motion and drawing motion share one coordinate transform.
        return None

    def _on_chart_button_release(self,event):
        return None

    def _on_trading_chart_resize(self, _event=None):
        if getattr(self, "_shutting_down", False):
            return
        candles = getattr(self, "_last_full_candles", None)
        if candles:
            self._draw_trading_chart(candles)
        else:
            self._draw_trading_placeholder_chart()

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

    def _update_bridge_error(self, bridge_connected: bool, bridge_error: str | None):
        from skills.trading.engine.trading_status import get_bridge_status_label, get_mt5_data_badge_text

        if self._trading_bridge_error_var is not None:
            self._trading_bridge_error_var.set(get_bridge_status_label(bridge_connected, bridge_error))

        try:
            if getattr(self, "_mt5_data_badge_var", None) is not None:
                account_error = getattr(self, "_last_account_error", None)
                last_account = getattr(self, "_last_account", {}) or {}
                actual_mode = (last_account.get("mode") or "").lower()
                requested_mode = (last_account.get("requested_mode") or "").lower()
                mode_match = last_account.get("mode_match", True)
                account_connected = bool(last_account.get("login")) and not bool(account_error)
                actual_mode = self._swap_display_mode(actual_mode)
                requested_mode = self._swap_display_mode(requested_mode)

                badge_text = get_mt5_data_badge_text(actual_mode, requested_mode, bridge_connected, account_connected, bridge_error, mode_match)
                if not badge_text:
                    self._mt5_data_badge_var.set("")
                    try:
                        self._mt5_data_badge_label.configure(bg=self._theme("accent"))
                    except Exception:
                        pass
                else:
                    self._mt5_data_badge_var.set(badge_text)
                    if badge_text == "MT5 unavailable":
                        bg = "#dc2626"
                    elif "Mode mismatch" in badge_text:
                        bg = "#f59e0b"
                    elif badge_text == "Using real MT5 data":
                        bg = "#16a34a"
                    elif badge_text == "Using demo MT5 data":
                        bg = "#0ea5e9"
                    else:
                        bg = self._theme("accent")
                    try:
                        self._mt5_data_badge_label.configure(bg=bg)
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
        self._trading_chart_view_count = max(80, old + 10)
        try:
            self._draw_trading_chart(self._last_full_candles)
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

    def _append_trading_transcript(self, message: str):
        transcript = getattr(self, "trading_transcript_text", None)
        if transcript is None:
            return

    def _update_symbol_menu(self, response):
        if not isinstance(response, dict):
            return
        symbols = response.get("symbols") or response.get("instruments") or []
        from skills.trading_skill.universe import eligible_symbols
        symbols = eligible_symbols(sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}))
        if not symbols or not hasattr(self, "_symbol_menu"):
            return
        current = self._symbol_var.get().strip().upper()
        menu = self._symbol_menu["menu"]
        menu.delete(0, "end")
        for symbol in symbols:
            menu.add_command(label=symbol, command=lambda value=symbol: self._symbol_var.set(value))
        if current not in symbols:
            self._symbol_var.set(symbols[0])
        signal_menu_owner = getattr(self, "_signal_symbol_menu", None)
        if signal_menu_owner is not None:
            signal_current = self._signal_symbol_var.get().strip().upper()
            signal_menu = signal_menu_owner["menu"]
            signal_menu.delete(0, "end")
            for symbol in symbols:
                signal_menu.add_command(label=symbol, command=lambda value=symbol: self._signal_symbol_var.set(value))
            if signal_current not in symbols:
                self._signal_symbol_var.set(symbols[0])

    def _get_market_symbols(self) -> list[str]:
        try:
            try:
                from skills.trading.engine.connection_manager import bridge_manager
                account_mode = self._gui_settings.get("account_mode", "demo")
                resp = bridge_manager.send_command("list_instruments", {"account_mode": account_mode})
                if isinstance(resp, dict) and (resp.get("symbols") or resp.get("instruments")):
                    from skills.trading_skill.universe import eligible_symbols
                    return eligible_symbols([s.upper() for s in (resp.get("symbols") or resp.get("instruments"))])
                if isinstance(resp, dict) and resp.get("instruments"):
                    from skills.trading_skill.universe import eligible_symbols
                    return eligible_symbols([s.upper() for s in resp.get("instruments")])
                if isinstance(resp, list):
                    from skills.trading_skill.universe import eligible_symbols
                    return eligible_symbols([s.upper() for s in resp])
            except Exception:
                pass
        except Exception:
            pass

        # Fallback common symbols list
        from skills.trading_skill.universe import eligible_symbols
        return eligible_symbols([s.upper() for s in config.TRADING_SYMBOLS])

    def _get_trading_dropdown_symbols(self) -> list[str]:
        """Return exactly the symbols currently exposed by the Trading Hub menu."""
        menu_owner = getattr(self, "_symbol_menu", None)
        if menu_owner is None:
            return []
        try:
            menu = menu_owner["menu"]
            symbols = []
            for index in range(menu.index("end") + 1):
                label = menu.entrycget(index, "label")
                if label:
                    symbols.append(str(label).strip().upper())
            return symbols
        except (tk.TclError, TypeError, ValueError):
            return []

    def _show_trade_plan_popup(self, result):
        """Show a complete assistant-generated plan before any approval action."""
        plan = result.get("plan") if isinstance(result, dict) else None
        message = result.get("message", "No executable trade plan was produced.") if isinstance(result, dict) else str(result)
        if not plan:
            self.trading_detail_var.set(message)
            self._append_console("TRADING", message)
            return
        dialog = tk.Toplevel(self)
        dialog.title("Angelique trade plan")
        dialog.configure(bg=self._theme("panel"))
        dialog.transient(self)
        dialog.grab_set()
        def get_value(name):
            value = plan.get(name) if isinstance(plan, dict) else getattr(plan, name)
            return "-" if value is None else value

        rationale = plan.get("rationale", []) if isinstance(plan, dict) else plan.rationale
        smc_analysis = plan.get("smc_analysis", {}) if isinstance(plan, dict) else getattr(plan, "smc_analysis", {})
        profile = plan.get("profile", {}) if isinstance(plan, dict) else getattr(plan, "profile", {})
        confluence = (result.get("details") or {}).get("confluence", {}) if isinstance(result, dict) else {}
        analysis_details = (result.get("details") or {}).get("analysis", {}) if isinstance(result, dict) else {}
        strategy_info = (analysis_details.get("strategy") or {}).get("selected", {})
        strategy_name = plan.get("strategy") if isinstance(plan, dict) else None
        strategy_name = strategy_name or strategy_info.get("name") or profile.get("strategy_mode") or "AUTO"
        account = result.get("account") if isinstance(result, dict) else None
        market = result.get("market") if isinstance(result, dict) else None
        if account is not None and not isinstance(account, dict):
            account = account.__dict__
        if market is not None and not isinstance(market, dict):
            market = market.__dict__
        risk_amount = float(get_value("risk_amount"))
        expected_profit = get_value("expected_profit_at_tp")
        potential_profit = float(expected_profit) if expected_profit not in (None, "-", "") else risk_amount * float(get_value("reward_to_risk"))
        score = confluence.get("score", "-")
        mode = plan.get("trading_mode", "DAY_TRADING") if isinstance(plan, dict) else getattr(plan, "trading_mode", "DAY_TRADING")
        structure = smc_analysis.get("structure_shift", "none") if isinstance(smc_analysis, dict) else "none"
        sweep = smc_analysis.get("liquidity_sweep", "none") if isinstance(smc_analysis, dict) else "none"
        location = smc_analysis.get("location", "unknown") if isinstance(smc_analysis, dict) else "unknown"
        news_context = plan.get("news_context", {}) if isinstance(plan, dict) else getattr(plan, "news_context", {})
        session_context = ((plan.get("analysis_audit") or {}).get("session_context", {}) if isinstance(plan, dict) else {})
        try:
            score_value = float(score)
        except (TypeError, ValueError):
            score_value = 0.0
        indicator_color = "#22c55e" if score_value >= 80 else "#ef4444"
        indicator_text = "HIGH CONFIDENCE" if score_value >= 80 else "POSSIBLE / LOWER CONFIDENCE"
        body = "\n".join([
            "ANGELIQUE - TRADE PLAN SUMMARY",
            "STATUS: READY FOR APPROVAL",
            "EXECUTION TARGET",
            f"Broker: {get_value('broker')} | Platform: {get_value('platform')} | Account: {get_value('account_login')}",
            f"Environment: {get_value('account_mode')} | Symbol: {get_value('mt5_symbol')} | Direction: {get_value('direction')}",
            f"PAIR: {get_value('mt5_symbol')}",
            f"MODE: {mode} | STRATEGY: {strategy_name} | SCORE: {score}/100 | MINIMUM: {profile.get('minimum_score', 70)}/100",
            f"Stop basis: {get_value('stop_basis')}",
            f"Target basis: {get_value('target_basis')}",
            "",
            "SETUP",
            f"DIRECTION: {get_value('direction')} | ORDER: {get_value('order_type')}",
            f"Structure: {structure} | Liquidity: {sweep} | Zone: {location}",
            f"News: {news_context.get('bias', 'unknown')} | {news_context.get('reason', 'No news context available.')}",
            f"Timeframes: {profile.get('context_timeframe', 'H4')} > {profile.get('trend_timeframe', 'H1')} > {profile.get('setup_timeframe', 'M15')} > {profile.get('entry_timeframe', 'M5')}",
            f"Session: {session_context.get('session', 'UNKNOWN')} | Active: {', '.join(session_context.get('active_sessions', [])) or 'none'}",
            f"Spread: {((market or {}).get('spread_pips') if (market or {}).get('spread_pips') is not None else (market or {}).get('spread_points', (market or {}).get('spread', '-')))} {(market or {}).get('spread_unit', 'pips')}",
            "",
            "EXECUTION LEVELS",
            f"Entry: {get_value('entry')} | Stop: {get_value('stop_loss')} | Target: {get_value('take_profit')}",
            f"Reward/Risk: 1:{float(get_value('reward_to_risk')):.2f} | Volume: {get_value('volume')}",
            "",
            "RISK",
            f"Risk: {float(get_value('risk_percent')):.2f}% | Planned SL loss: ${float(get_value('actual_risk_amount') if get_value('actual_risk_amount') not in ('-', None) else risk_amount):.2f} | Estimated profit at TP: ${potential_profit:.2f}",
            f"Estimated spread cost: ${get_value('estimated_spread_cost')} | Commission: ${get_value('estimated_commission')} | Swap: ${get_value('estimated_swap_cost')}",
            f"Margin required: ${get_value('margin_required')} | Free margin after: ${get_value('free_margin_after')}",
            f"Equity: ${(account or {}).get('equity', '-')} | Projected margin level: {get_value('projected_margin_level')}",
            "",
            "INVALIDATION",
            f"Cancel the {get_value('direction').lower()} idea if price reaches {get_value('stop_loss')} or the plan expires.",
            "Market execution may vary with spread and slippage.",
            "",
            f"TYPE EXACTLY: {get_value('confirmation_phrase')}",
        ])
        dialog.minsize(760, 480)
        dialog.geometry("820x560")
        dialog.resizable(True, True)

        indicators = tk.Frame(dialog, bg=self._theme("panel"))
        indicators.pack(fill="x", padx=20, pady=(16, 0))
        for label in ("SETUP QUALITY",):
            indicator = tk.Frame(indicators, bg=self._theme("panel"))
            indicator.pack(side="left", padx=(0, 24))
            light = tk.Canvas(indicator, width=16, height=16, bg=self._theme("panel"), highlightthickness=0)
            light.create_oval(2, 2, 14, 14, fill=indicator_color, outline=indicator_color)
            light.pack(side="left", padx=(0, 6))
            tk.Label(
                indicator,
                text=f"{label}: {indicator_text}",
                fg=self._theme("accent") if score_value >= 80 else self._theme("text"),
                bg=self._theme("panel"),
                font=("Consolas", 9, "bold"),
            ).pack(side="left")

        body_container = tk.Frame(dialog, bg=self._theme("panel"))
        body_container.pack(fill="both", expand=True, padx=20, pady=(20, 0))

        body_box = tk.Text(
            body_container,
            wrap="word",
            fg=self._theme("text"),
            bg=self._theme("panel"),
            insertbackground=self._theme("text"),
            relief="flat",
            highlightthickness=0,
            font=("Consolas", 10),
            width=88,
            height=20,
        )
        body_box.insert("1.0", body)
        body_box.configure(state="disabled")
        scrollbar = tk.Scrollbar(body_container, orient="vertical", command=body_box.yview)
        body_box.configure(yscrollcommand=scrollbar.set)
        body_box.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        actions = tk.Frame(dialog, bg=self._theme("panel"), height=64)
        actions.pack(fill="x", padx=20, pady=(6, 20))
        actions.pack_propagate(False)
        tk.Button(actions, text="Cancel", command=lambda: self._cancel_trade_plan(dialog), fg=self._theme("text"), bg=self._theme("button_bg"), bd=0, padx=16, pady=10).pack(side="right", padx=(10, 0))
        self._trading_monitor_popup_open = True
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._cancel_trade_plan(dialog))
        tk.Button(actions, text="APPROVE & EXECUTE", command=lambda: self._approve_trade_plan(dialog, get_value("confirmation_phrase")), fg=self._theme("text"), bg=self._theme("button_active"), bd=0, padx=16, pady=10).pack(side="right")
        self._center_dialog(dialog)

    def _cancel_trade_plan(self, dialog):
        self._trading_monitor_popup_open = False
        dialog.destroy()

    def _approve_trade_plan(self, dialog, confirmation_phrase):
        dialog.destroy()
        self._trading_monitor_popup_open = False
        self.trading_detail_var.set("Executing approved trade plan...")

        def execute_worker():
            from core.execution_gateway import GATEWAY
            import core.trading_gateway

            execution = GATEWAY.execute(
                "trading.execute_approved_trade",
                {"confirmation_phrase": confirmation_phrase},
                user_request="Approve and execute the displayed TradePlan",
                session_id="gui-trading-hub",
                timeout=30.0,
            )
            output = execution.output if isinstance(execution.output, dict) else {}
            message = execution.error or output.get("message", "Trade execution completed.")
            details = output.get("details") if isinstance(output.get("details"), dict) else {}
            if output.get("state") in {"REJECTED", "EXPIRED"}:
                stage = details.get("failure_stage", "execution")
                reason = details.get("reason", message)
                message = f"{output.get('state')}: {reason} [stage: {stage}]"
                diagnostic = f"{message} | details={details}"
            else:
                diagnostic = None
            if not getattr(self, "_shutting_down", False):
                self.after(0, lambda result=message, detail=diagnostic: (
                    self.trading_detail_var.set(result),
                    self._append_console("TRADING", result),
                    self._append_console("TRADING-DIAGNOSTIC", detail) if detail else None,
                    self._refresh_trading_view() if self._active_center_view == "trading" else None,
                ))

        threading.Thread(target=execute_worker, daemon=True).start()

    def _manual_exit_trade(self):
        try:
            payload = self._get_manual_exit_payload()
            if not payload:
                return
            self._append_console("TRADING", f"Manual exit requested for {payload['symbol']} on account {payload['account_mode']}.")
            self._append_console("DEBUG", f"Exit payload: {payload}")
            self.trading_detail_var.set("Closing selected trade...")

            def exit_worker():
                from core.execution_gateway import GATEWAY
                import core.trading_gateway

                execution = GATEWAY.execute(
                    "trading.close_position",
                    payload,
                    user_request="Close the selected active trade",
                    session_id="gui-trading-hub",
                    timeout=30.0,
                )
                response = execution.output if execution.success and isinstance(execution.output, dict) else {"error": execution.error}
                message = response.get("message") or response.get("error") or response.get("status") or "Manual exit attempted."
                success = response.get("success") is True or response.get("status") == "closed"
                if not getattr(self, "_shutting_down", False):
                    self.after(0, lambda: self._append_console("DEBUG", f"Bridge response: {response}"))
                    self.after(0, lambda text=message, ok=success: self._record_exit_result(text, ok))

            threading.Thread(target=exit_worker, daemon=True).start()
        except Exception as exc:
            self._append_console("TRADING-ERR", f"Manual exit failed: {exc}")
            self.trading_detail_var.set(f"Manual exit failed: {exc}")

    def _record_exit_result(self, message: str, success: bool):
        prefix = "successful" if success else "failed"
        self.trading_detail_var.set(f"Manual exit {prefix}: {message}")
        self._append_console("TRADING" if success else "TRADING-ERR", f"Manual exit {prefix}: {message}")

    def _close_all_positions(self):
        if not messagebox.askyesno(
            "Close all positions",
            "This will immediately close every open position on the selected account. Continue?",
        ):
            return
        account_mode = self._get_selected_account_mode()
        self._append_console("TRADING", f"Manual close-all requested on account {account_mode}.")
        self.trading_detail_var.set("Closing all open positions...")

        def worker():
            from core.execution_gateway import GATEWAY
            import core.trading_gateway

            execution = GATEWAY.execute(
                "trading.close_all_positions",
                {"account_mode": account_mode},
                user_request="Close every open position",
                session_id="gui-trading-hub",
                timeout=30.0,
            )
            response = execution.output if execution.success and isinstance(execution.output, dict) else {"error": execution.error}
            closed = len(response.get("closed", []) or [])
            failed = len(response.get("failed", []) or [])
            success = bool(response.get("success"))
            message = response.get("status") or response.get("error") or "Close-all attempted."
            summary = f"Close all positions: {message} (closed {closed}, failed {failed})"
            if not getattr(self, "_shutting_down", False):
                self.after(0, lambda text=summary, ok=success: self._record_exit_result(text, ok))
                self.after(0, lambda: self._refresh_trading_view() if self._active_center_view == "trading" else None)

        threading.Thread(target=worker, daemon=True).start()

    def _update_avatar(self):
        """Keep the Angelique portrait large and visually dominant."""
        if self.ring_canvas is None:
            return
        try:
            self.ring_canvas.update_idletasks()
        except Exception:
            pass
        width = self.ring_canvas.winfo_width() or 760
        height = self.ring_canvas.winfo_height() or 570
        avatar_image = getattr(self, "_avatar_image", None)
        center_x = width // 2
        center_y = height // 2

        # The core is deliberately large: it should read as the system's
        # visual identity, not as one small node inside the HUD.
        avatar_size = int(max(180, min(290, min(width, height) * 0.48)))
        if avatar_size > min(width - 120, height - 140):
            avatar_size = int(min(width - 120, height - 140))
        avatar_size = max(150, avatar_size)

        if avatar_image and ImageDraw and ImageTk:
            try:
                if getattr(self, "_avatar_size_cached", 0) != avatar_size or not getattr(self, "_avatar_photo", None):
                    avatar = self._create_circular_avatar(avatar_image, avatar_size)
                    if avatar is not None:
                        self._avatar_photo = ImageTk.PhotoImage(avatar)
                        self._avatar_size_cached = avatar_size
                existing_avatar = False
                if self._avatar_canvas_id is not None:
                    try:
                        existing_avatar = self._avatar_canvas_id in self.ring_canvas.find_all()
                    except Exception:
                        existing_avatar = False
                if existing_avatar:
                    self.ring_canvas.coords(self._avatar_canvas_id, center_x, center_y)
                    self.ring_canvas.itemconfigure(self._avatar_canvas_id, image=self._avatar_photo)
                else:
                    self._avatar_canvas_id = self.ring_canvas.create_image(
                        center_x, center_y, image=self._avatar_photo, anchor="center", tags=("hud_avatar",)
                    )
                self.ring_canvas.coords(self._avatar_canvas_id, int(center_x), int(center_y))
                self.ring_canvas.tag_raise(self._avatar_canvas_id)
                if self._avatar_text_id is not None:
                    self.ring_canvas.delete(self._avatar_text_id)
                    self._avatar_text_id = None
                return
            except Exception:
                pass

        text = "ANGELIQUE"
        font_size = max(22, min(42, int(min(width, height) / 15)))
        if self._avatar_text_id is not None:
            self.ring_canvas.coords(self._avatar_text_id, center_x, center_y)
            self.ring_canvas.itemconfigure(self._avatar_text_id, text=text, fill=self._theme("accent"))
        else:
            self._avatar_text_id = self.ring_canvas.create_text(
                center_x, center_y, text=text, fill=self._theme("accent"),
                font=("Consolas", font_size, "bold")
            )
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
        self._create_command_button(self.right_panel, "HOTSPOT HUB", command=self._show_wifi_view)
        self._create_command_button(self.right_panel, "VOICE ASSIST", command=self._toggle_audio_mode)
        self._create_command_button(self.right_panel, "SYSTEM DIAGNOSTICS", command=self._show_system_diagnostics)
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

    def _show_system_diagnostics(self):
        self._append_console("SYSTEM", "Running local system diagnostics.")
        try:
            from core.tools import call_skill
            health = call_skill("system_monitor.get_system_health", {})
            if isinstance(health, str):
                try:
                    import json
                    health = json.loads(health)
                except Exception:
                    health = {"error": health}
            top_processes = call_skill("get_running_processes", {"limit": 8})
            online = self._check_online()
            mode = "REMOTE MODE ENABLED" if online else "LOCAL MODE ENABLED"

            if isinstance(health, dict) and health.get("error"):
                raise RuntimeError(health["error"])

            payload = [
                "ANGELIQUE SYSTEM DIAGNOSTICS",
                "",
                f"Runtime mode: {mode}",
                f"Internet check: {'online' if online else 'offline'}",
                f"Hostname: {health.get('hostname', 'unknown')}",
                f"Platform: {health.get('platform', 'unknown')}",
                f"CPU: {health.get('cpu_percent', 0)}%",
                f"CPU cores: {health.get('cpu_cores', 'unknown')}",
                f"Memory: {health.get('memory_percent', 0)}% ({health.get('memory_used_gb', 0)} / {health.get('memory_total_gb', 0)} GB)",
                f"Disk: {health.get('disk_percent', 0)}% ({health.get('disk_used_gb', 0)} / {health.get('disk_total_gb', 0)} GB)",
                f"Uptime: {health.get('uptime_seconds', 0):.1f} seconds",
                f"Boot time: {health.get('boot_time', 'unknown')}",
                f"Network sent: {health.get('network_sent_mb', 0)} MB | received: {health.get('network_recv_mb', 0)} MB",
                "",
                "TOP PROCESSES",
                str(top_processes),
            ]
            for part in payload:
                self._append_console("SYSTEM", str(part))
        except Exception as exc:
            self._append_console("SYSTEM", f"Failed to gather PC health: {exc}")

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
            highlightthickness=0,
            cursor="hand2",
            command=(lambda: self._send_command(label)) if command is None else command,
        )
        self._bind_button_feedback(button, command if command is not None else (lambda: self._send_command(label)))
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
        """Render a large JARVIS-inspired (but original) Angelique system HUD.

        The design uses the restored Angelique portrait as the dominant centre,
        with nested animated rings, radial ticks, orbit nodes and live telemetry
        ribbons.  No four-corner card matrix is used.
        """
        if self.ring_canvas is None:
            return
        try:
            self.ring_canvas.delete("all")
            self.ring_canvas.update_idletasks()
        except Exception:
            return

        width = self.ring_canvas.winfo_width() or 760
        height = self.ring_canvas.winfo_height() or 570
        bg = self._theme("panel")
        text = self._theme("text")
        accent = self._theme("accent")
        border = self._theme("border")
        alt = self._theme("panel_alt")

        self._ring_state = {"width": width, "height": height}
        self._ring_focus = None
        self._ring_particle_ids = []
        self._ring_node_ids = []
        self._ring_node_meta = {}
        self._ring_arc_ids = []
        self._ring_arc_config = []

        # Layered HUD backdrop with perspective-style sweep lines.
        self.ring_canvas.create_rectangle(0, 0, width, height, fill=bg, outline="", tags=("hud",))
        self.ring_canvas.create_rectangle(10, 10, width - 10, height - 10, outline=border, width=1, tags=("hud",))
        self.ring_canvas.create_line(22, 54, width - 22, 54, fill=border, dash=(2, 8), tags=("hud",))
        self.ring_canvas.create_text(24, 28, anchor="w", text="ANGELIQUE • SYNTHESIS CORE", fill=accent,
                                     font=("Consolas", 12, "bold"), tags=("hud",))
        self.ring_canvas.create_text(width - 24, 28, anchor="e", text="SYSTEM-WIDE / ONLINE", fill=text,
                                     font=("Consolas", 7, "bold"), tags=("hud",))

        cx, cy = width / 2.0, height / 2.0 + 4
        base_r = max(92, min(148, int(min(width, height) * 0.245)))
        self._ring_state.update({"cx": cx, "cy": cy, "base_r": base_r})

        # Decorative elliptical rings and angular brackets make the centre
        # read as an active interface instead of a static image.
        for radius, dash, w in (
            (base_r + 9, None, 2), (base_r + 24, (3, 6), 1),
            (base_r + 42, (1, 9), 1), (base_r + 63, (6, 11), 1)
        ):
            item = self.ring_canvas.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                                                 outline=accent if radius in {base_r + 9, base_r + 42} else border,
                                                 width=w, dash=dash, tags=("hud_ring",))
            self._ring_arc_ids.append(item)

        # Dense radial ticks.
        for i in range(72):
            ang = 2 * math.pi * i / 72.0
            r1 = base_r + 67
            r2 = r1 + (9 if i % 6 == 0 else 4)
            x1, y1 = cx + math.cos(ang) * r1, cy + math.sin(ang) * r1
            x2, y2 = cx + math.cos(ang) * r2, cy + math.sin(ang) * r2
            self.ring_canvas.create_line(x1, y1, x2, y2,
                                         fill=accent if i % 9 == 0 else border,
                                         width=1, tags=("hud_ring",))

        # Rotating segmented arcs.
        arc_configs = [
            (base_r + 20, 18, 78, 1),
            (base_r + 34, 136, 62, -1),
            (base_r + 52, 252, 84, 1),
            (base_r + 67, 312, 34, -1),
        ]
        for radius, start_angle, extent, direction in arc_configs:
            item = self.ring_canvas.create_arc(cx - radius, cy - radius, cx + radius, cy + radius,
                                               start=start_angle, extent=extent, style="arc",
                                               outline=accent, width=2, tags=("hud_arc",))
            self._ring_arc_config.append({"id": item, "start": start_angle, "extent": extent,
                                          "direction": direction, "radius": radius})

        # Scanner beam.
        self._scanner_item = self.ring_canvas.create_line(
            cx, cy, cx + base_r + 75, cy, fill=accent, width=1, tags=("hud_scan",)
        )
        self._scanner_dot = self.ring_canvas.create_oval(
            cx + base_r + 69, cy - 4, cx + base_r + 77, cy + 4,
            fill=accent, outline="", tags=("hud_scan",)
        )

        # Core aura: multiple transparent-ish outlines pulsed by animation.
        self._glow_items = []
        for scale in (0.94, 0.80, 0.66, 0.54):
            radius = base_r * scale
            self._glow_items.append(self.ring_canvas.create_oval(
                cx - radius, cy - radius, cx + radius, cy + radius,
                outline=accent, width=1, dash=(2, 5) if scale < 0.9 else None,
                tags=("hud_core",)
            ))

        self.ring_canvas.create_text(cx, cy - base_r - 34, text="ANGELIQUE", fill=accent,
                                     font=("Consolas", 14, "bold"), tags=("hud",))
        self.ring_canvas.create_text(cx, cy + base_r + 30, text="SENSE • REMEMBER • REASON • RESPOND",
                                     fill=text, font=("Consolas", 7, "bold"), tags=("hud",))

        # Floating subsystem nodes, deliberately outside the rings.
        node_specs = [
            ("VISION", -148, "Vision Matrix", lambda: self._set_ring_focus("Vision Matrix", "Visual analysis layer active.")),
            ("MEMORY", -32, "Memory Vault", lambda: self._set_ring_focus("Memory Vault", "Memory and context layer active.")),
            ("TRADING", 28, "Trading Bridge", self._enter_trading_view),
            ("VOICE", 148, "Voice Layer", self._toggle_audio_mode),
            ("SYSTEM", 212, "System Diagnostics", self._show_system_diagnostics),
            ("NETWORK", 328, "Network Status", lambda: self._set_ring_focus("Network", "Network and connectivity layer active.")),
        ]
        orbit_r = base_r + 103
        for label, angle_deg, detail, callback in node_specs:
            angle = math.radians(angle_deg)
            nx, ny = cx + math.cos(angle) * orbit_r, cy + math.sin(angle) * orbit_r
            inner_r = base_r + 64
            ix, iy = cx + math.cos(angle) * inner_r, cy + math.sin(angle) * inner_r
            self.ring_canvas.create_line(ix, iy, nx, ny, fill=border, width=1, dash=(2, 6), tags=("hud_nodes",))
            node = self.ring_canvas.create_oval(nx - 16, ny - 16, nx + 16, ny + 16,
                                                fill=alt, outline=accent, width=1, tags=("hud_node",))
            self.ring_canvas.create_oval(nx - 6, ny - 6, nx + 6, ny + 6,
                                         outline=border, width=1, tags=("hud_node_detail",))
            text_id = self.ring_canvas.create_text(nx, ny + 26, text=label, fill=text,
                                                   font=("Consolas", 7, "bold"), tags=("hud_node_text",))
            self._ring_node_ids.extend([node, text_id])
            self._ring_node_meta[node] = {"label": label, "detail": detail, "callback": callback,
                                          "text_id": text_id, "x": nx, "y": ny}
            for target in (node, text_id):
                self.ring_canvas.tag_bind(target, "<Enter>", lambda e, item=node: self._ring_node_hover(item, True))
                self.ring_canvas.tag_bind(target, "<Leave>", lambda e, item=node: self._ring_node_hover(item, False))
                self.ring_canvas.tag_bind(target, "<Button-1>", lambda e, item=node: self._ring_node_click(item))

        # Fine particle field to add depth and continuous motion.
        self._ring_particles = []
        for i in range(44):
            angle = 2 * math.pi * i / 44.0
            radius = orbit_r + 4 + (i % 8) * 7
            pid = self.ring_canvas.create_oval(0, 0, 0, 0, fill=accent, outline="", tags=("hud_particle",))
            self._ring_particle_ids.append(pid)
            self._ring_particles.append({"id": pid, "angle": angle,
                                          "radius": radius, "speed": 0.0035 + (i % 5) * 0.0012,
                                          "size": 1 + (i % 3)})

        # Compact live telemetry ribbons instead of the old corner cards.
        def ribbon(x, y, w, label, value):
            self.ring_canvas.create_line(x, y, x + w, y, fill=border, tags=("hud_ribbon",))
            self.ring_canvas.create_text(x, y + 13, anchor="w", text=label, fill=text,
                                         font=("Consolas", 6), tags=("hud_ribbon",))
            self.ring_canvas.create_text(x + w, y + 13, anchor="e", text=value, fill=accent,
                                         font=("Consolas", 7, "bold"), tags=("hud_ribbon",))

        cpu = self._system_stats.get("cpu", 0)
        mem = self._system_stats.get("memory", 0)
        net = self._system_stats.get("network_mbps", 0)
        status = self._system_stats.get("status", "READY")
        ribbon(28, height - 78, width * 0.22, "CPU", f"{cpu}%")
        ribbon(width * 0.38, height - 78, width * 0.22, "MEMORY", f"{mem}%")
        ribbon(width * 0.68, height - 78, width * 0.22, "NET", f"{net:.1f} Mbps")
        self.ring_canvas.create_text(width - 24, height - 32, anchor="e", text=f"STATUS • {status}",
                                     fill=accent, font=("Consolas", 8, "bold"), tags=("hud",))

        self._update_avatar()
        if self._avatar_canvas_id is not None:
            self.ring_canvas.tag_raise(self._avatar_canvas_id)
        self._set_ring_focus("System Core", "Select a subsystem node to interact with Angelique.", log=False)
    def _set_ring_focus(self, title: str, detail: str = "", *, log: bool = True):
        self._ring_focus = title
        if self.center_status_label is not None and getattr(self, "_active_center_view", "home") == "home":
            self.center_status_label.configure(text=f"FOCUS: {title.upper()}" if not detail else f"FOCUS: {title.upper()} • {detail}")
        if log:
            self._append_console("CORE", f"Focus changed to {title}. {detail}".strip())

    def _ring_node_hover(self, item_id: int, active: bool):
        meta = self._ring_node_meta.get(item_id)
        if not meta or self.ring_canvas is None:
            return
        try:
            self.ring_canvas.itemconfigure(item_id, outline=self._theme("accent") if active else self._theme("border"), width=2 if active else 1)
            self.ring_canvas.itemconfigure(meta["text_id"], fill=self._theme("accent") if active else self._theme("text"))
            if active:
                self._set_ring_focus(meta["detail"], "Interactive subsystem node", log=False)
        except Exception:
            pass

    def _ring_node_click(self, item_id: int):
        meta = self._ring_node_meta.get(item_id)
        if not meta:
            return "break"
        self._set_ring_focus(meta["detail"])
        callback = meta.get("callback")
        if callable(callback):
            try:
                callback()
            except Exception as exc:
                self._append_console("CORE", f"Subsystem action failed: {exc}")
        return "break"

    def _set_avatar_status(self, mode: str | None, text: str | None = None):
        if self._avatar_status_blink_job is not None:
            self.after_cancel(self._avatar_status_blink_job)
            self._avatar_status_blink_job = None

        if mode is None:
            if self._avatar_status_text_id is not None:
                try:
                    self.ring_canvas.delete(self._avatar_status_text_id)
                except Exception:
                    pass
                self._avatar_status_text_id = None
            self._avatar_status_mode = None
            self._avatar_status_dot_count = 0
            return

        if self.ring_canvas is None:
            return

        if self._avatar_status_text_id is None:
            width = self.ring_canvas.winfo_width() or 520
            height = self.ring_canvas.winfo_height() or 520
            center_x = width // 2
            center_y = height // 2
            self._avatar_status_text_id = self.ring_canvas.create_text(
                center_x,
                int(center_y + min(width, height) * 0.28),
                text="",
                fill=self._theme("accent"),
                font=("Consolas", max(10, int(min(width, height) * 0.024)), "bold"),
                tags=("ring",),
            )

        self._avatar_status_mode = mode
        self._avatar_status_dot_count = 0
        self._animate_avatar_status()

    def _animate_avatar_status(self):
        if self._avatar_status_text_id is None or self.ring_canvas is None:
            self._avatar_status_blink_job = None
            return
        try:
            self._avatar_status_dot_count = (self._avatar_status_dot_count + 1) % 4
            dots = "." * self._avatar_status_dot_count
            label = "THINKING" if self._avatar_status_mode == "PROCESSING" else "LISTENING"
            self.ring_canvas.itemconfigure(self._avatar_status_text_id, text=f"{label}{dots}")
            self.ring_canvas.tag_raise(self._avatar_status_text_id)
        except Exception:
            pass
        self._avatar_status_blink_job = self.after(400, self._animate_avatar_status)

    def _animate_ring(self):
        """Animate the home HUD without rebuilding its canvas."""
        if getattr(self, "_shutting_down", False):
            self._ring_animation_job = None
            return
        try:
            if getattr(self, "_active_center_view", None) == "home" and self.ring_canvas is not None and self._ring_state:
                self._animation_phase = (self._animation_phase + 0.04) % (2 * math.pi)
                self._scanner_angle = (self._scanner_angle + 2.0) % 360
                state = self._ring_state
                cx, cy, base_r = state["cx"], state["cy"], state["base_r"]

                for cfg in self._ring_arc_config:
                    cfg["start"] = (cfg["start"] + cfg["direction"] * 1.15) % 360
                    self.ring_canvas.itemconfigure(cfg["id"], start=cfg["start"])

                ang = math.radians(self._scanner_angle)
                sx = cx + math.cos(ang) * (base_r + 75)
                sy = cy + math.sin(ang) * (base_r + 75)
                self.ring_canvas.coords(self._scanner_item, cx, cy, sx, sy)
                self.ring_canvas.coords(self._scanner_dot, sx - 4, sy - 4, sx + 4, sy + 4)

                pulse = (math.sin(self._animation_phase) + 1.0) * 0.5
                for idx, item in enumerate(self._glow_items):
                    factor = 0.95 + idx * 0.03 + pulse * 0.025
                    radius = base_r * factor
                    self.ring_canvas.coords(item, cx - radius, cy - radius, cx + radius, cy + radius)
                    self.ring_canvas.itemconfigure(item, width=1 if pulse < 0.58 else 2)

                for particle in self._ring_particles:
                    particle["angle"] = (particle["angle"] + particle["speed"]) % (2 * math.pi)
                    r = particle["radius"] + math.sin(self._animation_phase + particle["angle"] * 2) * 1.5
                    x = cx + math.cos(particle["angle"]) * r
                    y = cy + math.sin(particle["angle"]) * r
                    size = particle["size"]
                    self.ring_canvas.coords(particle["id"], x - size, y - size, x + size, y + size)
                    self.ring_canvas.itemconfigure(particle["id"], state="normal" if pulse > 0.15 else "hidden")
        except Exception:
            pass
        self._ring_animation_job = self.after(50, self._animate_ring)
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

    def _start_background_rotation(self):
        # Collect candidate images from assets folder, excluding the avatar
        try:
            candidates = []
            for p in ASSETS_DIR.iterdir():
                if not p.is_file():
                    continue
                if p.name.lower() == AVATAR_IMAGE.name.lower():
                    continue
                if p.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.bmp'):
                    continue
                candidates.append(p)
            # Sort for deterministic rotation order
            candidates.sort()
            self._bg_images = candidates
            self._bg_index = 0
        except Exception:
            self._bg_images = []
            self._bg_index = 0

        # Start rotation loop (10 minutes)
        def _rotate():
            try:
                if getattr(self, '_bg_images', None):
                    self._bg_index = (self._bg_index + 1) % len(self._bg_images)
                    path = self._bg_images[self._bg_index]
                    if Image is not None:
                        try:
                            self._background_image = Image.open(path)
                            self._background_photo = None
                            self._update_background()
                        except Exception:
                            pass
            finally:
                # schedule next rotation
                try:
                    self.after(600000, _rotate)
                except Exception:
                    pass

        # schedule first rotation in 10 minutes (do not change immediately on startup)
        try:
            self.after(600000, _rotate)
        except Exception:
            pass

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
        if self._command_in_progress:
            self._append_console("SYSTEM", "Angelique is still processing the previous request.")
            return
        self._command_in_progress = True
        self._append_console("USER", label)
        self._append_console("ANGELIQUE", "Processing your request...")
        self._set_avatar_status("PROCESSING")
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
        self._toggle_audio_mode()

    def _toggle_audio_mode(self):
        self._audio_enabled = not getattr(self, "_audio_enabled", False)
        try:
            self.mic_button.configure(text="🎙️" if self._audio_enabled else "⌨️")
            self._input_mode_label.configure(text="VOICE MODE" if self._audio_enabled else "TEXT MODE")
        except Exception:
            pass
        if self._audio_enabled:
            if self._listen is None:
                self._append_console("SYSTEM", "Voice interface is unavailable. Cannot start listening.")
                self._audio_enabled = False
                self.mic_button.configure(text="⌨️")
                self._input_mode_label.configure(text="TEXT MODE")
                return
            self._append_console("SYSTEM", "Voice assist activated. Listening continuously...")
            self._set_avatar_status("LISTENING")
            self.footer_label.configure(text=self._footer_text("LISTENING"))
            # Ensure speech engine is enabled for listening
            try:
                from skills.voice.voice_interface import set_speech_enabled
                set_speech_enabled(True)
            except Exception:
                pass
            self._start_voice_listener()
        else:
            self._append_console("SYSTEM", "Voice assist deactivated. Listening stopped.")
            self._set_avatar_status(None)
            self.footer_label.configure(text=self._footer_text("READY"))
            try:
                from skills.voice.voice_interface import set_speech_enabled
                set_speech_enabled(False)
            except Exception:
                pass
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
        if self._stop_listening is None:
            self._stop_listening = threading.Event()
        else:
            self._stop_listening = threading.Event()
        self._stop_listening.clear()
        self._voice_listener_thread = threading.Thread(target=self._voice_listener_loop, daemon=True)
        self._voice_listener_thread.start()

    def _stop_voice_listener(self):
        if getattr(self, "_stop_listening", None) is not None:
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
            if self._command_in_progress:
                self.after(0, lambda: self._append_console("SYSTEM", "Command queued. Angelique will process it after the current request."))
                self._queue_command(spoken)
                time.sleep(0.2)
                continue
            self.after(0, lambda: self.input_entry.delete(0, tk.END))
            self.after(0, lambda text=spoken: self.input_entry.insert(0, text))
            self.after(0, lambda: self._append_console("USER", spoken))
            self.after(0, lambda: self._append_console("ANGELIQUE", "Processing voice command..."))
            self.after(0, lambda: self._set_avatar_status("PROCESSING"))
            self.after(0, lambda: self.footer_label.configure(text=self._footer_text("PROCESSING")))
            self._command_in_progress = True
            self._process_command(spoken)
            time.sleep(0.2)
        self.after(0, lambda: self._set_avatar_status(None))
        self.after(0, lambda: self.footer_label.configure(text=self._footer_text("READY")))

    def _notify_user_whistle(self):
        # Try a GUI bell and play a whistle asset if present
        try:
            # GUI bell (cross-platform)
            try:
                self.bell()
            except Exception:
                pass
            whistle_path = ASSETS_DIR / "whistle.wav"
            # If missing, generate a short whistle WAV programmatically
            if not whistle_path.exists():
                try:
                    whistle_path.parent.mkdir(parents=True, exist_ok=True)
                    duration = 0.9
                    base_freq = 900.0
                    samplerate = 44100
                    amplitude = 16000
                    nframes = int(duration * samplerate)
                    with wave.open(str(whistle_path), 'w') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(samplerate)
                        for i in range(nframes):
                            t = i / samplerate
                            # simple upward chirp with fade-out
                            f = base_freq + 700.0 * (t / duration)
                            val = int(amplitude * math.sin(2 * math.pi * f * t) * (1 - t / duration))
                            wf.writeframes(struct.pack('<h', max(-32767, min(32767, val))))
                except Exception:
                    pass

            if whistle_path.exists():
                players = [
                    ["mpv", "--no-video", "--quiet", str(whistle_path)],
                    ["paplay", str(whistle_path)],
                    ["aplay", str(whistle_path)],
                ]
                for cmd in players:
                    try:
                        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                        break
                    except Exception:
                        continue
        except Exception:
            pass

    def show_trading_plan(self, plan_text: str):
        """Display a trading plan in the Trading Hub and notify the user if not focused."""
        try:
            self.trading_detail_var.set(plan_text)
            # If the GUI is not focused, notify with whistle/bell
            try:
                if not self.focus_displayof():
                    self._notify_user_whistle()
            except Exception:
                self._notify_user_whistle()
        except Exception:
            pass

    def _footer_text(self, status=None):
        status_text = status if status is not None else self._system_stats.get("status", "READY")
        detail = ""
        if status_text == "PROCESSING":
            detail = " • THINKING..."
        elif status_text == "LISTENING":
            detail = " • LISTENING..."
        elif status_text == "READY":
            detail = " • READY"
        return f"CPU {self._system_stats.get('cpu', 0)}%  |  MEMORY {self._system_stats.get('memory', 0)}%  |  NETWORK {self._system_stats.get('network_mbps', 0.0):.1f} Mbps  | STATUS: {status_text}{detail}"

    def _is_fast_command(self, text: str) -> bool:
        normalized = (text or "").strip().lower()
        if not normalized:
            return False
        prefixes = (
            "what time", "what's the time", "what is the time", "what is the date",
            "what's the date", "time and date", "look for", "look up a file",
            "find ", "search for a file", "locate ", "send ", "message ",
            "open the browser", "open browser", "open brave", "launch brave",
            "open firefox", "launch firefox", "list files", "list the files",
            "show running processes", "check system", "how many users are connected",
        )
        return normalized.startswith(prefixes)

    def _on_send(self, event=None):
        if getattr(self, "_input_placeholder_active", False):
            return
        text = self.input_entry.get().strip()
        if not text:
            return
        self.input_entry.delete(0, tk.END)
        if getattr(self, "_training_mode_enabled", False):
            text = f"[[TRAINING_MODE]] {text}"
        # Explicit deterministic commands can bypass a slow model request already
        # in progress. General reasoning requests remain serialized to keep the
        # conversational context ordered.
        if self._command_in_progress and not self._is_fast_command(text):
            self._queue_command(text)
            self._append_console("SYSTEM", "Command queued. Angelique will process it after the current request.")
            return
        self._command_in_progress = True
        self._append_console("USER", text)
        self._append_console("ANGELIQUE", "Command received. Processing locally in the desktop interface.")
        self._set_avatar_status("PROCESSING")
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
        # Terminal actions execute on their own worker and must not sit behind a
        # slow model request. Privileged auth is marshalled back to the Tk thread.
        self._append_console("TERMINAL", command)
        self.footer_label.configure(text=self._footer_text("PROCESSING"))
        self._command_in_progress = True
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

    def _queue_command(self, text: str) -> bool:
        if not text or not str(text).strip():
            return False
        pending = getattr(self, "_pending_command_queue", None)
        if pending is None:
            pending = deque()
            self._pending_command_queue = pending
        pending.append(str(text).strip())
        if not self._command_in_progress:
            self.after(0, self._process_next_queued_command)
        return True

    def _process_next_queued_command(self):
        if self._command_in_progress:
            return
        pending = getattr(self, "_pending_command_queue", None)
        if not pending:
            return
        text = pending.popleft()
        if not text or not str(text).strip():
            if pending:
                self.after(0, self._process_next_queued_command)
            return

        text = str(text).strip()
        self._command_in_progress = True
        self._append_console("USER", text)
        self._append_console("ANGELIQUE", "Command received. Processing locally in the desktop interface.")
        self._set_avatar_status("PROCESSING")
        self.footer_label.configure(text=self._footer_text("PROCESSING"))
        threading.Thread(target=self._process_command, args=(text,), daemon=True).start()

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

    def _confirm_privileged_command(self, command: str) -> bool:
        # Show a concise confirmation dialog for privileged actions.
        try:
            title = "Authorize privileged command"
            message = f"This action requires elevated privileges.\n\nCommand:\n{command}\n\nProceed?"
            return self._confirm_dialog(title, message, confirm_text="Yes", cancel_text="No")
        except Exception:
            return False

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
                confirm_callback=self._confirm_privileged_command,
                password_callback=self._prompt_for_sudo_password,
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
            self._command_in_progress = False
            self.after(0, lambda: self._set_avatar_status(None))
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
        if hasattr(self, "speech_toggle"):
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
                self.after(0, lambda e=str(exc): self._append_console("SYSTEM", f"Voice engine load failed: {e}"))
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

        # Start background rotation (assets) and other runtime decorators
        try:
            self._start_background_rotation()
        except Exception:
            pass

    def _toggle_voice_output(self):
        self._speak_enabled = not self._speak_enabled
        if hasattr(self, "speech_toggle"):
            label = "VOICE OUTPUT ON" if self._speak_enabled else "VOICE OUTPUT OFF"
            self.speech_toggle.configure(text=label)
        status = "enabled" if self._speak_enabled else "disabled"
        self._append_console("SYSTEM", f"Voice output {status}.")
        try:
            from skills.voice.voice_interface import set_speech_enabled
            set_speech_enabled(self._speak_enabled)
        except Exception:
            pass

    def _finish_response(self, response: str):
        if getattr(self, "_shutting_down", False):
            return
        self._append_console("ANGELIQUE", response)
        self._command_in_progress = False
        self._set_avatar_status(None)
        self.footer_label.configure(text=self._footer_text("READY"))
        self.after(0, self._process_next_queued_command)

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
        self._trading_monitor_running = False
        self._position_management_running = False
        self._trading_scan_stop_event.set()
        position_job = getattr(self, "_position_refresh_job", None)
        if position_job is not None:
            try:
                self.after_cancel(position_job)
            except Exception:
                pass
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
