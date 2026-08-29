"""Ubuntu desktop control: mouse, keyboard, clipboard, screenshots and windows."""
from __future__ import annotations
import os, shutil, subprocess
from pathlib import Path
from typing import Any


def _require_display() -> None:
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("No graphical session detected (DISPLAY/WAYLAND_DISPLAY is missing).")


def screenshot(path: str | None = None) -> str:
    _require_display()
    target = Path(path).expanduser() if path else Path.home()/"Pictures"/"angelique_screenshot.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        import pyautogui
        img = pyautogui.screenshot()
        img.save(target)
        return str(target)
    except Exception as exc:
        raise RuntimeError(f"Screenshot failed: {exc}") from exc


def mouse_move(x: int, y: int) -> str:
    _require_display()
    import pyautogui; pyautogui.moveTo(int(x), int(y), duration=0.08); return f"Moved mouse to ({x}, {y})."


def mouse_click(x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> str:
    _require_display(); import pyautogui
    if x is not None and y is not None: pyautogui.moveTo(int(x), int(y), duration=0.08)
    if button not in {"left","right","middle"}: raise ValueError("button must be left, right or middle")
    pyautogui.click(button=button, clicks=max(1,int(clicks)), interval=0.08); return "Mouse click sent."


def type_text(text: str, interval: float = 0.01) -> str:
    _require_display()
    import pyautogui
    value=str(text)
    try:
        if any(ord(ch)>127 for ch in value):
            clipboard_set(value); pyautogui.hotkey("ctrl","v")
        else:
            pyautogui.write(value, interval=max(0,float(interval)))
    except Exception:
        pyautogui.write(value, interval=max(0,float(interval)))
    return "Text typed."


def hotkey(keys: str) -> str:
    _require_display(); import pyautogui
    sequence=[k.strip() for k in str(keys).split("+") if k.strip()]
    if not sequence: raise ValueError("No keys supplied")
    pyautogui.hotkey(*sequence); return f"Hotkey sent: {'+'.join(sequence)}"


def key_press(key: str) -> str:
    _require_display(); import pyautogui; pyautogui.press(key); return f"Key pressed: {key}"


def clipboard_get() -> str:
    for cmd in (("wl-paste",), ("xclip","-selection","clipboard","-o"), ("xsel","--clipboard","--output")):
        if shutil.which(cmd[0]):
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=3)
            if p.returncode==0: return p.stdout
    try:
        import tkinter as tk
        root=tk.Tk(); root.withdraw(); text=root.clipboard_get(); root.destroy(); return text
    except Exception as exc: raise RuntimeError("No clipboard backend available") from exc


def clipboard_set(text: str) -> str:
    data=str(text)
    if shutil.which("wl-copy"):
        subprocess.run(["wl-copy"],input=data,text=True,check=True,timeout=3); return "Clipboard updated."
    if shutil.which("xclip"):
        subprocess.run(["xclip","-selection","clipboard"],input=data,text=True,check=True,timeout=3); return "Clipboard updated."
    if shutil.which("xsel"):
        subprocess.run(["xsel","--clipboard","--input"],input=data,text=True,check=True,timeout=3); return "Clipboard updated."
    raise RuntimeError("No clipboard backend available")


def active_window() -> dict[str, Any]:
    for cmd in (("xdotool","getactivewindow","getwindowname"),("hyprctl","activewindow","-j")):
        if shutil.which(cmd[0]):
            p=subprocess.run(cmd,capture_output=True,text=True,timeout=2)
            if p.returncode==0: return {"backend":cmd[0],"raw":p.stdout.strip()}
    return {"backend":None,"raw":None}
