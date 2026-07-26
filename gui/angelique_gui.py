# gui/angelique_gui.py
import customtkinter as ctk
import tkinter as tk
import math
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

        # Futuristic background accent color
        self.configure(bg="#031032")
        
        self.message_queue = queue.Queue()
        self.is_listening = False
        self.is_thinking = False
        self.current_theme = "dark-blue"
        self.uploaded_files = []
        
        self._create_widgets()
        # Try to load assets (background/profile) if present
        self._load_assets()
        self._check_queue()
        # Start subtle animations
        self._start_animations()
        
    def _create_widgets(self):
        # Sidebar
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        
        # Sidebar logo with neon canvas behind
        self.logo_canvas = tk.Canvas(self.sidebar, width=220, height=80, bg="#031032", highlightthickness=0)
        self.logo_canvas.grid(row=0, column=0, padx=20, pady=8)

        self.logo_label = ctk.CTkLabel(
            self.sidebar,
            text="ANGELIQUE",
            font=ctk.CTkFont(size=26, weight="bold"),
            text_color="#00ffd7"
        )
        # place label on top of canvas
        self.logo_label.place(in_=self.logo_canvas, relx=0.5, rely=0.5, anchor=tk.CENTER)
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
            bg="#071530",
            fg="#e8e8e8",
            font=("Consolas", 12),
            borderwidth=0,
            highlightthickness=0,
            padx=20,
            pady=20
        )
        self.chat_display.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.chat_display.config(state=tk.DISABLED)
        
        self.chat_display.tag_configure("user", foreground="#7be8ff", font=("Consolas", 12, "bold"))
        self.chat_display.tag_configure("angelique", foreground="#00ffcc", font=("Consolas", 12, "bold"))
        self.chat_display.tag_configure("system", foreground="#ffd27a", font=("Consolas", 11, "italic"))
        
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

    # subtle pulsing effect for a futuristic feel (affects title color)
    def _pulse_title(self, step=0):
        try:
            green = int(200 + 55 * (0.5 + 0.5 * __import__('math').sin(step / 10)))
            color = f"#00{green:02x}cc"
            self.logo_label.configure(text_color=color)
            self.after(80, lambda: self._pulse_title(step + 1))
        except Exception:
            pass

    def _animate_sidebar_glow(self, t=0):
        try:
            # Clear canvas and draw a soft radial glow behind the logo
            self.logo_canvas.delete("glow")
            w = int(self.logo_canvas.winfo_width() or 220)
            h = int(self.logo_canvas.winfo_height() or 80)
            cx = w // 2
            cy = h // 2
            max_r = max(w, h)
            # animate color
            intensity = int(120 + 60 * math.sin(t / 10))
            color = f"#{intensity:02x}{255:02x}{220:02x}"
            for i in range(6, 0, -1):
                r = int(max_r * (i / 6.0))
                alpha = int(8 * i)
                self.logo_canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="", tags=("glow",), stipple="gray12")
            self.after(120, lambda: self._animate_sidebar_glow(t + 1))
        except Exception:
            pass

    def _animate_chat_bg(self, t=0):
        try:
            # cycle dark blue shades
            shades = [(7,21,48), (5,18,44), (3,16,40), (6,20,46)]
            r,g,b = shades[t % len(shades)]
            color = f"#{r:02x}{g:02x}{b:02x}"
            self.chat_display.config(bg=color)
            self.after(800, lambda: self._animate_chat_bg(t + 1))
        except Exception:
            pass

    def _start_animations(self):
        self._pulse_title()
        self._animate_sidebar_glow()
        self._animate_chat_bg()

    def _load_assets(self):
        # Look for assets in project gui/assets/ or user config directory
        candidates = [
            os.path.join(os.getcwd(), 'gui', 'assets', 'female.png'),
            os.path.expanduser('~/.config/angelique/assets/female.png'),
        ]
        for path in candidates:
            try:
                if os.path.exists(path):
                    img = Image.open(path).convert('RGBA')
                    img = img.resize((160, 160), Image.LANCZOS)
                    self.logo_img = ImageTk.PhotoImage(img)
                    self.logo_label.configure(image=self.logo_img, text='')
                    break
            except Exception:
                continue
        
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
    # Only allow direct start when launched by the official supervisor `launcher.py`.
    if os.environ.get("ANGELIQUE_LAUNCHED") == "1":
        main()
    else:
        print("Please start Angelique via launcher.py. Run: python3 launcher.py")
