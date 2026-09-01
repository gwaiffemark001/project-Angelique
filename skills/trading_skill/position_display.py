from __future__ import annotations

from typing import Any

from core.price_units import instrument_class, pip_size_from_specs, tick_size_from_specs


def pip_size(symbol: str, specs: dict[str, Any] | None = None) -> float:
    """Compatibility helper: returns a conventional pip only for FX."""
    return pip_size_from_specs(symbol, specs or {})


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
    specs = market.get("symbol_specs") or {}
    klass = instrument_class(symbol, specs)
    pip_unit = pip_size_from_specs(symbol, specs)
    tick_unit = tick_size_from_specs(specs)
    movement_unit = pip_unit if pip_unit > 0 else tick_unit
    distance_unit = "pips" if pip_unit > 0 else ("ticks" if tick_unit > 0 else "price")
    favorable = current - entry if direction == "BUY" else entry - current
    risk_distance = abs(entry - stop)
    to_stop = round(abs(current - stop) / movement_unit, 2) if stop and movement_unit > 0 else None
    to_target = round(abs(target - current) / movement_unit, 2) if target and movement_unit > 0 else None
    total_stop = round(risk_distance / movement_unit, 2) if stop and movement_unit > 0 else None
    total_target = round(abs(target - entry) / movement_unit, 2) if target and movement_unit > 0 else None
    status = "PROFIT" if favorable > 0 else "LOSS" if favorable < 0 else "AT ENTRY"
    return {
        "ticket": position.get("ticket", "-"),
        "symbol": symbol or "-",
        "direction": direction,
        "current": current,
        "entry": entry,
        "to_stop_pips": to_stop if distance_unit == "pips" else None,
        "to_target_pips": to_target if distance_unit == "pips" else None,
        "total_stop_pips": total_stop if distance_unit == "pips" else None,
        "total_target_pips": total_target if distance_unit == "pips" else None,
        "to_stop": to_stop,
        "to_target": to_target,
        "total_stop": total_stop,
        "total_target": total_target,
        "distance_unit": distance_unit,
        "instrument_class": klass,
        "profit": float(position.get("profit", 0) or 0),
        "expected_profit": (
            float(position["expected_profit"])
            if position.get("expected_profit") is not None
            else None
        ),
        "r_multiple": round(favorable / risk_distance, 4) if risk_distance else None,
        "status": status,
        "spread_pips": float(market.get("spread_pips", 0) or 0) if market.get("spread_pips") is not None else None,
        "spread_points": float(market.get("spread_points", 0) or 0) if market.get("spread_points") is not None else None,
        "spread_unit": market.get("spread_unit"),
    }