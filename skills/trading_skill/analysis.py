from __future__ import annotations

from typing import Any

from .context import build_market_context
from .confluence import evaluate_confluence


def _trend(candles: list[dict[str, Any]]) -> str:
    closes = [float(c.get("close", 0)) for c in candles if float(c.get("close", 0)) > 0]
    if len(closes) < 3:
        return "unknown"
    if closes[-1] > closes[0] and closes[-1] > closes[-2]:
        return "bullish"
    if closes[-1] < closes[0] and closes[-1] < closes[-2]:
        return "bearish"
    return "sideways"


def analyze_structure(timeframes: dict[str, list[dict[str, Any]]], profile=None) -> dict[str, Any]:
    context = build_market_context(timeframes)
    trends = context.trends
    indicator_data = context.indicators
    smc_data = context.smc
    context_timeframe = getattr(profile, "context_timeframe", "H4")
    trend_timeframe = getattr(profile, "trend_timeframe", "H1")
    setup_timeframe = getattr(profile, "setup_timeframe", "M15")
    entry_timeframe = getattr(profile, "entry_timeframe", "M5")
    higher = trends.get(context_timeframe, "unknown")
    intermediate = trends.get(trend_timeframe, "unknown")
    setup = trends.get(setup_timeframe, "unknown")
    confirmation = trends.get(entry_timeframe, "unknown")
    if "unknown" in trends.values():
        return {"valid": False, "reason": "Insufficient candles for the required multi-timeframe analysis.", "trends": trends, "indicators": indicator_data, "smc": smc_data}
    if higher not in {"bullish", "bearish"}:
        return {"valid": False, "reason": "Higher-timeframe market structure is not directional.", "trends": trends, "indicators": indicator_data, "smc": smc_data}
    if intermediate != higher or setup != higher or confirmation != higher:
        return {"valid": False, "reason": "The required timeframes conflict; no aligned setup exists.", "trends": trends, "indicators": indicator_data, "smc": smc_data}

    direction = "BUY" if higher == "bullish" else "SELL"
    indicator_reasons = []
    for timeframe, values in indicator_data.items():
        if values.get("status") != "ready":
            return {"valid": False, "reason": f"Indicators are unavailable on {timeframe}.", "trends": trends, "indicators": indicator_data, "smc": smc_data}
        last_close = float(values["last_close"])
        ema_ok = last_close >= float(values["ema_20"]) >= float(values["ema_50"]) if direction == "BUY" else last_close <= float(values["ema_20"]) <= float(values["ema_50"])
        macd_ok = float(values["macd"]) >= 0 if direction == "BUY" else float(values["macd"]) <= 0
        rsi_ok = float(values["rsi_14"]) >= 50 if direction == "BUY" else float(values["rsi_14"]) <= 50
        middle = float(values["bollinger_middle"])
        upper = float(values["bollinger_upper"])
        lower = float(values["bollinger_lower"])
        band_position = "upper half" if last_close >= middle else "lower half"
        band_valid = lower <= last_close <= upper
        indicator_reasons.append(f"{timeframe}: EMA {'aligned' if ema_ok else 'mixed'}, RSI {float(values['rsi_14']):.1f} {'aligned' if rsi_ok else 'mixed'}, MACD {'aligned' if macd_ok else 'mixed'}, Bollinger {band_position} {'inside bands' if band_valid else 'outside bands'}, ATR {float(values['atr_14']):.6f}")

    smc_reasons = []
    for timeframe, values in smc_data.items():
        sweep = values.get("liquidity_sweep") or "none"
        shift = values.get("structure_shift") or "none"
        gaps = len(values.get("fair_value_gaps", []))
        block = values.get("order_block")
        smc_reasons.append(f"{timeframe}: liquidity={sweep}, shift={shift}, FVGs={gaps}, order_block={block.get('type') if isinstance(block, dict) else 'none'}, location={values.get('location', 'unknown')}")

    confluence = evaluate_confluence(direction, trends, indicator_data, smc_data, profile=profile)
    if not confluence["ready"]:
        return {"valid": False, "reason": "The setup lacks enough confluence; indicators and SMC are not aligned strongly enough to plan a trade.", "trends": trends, "indicators": indicator_data, "smc": smc_data, "confluence": confluence}

    return {"valid": True, "direction": direction, "trends": trends, "indicators": indicator_data, "smc": smc_data, "reason": f"{context_timeframe}, {trend_timeframe}, {setup_timeframe}, and {entry_timeframe} structure align {higher}.", "indicator_reasons": indicator_reasons, "smc_reasons": smc_reasons, "confluence": confluence}
