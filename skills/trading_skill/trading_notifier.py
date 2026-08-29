from __future__ import annotations

import threading
from typing import Any, Callable


_lock = threading.Lock()
_seen: set[str] = set()


def _default_speaker(text: str) -> None:
    from skills.voice.voice_interface import speak
    speak(text)


def _event_key(plan: dict[str, Any], event_type: str) -> str:
    return f"{plan.get('opportunity_id') or plan.get('confirmation_phrase') or plan.get('mt5_symbol')}:{event_type}"


def _human_name(symbol: str) -> str:
    key = "".join(ch for ch in str(symbol or "").upper() if ch.isalnum())
    if key.startswith("XAU"):
        return "Gold"
    if key.startswith("XAG"):
        return "Silver"
    return str(symbol or "instrument").upper()


def notify(event_type: str, plan: dict[str, Any], *, speaker: Callable[[str], None] | None = None, reason: str = "") -> bool:
    key = _event_key(plan, event_type)
    with _lock:
        if key in _seen:
            return False
        _seen.add(key)
    symbol = _human_name(plan.get("mt5_symbol") or plan.get("symbol") or plan.get("requested_symbol"))
    direction = str(plan.get("direction") or "").lower()
    if event_type == "MANUAL_APPROVAL_REQUIRED":
        text = f"Angelique notification. {symbol} {direction} plan requires manual approval because of news. Review the Trading Hub."
    elif event_type == "TRADE_EXECUTED":
        text = f"Angelique notification. {symbol} {direction} trade executed. Risk one percent."
    elif event_type == "EXECUTION_VERIFICATION_PENDING":
        text = f"Angelique notification. {symbol} {direction} order was accepted, but execution verification is still pending."
    elif event_type == "TRADE_FAILED":
        text = f"Angelique notification. {symbol} {direction} trade was not executed. Review the Trading Hub."
    elif event_type == "POSITION_CLOSED":
        text = f"Angelique notification. {symbol} position has been closed."
    else:
        return False
    speaker = speaker or _default_speaker
    threading.Thread(target=lambda: _safe_speak(speaker, text), daemon=True).start()
    return True


def _safe_speak(speaker: Callable[[str], None], text: str) -> None:
    try:
        speaker(text)
    except Exception:
        pass
