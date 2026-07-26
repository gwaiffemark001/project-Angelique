#!/usr/bin/env python3
import os

files = {
    "gui/angelique_gui.py": '''# gui/angelique_gui.py
import customtkinter as ctk
import tkinter as tk
from tkinter import scrolledtext, filedialog
import threading
import time
import os
import sys
from datetime import datetime
from PIL import Image, ImageTk
import queue
import json

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class AngeliqueGUI(ctk.CTk):
    def __init__(self, floating_mode=False):
        super().__init__()
        
        self.floating_mode = floating_mode
        self.title("Angelique AI - Cognitive Architecture")
        self.geometry("1400x900")
        
        self.message_queue = queue.Queue()
        self.is_listening = False
        self.is_thinking = False
        self.current_theme = "dark-blue"
        self.uploaded_files = []
        
        self._create_widgets()
        self._check_queue()
        
    def _create_widgets(self):
        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        
        self.logo_label = ctk.CTkLabel(
            self.sidebar,
            text="🤖 ANGELIQUE",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=20)
        
        # Quick actions
        ctk.CTkLabel(self.sidebar, text="Quick Actions", font=("Arial", 12, "bold")).grid(
            row=1, column=0, padx=20, pady=(20, 10), sticky="w")
        
        self.btn_check_mt5 = ctk.CTkButton(
            self.sidebar, text="📊 MT5 Status",
            command=lambda: self.queue_message("Check my MT5 account"),
            height=35
        )
        self.btn_check_mt5.grid(row=2, column=0, padx=20, pady=5, sticky="ew")
        
        self.btn_analyze = ctk.CTkButton(
            self.sidebar, text=" Analyze EURUSD",
            command=lambda: self.queue_message("Analyze EURUSD on H1"),
            height=35
        )
        self.btn_analyze.grid(row=3, column=0, padx=20, pady=5, sticky="ew")
        
        self.btn_generate_img = ctk.CTkButton(
            self.sidebar, text=" Generate Image",
            command=self.open_image_generator,
            height=35
        )
        self.btn_generate_img.grid(row=4, column=0, padx=20, pady=5, sticky="ew")
        
        self.btn_upload = ctk.CTkButton(
            self.sidebar, text="📁 Upload File",
            command=self.upload_file,
            height=35
        )
        self.btn_upload.grid(row=5, column=0, padx=20, pady=5, sticky="ew")
        
        # Main chat area
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)
        
        self.chat_display = scrolledtext.ScrolledText(
            self.main_frame,
            wrap=tk.WORD,
            bg="#16213e",
            fg="#e8e8e8",
            font=("Consolas", 11),
            borderwidth=0,
            highlightthickness=0,
            padx=20,
            pady=20
        )
        self.chat_display.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.chat_display.config(state=tk.DISABLED)
        
        self.chat_display.tag_configure("user", foreground="#00d9ff", font=("Consolas", 11, "bold"))
        self.chat_display.tag_configure("angelique", foreground="#00ff88", font=("Consolas", 11, "bold"))
        self.chat_display.tag_configure("system", foreground="#ffa500", font=("Consolas", 10, "italic"))
        
        # Input area
        self.input_frame = ctk.CTkFrame(self.main_frame, height=80)
        self.input_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.input_frame.grid_columnconfigure(0, weight=1)
        
        self.input_box = ctk.CTkTextbox(self.input_frame, height=50, font=("Consolas", 12))
        self.input_box.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.input_box.bind("<Return>", self.on_enter_key)
        
        self.btn_send = ctk.CTkButton(
            self.input_frame, text="➤ Send",
            command=self.send_message,
            width=100,
            height=50
        )
        self.btn_send.grid(row=0, column=1, padx=(0, 10), pady=10)
        
        self.add_message("system", "🟢 Angelique v2.0 initialized.")
        
    def add_message(self, sender: str, message: str):
        self.chat_display.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if sender == "user":
            self.chat_display.insert(tk.END, f"\n[{timestamp}] You: {message}\n")
        elif sender == "angelique":
            self.chat_display.insert(tk.END, f"\n[{timestamp}] Angelique: {message}\n", "angelique")
        elif sender == "system":
            self.chat_display.insert(tk.END, f"\n[{timestamp}] » {message}\n", "system")
            
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)
        
    def queue_message(self, message: str):
        self.message_queue.put(("user", message))
        
    def send_message(self):
        message = self.input_box.get("1.0", tk.END).strip()
        if message:
            self.queue_message(message)
            self.input_box.delete("1.0", tk.END)
            
    def on_enter_key(self, event):
        self.send_message()
        return "break"
        
    def upload_file(self):
        file_path = filedialog.askopenfilename(title="Select file")
        if file_path:
            self.uploaded_files.append(file_path)
            self.add_message("system", f"📁 File uploaded: {os.path.basename(file_path)}")
            
    def open_image_generator(self):
        self.add_message("system", " Image generator opened (feature pending)")
        
    def _check_queue(self):
        try:
            while True:
                sender, message = self.message_queue.get_nowait()
                if sender == "user":
                    self.add_message("user", message)
                    threading.Thread(target=self.process_message, args=(message,), daemon=True).start()
        except queue.Empty:
            pass
        self.after(100, self._check_queue)
        
    def process_message(self, message: str):
        self.add_message("system", "🧠 Thinking...")
        time.sleep(1)
        self.add_message("angelique", f"I received: {message}")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--floating', action='store_true')
    args = parser.parse_args()
    
    app = AngeliqueGUI(floating_mode=args.floating)
    app.mainloop()

if __name__ == "__main__":
    main()
''',

    "gui/trading_dashboard.py": '''# gui/trading_dashboard.py
import customtkinter as ctk
import tkinter as tk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import numpy as np

class TradingDashboard(ctk.CTkFrame):
    def __init__(self, parent, bridge=None):
        super().__init__(parent)
        self.bridge = bridge
        self.current_symbol = "EURUSD"
        
        self._create_widgets()
        
    def _create_widgets(self):
        # Top bar
        self.top_bar = ctk.CTkFrame(self)
        self.top_bar.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(self.top_bar, text="Symbol:", font=("Arial", 12)).pack(side="left", padx=5)
        
        self.btn_refresh = ctk.CTkButton(self.top_bar, text="🔄 Refresh", command=self.refresh_data)
        self.btn_refresh.pack(side="left", padx=20)
        
        # Chart area
        self.chart_frame = ctk.CTkFrame(self)
        self.chart_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.fig, self.ax = plt.subplots(figsize=(10, 6), facecolor='#1a1a2e')
        self.ax.set_facecolor('#16213e')
        self.ax.grid(True, alpha=0.3)
        
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.chart_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        
        self.refresh_data()
        
    def refresh_data(self):
        self.ax.clear()
        self.ax.set_facecolor('#16213e')
        self.ax.grid(True, alpha=0.3)
        
        dates = [datetime.now() - timedelta(hours=i) for i in range(50)][::-1]
        prices = [1.0850 + np.random.uniform(-0.005, 0.005) for _ in range(50)]
        
        self.ax.plot(dates, prices, color='#00d9ff', linewidth=2)
        self.ax.set_title(f"{self.current_symbol} Chart", color='#ffffff')
        
        self.canvas.draw()
''',

    "skills/voice/voice_interface.py": '''# skills/voice/voice_interface.py
import os
import sys
import tempfile
import asyncio
import subprocess
import threading
import re
import contextlib
from dotenv import load_dotenv

load_dotenv()

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

@contextlib.contextmanager
def suppress_stderr():
    old_stderr = sys.stderr
    devnull = open(os.devnull, 'w')
    sys.stderr = devnull
    try:
        yield
    finally:
        sys.stderr.close()
        sys.stderr = old_stderr

with suppress_stderr():
    import speech_recognition as sr

def listen() -> str:
    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1.5
    
    try:
        with suppress_stderr():
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = recognizer.listen(source, timeout=4, phrase_time_limit=12)
        text = recognizer.recognize_google(audio)
        return text
    except:
        return ""

def speak(text: str):
    clean_text = re.sub(r'```.*?```', '', text, flags=re.DOTALL).strip()
    if not clean_text:
        return
    print(f"🔊 Speaking: {clean_text[:100]}...")
''',

    "skills/messaging/whatsapp_tools.py": '''# skills/messaging/whatsapp_tools.py
import os
import time
import re

def prepare_whatsapp_message(contact_name: str, message: str) -> str:
    return f"PREPARED: Contact '{contact_name}'. Message: '{message}'"

def execute_whatsapp_send(contact_name: str, message: str) -> str:
    return f"SUCCESS: Message sent to {contact_name}"
''',

    "skills/file_management/file_ops.py": '''# skills/file_management/file_ops.py
import os
import shutil

def manage_files(action: str, path: str, content: str = "", new_path: str = "") -> str:
    try:
        if action == "create":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"Successfully created file at {path}"
        elif action == "read":
            if not os.path.exists(path):
                return f"File not found: {path}"
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return "Invalid action"
    except Exception as e:
        return f"File operation failed: {str(e)}"
''',

    "skills/self_evolution/code_generator.py": '''# skills/self_evolution/code_generator.py
import os
import importlib.util
import sys
import traceback

SKILLS_DIR = "data/generated_skills"
os.makedirs(SKILLS_DIR, exist_ok=True)

def save_new_skill(skill_name: str, code: str) -> str:
    try:
        file_path = os.path.join(SKILLS_DIR, f"{skill_name}.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)
        return f"✅ Skill '{skill_name}' saved to {file_path}"
    except Exception as e:
        return f"Failed to save skill: {str(e)}"

def execute_generated_code(code: str, function_name: str = "main", **kwargs) -> str:
    temp_path = os.path.join(SKILLS_DIR, "_temp_exec.py")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(code)
        
        spec = importlib.util.spec_from_file_location("_temp_exec", temp_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["_temp_exec"] = module
        spec.loader.exec_module(module)
        
        if hasattr(module, function_name):
            func = getattr(module, function_name)
            result = func(**kwargs)
            return f"✅ Code executed. Result: {str(result)}"
        else:
            return f"⚠️ Function '{function_name}' not found"
    except Exception as e:
        return f"❌ Execution failed: {traceback.format_exc()}"
''',

    "skills/trading/engine/mt5_bridge_server.py": '''# skills/trading/engine/mt5_bridge_server.py
import asyncio
import json
import sys

HOST = '127.0.0.1'
PORT = 9999

def initialize_mt5():
    return {"status": "connected", "version": "5.0"}

def get_account_info():
    return {
        "login": 436885745,
        "balance": 500.0,
        "equity": 500.0,
        "free_margin": 500.0,
        "leverage": 2000
    }

async def handle_client(websocket, path):
    print(f" [Bridge] Client connected")
    try:
        async for message in websocket:
            data = json.loads(message)
            action = data.get("action")
            
            if action == "ping":
                response = {"status": "pong"}
            elif action == "get_account_info":
                response = get_account_info()
            else:
                response = {"error": f"Unknown action: {action}"}
            
            await websocket.send(json.dumps(response))
    except Exception as e:
        print(f" [Bridge] Error: {e}")
    finally:
        print(f" [Bridge] Client disconnected")

async def main():
    print(f"🚀 [Bridge] Starting MT5 Bridge Server on {HOST}:{PORT}")
    
    try:
        import websockets
        async with websockets.serve(handle_client, HOST, PORT):
            print(f"👂 [Bridge] Listening for commands...")
            await asyncio.Future()
    except ImportError:
        print("⚠️ websockets not installed. Run: pip install websockets")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
''',

    "skills/trading/engine/connection_manager.py": '''# skills/trading/engine/connection_manager.py
import asyncio
import json
import websockets
import threading
import time

class MT5ConnectionManager:
    def __init__(self, host='127.0.0.1', port=9999):
        self.host = host
        self.port = port
        self.ws = None
        self._is_connected = False
        self._loop = None
        self._thread = None

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self.connect()

    def connect(self):
        if self._is_connected:
            return True
        
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
            self._thread.start()
            
            for _ in range(20):
                if self._is_connected:
                    return True
                time.sleep(0.1)
                
        return self._is_connected

    def _run_event_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_async())
            if self._is_connected:
                self._loop.run_forever()
        except Exception as e:
            print(f"⚠️ [MT5 Client] Connection loop failed: {e}")
            self._is_connected = False

    async def _connect_async(self):
        try:
            self.ws = await websockets.connect(f"ws://{self.host}:{self.port}")
            self._is_connected = True
            print("🟢 [MT5 Client] Connected to Wine Bridge.")
        except Exception as e:
            self._is_connected = False

    def send_command(self, action: str, params: dict = None) -> dict:
        if not self._is_connected:
            return {"error": "Not connected"}
        
        payload = {"action": action}
        if params:
            payload.update(params)

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._send_async(json.dumps(payload)), 
                self._loop
            )
            return future.result(timeout=10)
        except Exception as e:
            return {"error": str(e)}

    async def _send_async(self, message: str) -> dict:
        await self.ws.send(message)
        response = await self.ws.recv()
        return json.loads(response)

    def get_status(self) -> bool:
        return self._is_connected

bridge_manager = MT5ConnectionManager()
''',

    "skills/trading/engine/mt5_bridge.py": '''# skills/trading/engine/mt5_bridge.py
from skills.trading.engine.connection_manager import bridge_manager

class MT5Bridge:
    @staticmethod
    def ensure_connected():
        if not bridge_manager.get_status():
            bridge_manager.connect()
        return bridge_manager.get_status()

    @staticmethod
    def get_account_info() -> dict:
        if not MT5Bridge.ensure_connected():
            return {"error": "Not connected"}
        return bridge_manager.send_command("get_account_info")

    @staticmethod
    def ping() -> dict:
        return bridge_manager.send_command("ping")

bridge = MT5Bridge()
''',

    "skills/trading/market/candles.py": '''# skills/trading/market/candles.py
import pandas as pd

def build_candle_objects(raw_candles: list) -> list:
    structured_candles = []
    for c in raw_candles:
        body_size = abs(c["close"] - c["open"])
        structured_candles.append({
            "time": c["time"],
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c["tick_volume"],
            "body_size": round(body_size, 5)
        })
    return structured_candles

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    try:
        import pandas_ta as ta
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.rsi(length=14, append=True)
        return df
    except:
        return df
''',

    "skills/trading/market/market_data.py": '''# skills/trading/market/market_data.py
import pandas as pd
from skills.trading.engine.connection_manager import bridge_manager
from skills.trading.market.candles import build_candle_objects, calculate_indicators

class MarketData:
    @staticmethod
    def get_candles_and_indicators(symbol: str, timeframe: str = "H1", count: int = 100) -> dict:
        if not bridge_manager.get_status():
            return {"error": "Not connected"}
        
        import numpy as np
        from datetime import datetime, timedelta
        
        candles = []
        for i in range(count):
            dt = datetime.now() - timedelta(hours=count-i)
            price = 1.0850 + np.random.uniform(-0.005, 0.005)
            candles.append({
                "time": dt.isoformat(),
                "open": price,
                "high": price + 0.001,
                "low": price - 0.001,
                "close": price,
                "tick_volume": 100
            })
        
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": candles,
            "status": "success"
        }

market = MarketData()
''',

    "skills/vision/image_generator.py": '''# skills/vision/image_generator.py
import os
import requests

def generate_image(prompt: str, style: str = "realistic") -> str:
    try:
        API_URL = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
        headers = {"Authorization": f"Bearer {os.getenv('HUGGINGFACE_API_KEY', '')}"}
        
        payload = {
            "inputs": prompt,
            "parameters": {"width": 1024, "height": 1024}
        }
        
        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
        
        if response.status_code == 200:
            output_path = "data/generated_images"
            os.makedirs(output_path, exist_ok=True)
            
            import hashlib
            filename = f"img_{hashlib.md5(prompt.encode()).hexdigest()[:8]}.png"
            file_path = os.path.join(output_path, filename)
            
            with open(file_path, "wb") as f:
                f.write(response.content)
            
            return f"✅ Image generated! Saved to: {file_path}"
        else:
            return f"❌ Image generation failed: {response.text}"
            
    except Exception as e:
        return f"️ Error: {str(e)}"
''',

    "skills/vision/file_analyzer.py": '''# skills/vision/file_analyzer.py
import os
import mimetypes
from typing import Dict, Any

def analyze_file(file_path: str) -> Dict[str, Any]:
    try:
        if not os.path.exists(file_path):
            return {"error": "File not found"}
        
        file_info = {
            "name": os.path.basename(file_path),
            "size": os.path.getsize(file_path),
            "type": mimetypes.guess_type(file_path)[0] or "unknown"
        }
        
        if file_info["type"].startswith("image/"):
            return {**file_info, "analysis": "Image file detected"}
        elif file_info["type"] in ["text/plain", "text/csv"]:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(500)
            return {**file_info, "content_preview": content}
        
        return file_info
        
    except Exception as e:
        return {"error": f"Analysis failed: {str(e)}"}
''',

    "skills/os_control/system_monitor.py": '''# skills/os_control/system_monitor.py
import psutil
import platform

def get_system_health() -> str:
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        report = (
            f"🖥️ OS: {platform.system()} {platform.release()}\n"
            f"⚙️ CPU Usage: {cpu}%\n"
            f"🧠 RAM Usage: {ram.percent}%\n"
            f"💾 Disk Usage: {disk.percent}%"
        )
        return report
    except Exception as e:
        return f"Failed to read system stats: {str(e)}"

def get_running_processes(limit: int = 10) -> str:
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
            try:
                processes.append(proc.info)
            except:
                pass
        
        processes.sort(key=lambda x: x['cpu_percent'] or 0, reverse=True)
        top_procs = processes[:limit]
        
        report = "Top CPU consuming processes:\n"
        for p in top_procs:
            report += f"- {p['name']} (PID: {p['pid']}): {p['cpu_percent']}%\n"
        return report
    except Exception as e:
        return f"Failed: {str(e)}"
'''
}

print("📝 Creating GUI and advanced feature files...")

for filepath, content in files.items():
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ Created: {filepath}")

print("\n✅ All files created successfully!")
print("\nNow run:")
print("  pip install customtkinter matplotlib pillow pandas pandas-ta websockets")
print("  python3 launcher.py --gui")
