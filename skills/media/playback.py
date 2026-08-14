import time
import webbrowser
import urllib.parse
import shutil
import subprocess
from typing import Optional

try:
    from skills.os_control.app_discovery import open_app
except Exception:
    def open_app(name: str):
        return f"open_app fallback: would open {name}"


def _playerctl_available() -> bool:
    return shutil.which("playerctl") is not None


def _playerctl_play_for_spotify() -> bool:
    """Attempt to send a play command to the Spotify MPRIS player via playerctl."""
    try:
        if _playerctl_available():
            # Prefer targeting the spotify desktop player if present
            subprocess.run(["playerctl", "-p", "spotify", "play"], check=False)
            return True
    except Exception:
        pass
    return False


def play_media(app_name: Optional[str] = None, service: Optional[str] = None, query: Optional[str] = None) -> str:
    """Play media using best-effort native app control and browser fallbacks.

    Behavior:
    - Spotify: try to open native app, open a Spotify search in the browser, then call `playerctl play` if available.
    - YouTube or generic: open a YouTube search in the browser.
    """
    svc = (service or app_name or "").lower()
    q = (query or "").strip()
    try:
        if 'spotify' in svc or (app_name and 'spotify' in app_name.lower()):
            # 1) Try to open native Spotify app
            try:
                open_app('spotify')
            except Exception:
                pass
            # Allow the app a moment to start
            time.sleep(1)

            # 2) Open Spotify web search as a fallback / helper
            if q:
                url = f"https://open.spotify.com/search/{urllib.parse.quote(q)}"
                webbrowser.open(url)

            # 3) Try to nudge the native player to play via playerctl (MPRIS)
            playerctl_ok = _playerctl_play_for_spotify()
            if q:
                return f"Opened Spotify and searched for '{q}'. Playerctl applied: {playerctl_ok}."
            return f"Opened Spotify. Playerctl applied: {playerctl_ok}."

        # Default to YouTube search in browser
        if q:
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}"
            webbrowser.open(url)
            return f"Opened YouTube search for '{q}'."
        return "No query provided for playback."
    except Exception as e:
        return f"Playback failed: {e}"
