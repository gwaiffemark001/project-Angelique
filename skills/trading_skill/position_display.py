from __future__ import annotations

from typing import Any


def pip_size(symbol: str) -> float:
    normalized = str(symbol or "").upper()
    if "JPY" in normalized:
        return 0.01
    if "XAU" in normalized or "GOLD" in normalized:
        return 0.1
    return 0.0001


def _price(position: dict[str, Any], market: dict[str, Any]) -> float:
    direction = str(position.get("type", position.get("direction", "BUY"))).upper()
    latest = market.get("latest_candle", {}) or {}
    fallback = latest.get("close", position.get("current_price", 0))
    if direction == "BUY":
        return float(market.get("bid", fallback) or 0)
    return float(market.get("ask", fallback) or 0)


def format_position_row(position: dict[str, Any], market: dict[str, Any] | None = None) -> dict[str, Any]:
    market = market or {}
    symbol = str(position.get("symbol", ""))
    direction = str(position.get("type", position.get("direction", "BUY"))).upper()
    current = _price(position, market)
    entry = float(position.get("price_open", position.get("entry", position.get("open_price", 0))) or 0)
    stop = float(position.get("sl", position.get("stop_loss", 0)) or 0)
    target = float(position.get("tp", position.get("take_profit", 0)) or 0)
    unit = pip_size(symbol)
    favorable = current - entry if direction == "BUY" else entry - current
    risk_distance = abs(entry - stop)
    to_stop = round(abs(current - stop) / unit, 2) if stop else None
    to_target = round(abs(target - current) / unit, 2) if target else None
    total_stop = round(risk_distance / unit, 2) if stop else None
    total_target = round(abs(target - entry) / unit, 2) if target else None
    status = "PROFIT" if favorable > 0 else "LOSS" if favorable < 0 else "AT ENTRY"
    return {
        "ticket": position.get("ticket", "-"),
        "symbol": symbol or "-",
        "direction": direction,
        "current": current,
        "entry": entry,
        "to_stop_pips": to_stop,
        "to_target_pips": to_target,
        "total_stop_pips": total_stop,
        "total_target_pips": total_target,
        "profit": float(position.get("profit", 0) or 0),
        "expected_profit": (
            float(position["expected_profit"])
            if position.get("expected_profit") is not None
            else None
        ),
        "r_multiple": round(favorable / risk_distance, 4) if risk_distance else None,
        "status": status,
        "spread_pips": float(market.get("spread_pips", 0) or 0) if market.get("spread_pips") is not None else None,
    }