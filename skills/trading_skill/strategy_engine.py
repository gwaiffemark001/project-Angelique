"""Explainable strategy-family selector for Angelique.

Supported families are deliberately limited to the current product scope:
SMC, trend-following, momentum, breakout and mean-reversion.
No strategy executes orders; selection only returns evidence for the workflow.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyCandidate:
    name: str
    direction: str | None
    state: str
    score: float
    required: tuple[str, ...]
    missing: tuple[str, ...]
    reasons: tuple[str, ...]
    zone: dict[str, float] | None = None
    target: float | None = None
    metadata: dict[str, Any] | None = None


def _ind(indicators: dict[str, dict[str, Any]], tf: str) -> dict[str, Any]:
    return indicators.get(tf, {}) or {}


def _last(candles: list[dict[str, Any]], n: int = 1) -> dict[str, Any] | None:
    if len(candles) < n:
        return None
    return candles[-n]


def _trend_following(indicators, trends, tf="H1") -> StrategyCandidate:
    i = _ind(indicators, tf)
    close = float(i.get("last_close", 0) or 0)
    ema20 = float(i.get("ema_20", 0) or 0)
    ema50 = float(i.get("ema_50", 0) or 0)
    ema200 = float(i.get("ema_200", 0) or 0)
    adx = float(i.get("adx_14", 0) or 0)
    bull = close > ema20 > ema50 > ema200 and adx >= 20
    bear = close < ema20 < ema50 < ema200 and adx >= 20
    if bull:
        return StrategyCandidate("TREND_FOLLOWING", "BUY", "READY", 7, ("EMA alignment", "ADX", "price alignment"), (), (f"{tf} EMA20>EMA50>EMA200", f"ADX={adx:.1f}"), metadata={"regime": "trend"})
    if bear:
        return StrategyCandidate("TREND_FOLLOWING", "SELL", "READY", 7, ("EMA alignment", "ADX", "price alignment"), (), (f"{tf} EMA20<EMA50<EMA200", f"ADX={adx:.1f}"), metadata={"regime": "trend"})
    missing = []
    if not (bull or bear):
        missing.append("directional EMA alignment")
    if adx < 20:
        missing.append("ADX >= 20")
    return StrategyCandidate("TREND_FOLLOWING", None, "WAIT", 2, ("EMA alignment", "ADX"), tuple(missing), (f"{tf} trend-following conditions incomplete",), metadata={"regime": "mixed"})


def _momentum(indicators, trends, tf="M15") -> StrategyCandidate:
    i = _ind(indicators, tf)
    rsi = float(i.get("rsi_14", 50) or 50)
    hist = float(i.get("macd_histogram", 0) or 0)
    if rsi >= 55 and hist > 0 and trends.get(tf) == "bullish":
        return StrategyCandidate("MOMENTUM", "BUY", "READY", 6, ("RSI", "MACD", "trend"), (), (f"RSI={rsi:.1f}", "MACD histogram positive", f"{tf} bullish"))
    if rsi <= 45 and hist < 0 and trends.get(tf) == "bearish":
        return StrategyCandidate("MOMENTUM", "SELL", "READY", 6, ("RSI", "MACD", "trend"), (), (f"RSI={rsi:.1f}", "MACD histogram negative", f"{tf} bearish"))
    return StrategyCandidate("MOMENTUM", None, "WAIT", 2, ("RSI", "MACD", "trend"), ("momentum alignment",), (f"{tf} momentum conditions are mixed",))


def _breakout(timeframes, indicators, tf="M15") -> StrategyCandidate:
    candles = timeframes.get(tf, []) or []
    if len(candles) < 25:
        return StrategyCandidate("BREAKOUT", None, "WAIT", 0, ("range break", "close confirmation"), ("enough candles",), ("Insufficient candles for breakout range",))
    last = _last(candles)
    prior = candles[-21:-1]
    high = max(float(c.get("high", 0) or 0) for c in prior)
    low = min(float(c.get("low", 0) or 0) for c in prior)
    close = float((last or {}).get("close", 0) or 0)
    atr = float(_ind(indicators, tf).get("atr_14", 0) or 0)
    if atr > 0 and close > high:
        return StrategyCandidate("BREAKOUT", "BUY", "READY", 6, ("range break", "close confirmation"), (), (f"Close {close} > range high {high}",), target=high + atr * 2, metadata={"break_level": high})
    if atr > 0 and close < low:
        return StrategyCandidate("BREAKOUT", "SELL", "READY", 6, ("range break", "close confirmation"), (), (f"Close {close} < range low {low}",), target=low - atr * 2, metadata={"break_level": low})
    return StrategyCandidate("BREAKOUT", None, "WAIT", 2, ("range break", "close confirmation"), ("confirmed close outside range",), (f"Range {low:.5f}-{high:.5f} not broken",), metadata={"break_high": high, "break_low": low})


def _mean_reversion(timeframes, indicators, tf="M15") -> StrategyCandidate:
    i = _ind(indicators, tf)
    close = float(i.get("last_close", 0) or 0)
    upper = float(i.get("bollinger_upper", 0) or 0)
    lower = float(i.get("bollinger_lower", 0) or 0)
    rsi = float(i.get("rsi_14", 50) or 50)
    if close <= lower and rsi <= 35:
        return StrategyCandidate("MEAN_REVERSION", "BUY", "READY", 5, ("lower band", "RSI extreme"), (), ("Price at/below lower Bollinger band", f"RSI={rsi:.1f}"), zone={"low": lower, "high": close})
    if close >= upper and rsi >= 65:
        return StrategyCandidate("MEAN_REVERSION", "SELL", "READY", 5, ("upper band", "RSI extreme"), (), ("Price at/above upper Bollinger band", f"RSI={rsi:.1f}"), zone={"low": close, "high": upper})
    return StrategyCandidate("MEAN_REVERSION", None, "WAIT", 2, ("band extreme", "RSI extreme"), ("mean-reversion extreme",), ("Price/RSI not at a mean-reversion extreme",))


def _smc_proxy(structure: dict[str, Any] | None, trends: dict[str, str]) -> StrategyCandidate:
    if not structure:
        return StrategyCandidate("SMC", None, "WAIT", 0, (), ("SMC analysis",), ("SMC analysis unavailable",))
    decision = structure.get("decision")
    direction = structure.get("direction")
    assessment = structure.get("setup_assessment", {}) or {}
    if decision in {"BUY_PLAN_READY", "SELL_PLAN_READY"} and direction in {"BUY", "SELL"}:
        return StrategyCandidate("SMC", direction, "READY", 8, tuple(assessment.get("required", ())), tuple(assessment.get("missing", ())), (assessment.get("reason", "SMC setup complete"),), zone=assessment.get("zone"), target=(assessment.get("target_liquidity") or {}).get("price") if isinstance(assessment.get("target_liquidity"), dict) else None, metadata={"setup": assessment})
    if direction and assessment.get("model") not in {None, "UNSUPPORTED"}:
        return StrategyCandidate("SMC", direction, "WAIT", 4, tuple(assessment.get("required", ())), tuple(assessment.get("missing", ())), (assessment.get("reason", "SMC setup incomplete"),), zone=assessment.get("zone"), metadata={"setup": assessment})
    return StrategyCandidate("SMC", None, "WAIT", 1, (), (), ("No complete SMC setup",))


def select_strategy(*, timeframes, indicators, trends, structure=None, preferred="AUTO") -> dict[str, Any]:
    candidates = [
        _smc_proxy(structure, trends),
        _trend_following(indicators, trends, "H1"),
        _momentum(indicators, trends, "M15"),
        _breakout(timeframes, indicators, "M15"),
        _mean_reversion(timeframes, indicators, "M15"),
    ]
    preferred = str(preferred or "AUTO").upper()
    if preferred != "AUTO":
        candidates = [c for c in candidates if c.name == preferred] or candidates
    ready = [c for c in candidates if c.state == "READY"]
    if ready:
        best = max(ready, key=lambda c: c.score)
    else:
        best = max(candidates, key=lambda c: c.score)
    return {
        "selected": best.__dict__,
        "candidates": [c.__dict__ for c in candidates],
        "regime": "TRENDING" if best.name == "TREND_FOLLOWING" else "RANGE" if best.name == "MEAN_REVERSION" else "MIXED",
    }
