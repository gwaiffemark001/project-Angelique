# gui/trading_dashboard.py
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
