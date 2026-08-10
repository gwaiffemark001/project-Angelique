from __future__ import annotations

from typing import Any
from .indicators import snapshot


def _trend(candles: list[dict[str, Any]]) -> str:
    closes = [float(c.get("close", 0)) for c in candles if float(c.get("close", 0)) > 0]
    if len(closes) < 3:
        return "unknown"
    if closes[-1] > closes[0] and closes[-1] > closes[-2]:
        return "bullish"
    if closes[-1] < closes[0] and closes[-1] < closes[-2]:
        return "bearish"
    return "sideways"


def analyze_structure(timeframes: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    trends = {timeframe: _trend(candles) for timeframe, candles in timeframes.items()}
    indicator_data = {timeframe: snapshot(candles) for timeframe, candles in timeframes.items()}
    higher = trends.get("H4", "unknown")
    intermediate = trends.get("H1", "unknown")
    setup = trends.get("M15", "unknown")
    confirmation = trends.get("M5", "unknown")
    if "unknown" in trends.values():
        return {"valid": False, "reason": "Insufficient candles for the required multi-timeframe analysis.", "trends": trends, "indicators": indicator_data}
    if higher not in {"bullish", "bearish"}:
        return {"valid": False, "reason": "Higher-timeframe market structure is not directional.", "trends": trends, "indicators": indicator_data}
    if intermediate != higher or setup != higher or confirmation != higher:
        return {"valid": False, "reason": "The required timeframes conflict; no aligned setup exists.", "trends": trends, "indicators": indicator_data}
    direction = "BUY" if higher == "bullish" else "SELL"
    indicator_reasons = []
    for timeframe, values in indicator_data.items():
        if values.get("status") != "ready":
            return {"valid": False, "reason": f"Indicators are unavailable on {timeframe}.", "trends": trends, "indicators": indicator_data}
        last_close = float(values["last_close"])
        ema_ok = last_close >= float(values["ema_20"]) >= float(values["ema_50"]) if direction == "BUY" else last_close <= float(values["ema_20"]) <= float(values["ema_50"])
        macd_ok = float(values["macd"]) >= 0 if direction == "BUY" else float(values["macd"]) <= 0
        rsi_ok = float(values["rsi_14"]) >= 50 if direction == "BUY" else float(values["rsi_14"]) <= 50
        last_close = float(values["last_close"])
        middle = float(values["bollinger_middle"])
        upper = float(values["bollinger_upper"])
        lower = float(values["bollinger_lower"])
        band_position = "upper half" if last_close >= middle else "lower half"
        band_valid = lower <= last_close <= upper
        indicator_reasons.append(f"{timeframe}: EMA {'aligned' if ema_ok else 'mixed'}, RSI {float(values['rsi_14']):.1f} {'aligned' if rsi_ok else 'mixed'}, MACD {'aligned' if macd_ok else 'mixed'}, Bollinger {band_position} {'inside bands' if band_valid else 'outside bands'}, ATR {float(values['atr_14']):.6f}")
    return {"valid": True, "direction": direction, "trends": trends, "indicators": indicator_data, "reason": f"H4, H1, M15, and M5 structure align {higher}.", "indicator_reasons": indicator_reasons}
