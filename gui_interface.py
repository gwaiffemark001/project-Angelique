# gui_interface.py
import customtkinter as ctk
import tkinter as tk
from tkinter import scrolledtext
import threading
import time
import os
import sys
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import queue

# Set theme and appearance
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class AngeliqueGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Window configuration
        self.title("Angelique AI - Cognitive Architecture")
        self.geometry("1200x800")
        self.minsize(1000, 700)
        
        # Message queue for thread-safe updates
        self.message_queue = queue.Queue()
        
        # State variables
        self.is_listening = False
        self.is_thinking = False
        self.is_speaking = False
        self.mt5_connected = False
        
        # Configure grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self._create_widgets()
        self._check_queue()
        
    def _create_widgets(self):
        # === LEFT SIDEBAR ===
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.sidebar.grid_rowconfigure(4, weight=1)
        
        # Logo/Title
        self.logo_label = ctk.CTkLabel(
            self.sidebar, 
            text="🤖 ANGELIQUE",
            font=ctk.CTkFont(size=28, weight="bold")
        )
        self.logo_label.grid(row=0, column=0, padx=20, pady=20)
        
        # Status indicators
        self.status_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.status_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        
        # MT5 Status
        self.mt5_status_label = ctk.CTkLabel(
            self.status_frame,
            text="🔴 MT5: Disconnected",
            font=ctk.CTkFont(size=12)
        )
        self.mt5_status_label.pack(anchor="w", pady=5)
        
        # Voice Status
        self.voice_status_label = ctk.CTkLabel(
            self.status_frame,
            text=" Voice: Ready",
            font=ctk.CTkFont(size=12)
        )
        self.voice_status_label.pack(anchor="w", pady=5)
        
        # System Status
        self.system_status_label = ctk.CTkLabel(
            self.status_frame,
            text=" System: Online",
            font=ctk.CTkFont(size=12)
        )
        self.system_status_label.pack(anchor="w", pady=5)
        
        # Visual AI Indicator (Animated Circle)
        self.ai_indicator_canvas = tk.Canvas(
            self.sidebar, 
            width=200, 
            height=200, 
            bg="#1a1a2e', 
            highlightthickness=0
        )
        self.ai_indicator_canvas.grid(row=2, column=0, padx=20, pady=20)
        self._draw_ai_indicator()
        
        # Quick Actions
        self.actions_label = ctk.CTkLabel(
            self.sidebar,
            text="QUICK ACTIONS",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.actions_label.grid(row=3, column=0, padx=20, pady=(20, 10), sticky="w")
        
        # Action buttons
        self.btn_check_mt5 = ctk.CTkButton(
            self.sidebar,
            text="📊 Check MT5",
            command=lambda: self._queue_message("Check my MT5 account balance"),
            height=35
        )
        self.btn_check_mt5.grid(row=4, column=0, padx=20, pady=5, sticky="ew")
        
        self.btn_analyze_eurusd = ctk.CTkButton(
            self.sidebar,
            text="📈 Analyze EURUSD",
            command=lambda: self._queue_message("Analyze EURUSD on H1 timeframe"),
            height=35
        )
        self.btn_analyze_eurusd.grid(row=5, column=0, padx=20, pady=5, sticky="ew")
        
        self.btn_read_screen = ctk.CTkButton(
            self.sidebar,
            text="️ Read Screen",
            command=lambda: self._queue_message("Read my screen"),
            height=35
        )
        self.btn_read_screen.grid(row=6, column=0, padx=20, pady=5, sticky="ew")
        
        # === MAIN CHAT AREA ===
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.main_frame.grid_rowconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(0, weight=1)
        
        # Chat display
        self.chat_display = scrolledtext.ScrolledText(
            self.main_frame,
            wrap=tk.WORD,
            bg="#16213e',
            fg="#e8e8e8',
            font=("Consolas", 11),
            borderwidth=0,
            highlightthickness=0,
            padx=20,
            pady=20
        )
        self.chat_display.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.chat_display.config(state=tk.DISABLED)
        
        # Configure text tags for different message types
        self.chat_display.tag_configure("user", foreground="#00d9ff', font=("Consolas", 11, "bold"))
        self.chat_display.tag_configure("angelique", foreground="#00ff88', font=("Consolas", 11, "bold"))
        self.chat_display.tag_configure("system", foreground="#ffa500', font=("Consolas", 10, "italic"))
        self.chat_display.tag_configure("timestamp", foreground="#666666', font=("Consolas", 9))
        
        # === INPUT AREA ===
        self.input_frame = ctk.CTkFrame(self.main_frame, height=80)
        self.input_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.input_frame.grid_columnconfigure(0, weight=1)
        
        # Text input
        self.input_box = ctk.CTkTextbox(
            self.input_frame,
            height=50,
            font=("Consolas", 12)
        )
        self.input_box.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.input_box.bind("<Return>", self._on_enter_key)
        self.input_box.bind("<Shift-Return>", lambda e: self.input_box.insert("end", "\n"))
        
        # Send button
        self.btn_send = ctk.CTkButton(
            self.input_frame,
            text="➤ Send",
            command=self._send_message,
            width=100,
            height=50
        )
        self.btn_send.grid(row=0, column=1, padx=(0, 10), pady=10)
        
        # Voice toggle button
        self.btn_voice = ctk.CTkButton(
            self.input_frame,
            text="🎤 Voice ON",
            command=self._toggle_voice,
            width=120,
            height=50,
            fg_color="#2ecc71"
        )
        self.btn_voice.grid(row=0, column=2, padx=(0, 10), pady=10)
        
        # === STATUS BAR ===
        self.status_bar = ctk.CTkFrame(self, height=30, corner_radius=0)
        self.status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.status_bar.grid_columnconfigure(0, weight=1)
        
        self.status_label = ctk.CTkLabel(
            self.status_bar,
            text="Ready | Press Enter to send, Shift+Enter for new line",
            font=ctk.CTkFont(size=11)
        )
        self.status_label.grid(row=0, column=0, padx=10, sticky="w")
        
        # Welcome message
        self._add_message("system", " Angelique v2.0 initialized. Cognitive Architecture Online.")
        self._add_message("system", "🎤 Voice mode is active. I'm ready to assist you.")
        
    def _draw_ai_indicator(self):
        """Draw animated AI indicator circle"""
        self.ai_indicator_canvas.delete("all")
        
        # Outer ring
        self.ai_indicator_canvas.create_oval(
            20, 20, 180, 180,
            outline="#00d9ff',
            width=3
        )
        
        # Inner pulsing circle
        if self.is_thinking:
            self.ai_indicator_canvas.create_oval(
                50, 50, 150, 150,
                fill="#00d9ff',
                stipple="gray25"
            )
        elif self.is_listening:
            self.ai_indicator_canvas.create_oval(
                60, 60, 140, 140,
                fill="#00ff88',
                stipple="gray25"
            )
        elif self.is_speaking:
            self.ai_indicator_canvas.create_oval(
                70, 70, 130, 130,
                fill="#ffa500',
                stipple="gray25"
            )
        else:
            # Idle state - breathing animation
            self.ai_indicator_canvas.create_oval(
                80, 80, 120, 120,
                fill="#00d9ff',
                stipple="gray25"
            )
        
        # Center text
        self.ai_indicator_canvas.create_text(
            100, 100,
            text="AI",
            font=("Arial", 20, "bold"),
            fill="#ffffff"
        )
        
    def _add_message(self, sender: str, message: str):
        """Add message to chat display"""
        self.chat_display.config(state=tk.NORMAL)
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if sender == "user":
            self.chat_display.insert(tk.END, f"\n[{timestamp}] ", "timestamp")
            self.chat_display.insert(tk.END, "You: ", "user")
            self.chat_display.insert(tk.END, f"{message}\n")
        elif sender == "angelique":
            self.chat_display.insert(tk.END, f"\n[{timestamp}] ", "timestamp")
            self.chat_display.insert(tk.END, "Angelique: ", "angelique")
            self.chat_display.insert(tk.END, f"{message}\n")
        elif sender == "system":
            self.chat_display.insert(tk.END, f"\n[{timestamp}] ", "timestamp")
            self.chat_display.insert(tk.END, f"» {message}\n", "system")
        
        self.chat_display.config(state=tk.DISABLED)
        self.chat_display.see(tk.END)
        
    def _queue_message(self, message: str):
        """Queue message for processing"""
        self.message_queue.put(("user", message))
        
    def _send_message(self):
        """Send message from input box"""
        message = self.input_box.get("1.0", tk.END).strip()
        if message:
            self._queue_message(message)
            self.input_box.delete("1.0", tk.END)
            
    def _on_enter_key(self, event):
        """Handle Enter key press"""
        if not event.state & 0x1:  # If Shift is not pressed
            self._send_message()
            return "break"
            
    def _toggle_voice(self):
        """Toggle voice mode"""
        # This will be connected to the actual voice interface
        self._add_message("system", " Voice mode toggled (integration pending)")
        
    def update_mt5_status(self, connected: bool):
        """Update MT5 connection status"""
        self.mt5_connected = connected
        if connected:
            self.mt5_status_label.configure(text="🟢 MT5: Connected", text_color="#00ff88")
        else:
            self.mt5_status_label.configure(text="🔴 MT5: Disconnected", text_color="#ff4444")
            
    def set_listening(self, listening: bool):
        """Set listening state"""
        self.is_listening = listening
        if listening:
            self.voice_status_label.configure(text="🎤 Voice: Listening...", text_color="#00ff88")
            self.btn_voice.configure(text=" Listening...", fg_color="#e74c3c")
        else:
            self.voice_status_label.configure(text="🎤 Voice: Ready", text_color="#ffffff")
            self.btn_voice.configure(text="🎤 Voice ON", fg_color="#2ecc71")
        self._draw_ai_indicator()
        
    def set_thinking(self, thinking: bool):
        """Set thinking state"""
        self.is_thinking = thinking
        if thinking:
            self.status_label.configure(text="🧠 Angelique is thinking...")
        else:
            self.status_label.configure(text="Ready | Press Enter to send, Shift+Enter for new line")
        self._draw_ai_indicator()
        
    def set_speaking(self, speaking: bool):
        """Set speaking state"""
        self.is_speaking = speaking
        if speaking:
            self.status_label.configure(text="🔊 Angelique is speaking...")
        self._draw_ai_indicator()
        
    def _check_queue(self):
        """Check message queue and process messages"""
        try:
            while True:
                sender, message = self.message_queue.get_nowait()
                if sender == "user":
                    self._add_message("user", message)
                    # Here you would integrate with the actual cognitive loop
                    threading.Thread(target=self._process_message, args=(message,), daemon=True).start()
        except queue.Empty:
            pass
        
        self.after(100, self._check_queue)
        
    def _process_message(self, message: str):
        """Process message through cognitive loop (placeholder)"""
        self.set_thinking(True)
        
        # Simulate processing delay
        time.sleep(1)
        
        # This is where you'd call: response = run_cognitive_loop(message)
        # For now, simulate a response
        response = f"I received your message: '{message}'. Integration with cognitive loop pending."
        
        self.set_thinking(False)
        self.set_speaking(True)
        self._add_message("angelique", response)
        time.sleep(2)  # Simulate speaking time
        self.set_speaking(False)

def main():
    app = AngeliqueGUI()
    app.mainloop()

if __name__ == "__main__":
    main()