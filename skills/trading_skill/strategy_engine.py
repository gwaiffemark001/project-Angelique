"""Explainable first-class strategy selector for Angelique."""
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
    return candles[-n] if len(candles) >= n else None


def _ready(i: dict[str, Any], keys: tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    readiness = i.get("readiness", {}) or {}
    missing = tuple(key for key in keys if not readiness.get(key, False) or i.get(key) in (None, ""))
    return not missing, missing


def _trend_following(indicators, trends, tf="H1") -> StrategyCandidate:
    i = _ind(indicators, tf)
    ok, missing = _ready(i, ("ema_20", "ema_50", "ema_200", "adx_14", "last_close"))
    if not ok:
        return StrategyCandidate("TREND_FOLLOWING", None, "WAIT", 0, ("EMA alignment", "ADX", "price alignment"), missing, (f"{tf} indicator history is not ready",))
    close, ema20, ema50, ema200, adx = (float(i[k]) for k in ("last_close", "ema_20", "ema_50", "ema_200", "adx_14"))
    bull = close > ema20 > ema50 > ema200 and adx >= 20
    bear = close < ema20 < ema50 < ema200 and adx >= 20
    if bull:
        return StrategyCandidate("TREND_FOLLOWING", "BUY", "READY", 7, ("EMA alignment", "ADX", "price alignment"), (), (f"{tf} EMA20>EMA50>EMA200", f"ADX={adx:.1f}"), metadata={"regime": "trend"})
    if bear:
        return StrategyCandidate("TREND_FOLLOWING", "SELL", "READY", 7, ("EMA alignment", "ADX", "price alignment"), (), (f"{tf} EMA20<EMA50<EMA200", f"ADX={adx:.1f}"), metadata={"regime": "trend"})
    return StrategyCandidate("TREND_FOLLOWING", None, "WAIT", 2, ("EMA alignment", "ADX"), ("directional EMA alignment",), (f"{tf} trend-following conditions incomplete",), metadata={"regime": "mixed"})


def _momentum(indicators, trends, tf="M15") -> StrategyCandidate:
    i = _ind(indicators, tf)
    ok, missing = _ready(i, ("rsi_14", "macd_histogram", "last_close"))
    if not ok or trends.get(tf) not in {"bullish", "bearish"}:
        return StrategyCandidate("MOMENTUM", None, "WAIT", 1, ("RSI", "MACD", "trend"), missing or ("trend",), (f"{tf} momentum data is not ready or trend is mixed",))
    rsi = float(i["rsi_14"]); hist = float(i["macd_histogram"])
    if rsi >= 55 and hist > 0 and trends.get(tf) == "bullish":
        return StrategyCandidate("MOMENTUM", "BUY", "READY", 6, ("RSI", "MACD", "trend"), (), (f"RSI={rsi:.1f}", "MACD histogram positive", f"{tf} bullish"))
    if rsi <= 45 and hist < 0 and trends.get(tf) == "bearish":
        return StrategyCandidate("MOMENTUM", "SELL", "READY", 6, ("RSI", "MACD", "trend"), (), (f"RSI={rsi:.1f}", "MACD histogram negative", f"{tf} bearish"))
    return StrategyCandidate("MOMENTUM", None, "WAIT", 2, ("RSI", "MACD", "trend"), ("momentum alignment",), (f"{tf} momentum conditions are mixed",))


def _breakout(timeframes, indicators, tf="M15") -> StrategyCandidate:
    candles = timeframes.get(tf, []) or []
    i = _ind(indicators, tf)
    if len(candles) < 30 or i.get("status") != "ready":
        return StrategyCandidate("BREAKOUT", None, "WAIT", 0, ("range break", "displacement", "retest/confirmation"), ("sufficient closed history",), ("Insufficient closed candles for breakout analysis",))
    last = _last(candles)
    prior = candles[-21:-1]
    high = max(float(c.get("high", 0) or 0) for c in prior)
    low = min(float(c.get("low", 0) or 0) for c in prior)
    close = float((last or {}).get("close", 0) or 0)
    atr = float(i.get("atr_14", 0) or 0)
    body = abs(float((last or {}).get("close", 0)) - float((last or {}).get("open", 0)))
    displacement = atr > 0 and body >= atr * 1.2
    if displacement and close > high:
        return StrategyCandidate("BREAKOUT", "BUY", "READY", 6, ("range break", "displacement"), (), (f"Close {close} > range high {high}", "displacement confirmed"), target=high + atr * 2, metadata={"break_level": high})
    if displacement and close < low:
        return StrategyCandidate("BREAKOUT", "SELL", "READY", 6, ("range break", "displacement"), (), (f"Close {close} < range low {low}", "displacement confirmed"), target=low - atr * 2, metadata={"break_level": low})
    return StrategyCandidate("BREAKOUT", None, "WAIT", 2, ("range break", "displacement"), ("confirmed displacement break",), (f"Range {low:.5f}-{high:.5f} not validly broken",), metadata={"break_high": high, "break_low": low})


def _mean_reversion(timeframes, indicators, tf="M15") -> StrategyCandidate:
    i = _ind(indicators, tf)
    ok, missing = _ready(i, ("bollinger_lower", "bollinger_upper", "rsi_14", "last_close"))
    if not ok:
        return StrategyCandidate("MEAN_REVERSION", None, "WAIT", 0, ("band extreme", "RSI extreme"), missing, (f"{tf} mean-reversion indicators are not ready",))
    close = float(i["last_close"]); upper = float(i["bollinger_upper"]); lower = float(i["bollinger_lower"]); rsi = float(i["rsi_14"])
    if close <= lower and rsi <= 35:
        return StrategyCandidate("MEAN_REVERSION", "BUY", "READY", 5, ("lower band", "RSI extreme"), (), ("Price at/below lower Bollinger band", f"RSI={rsi:.1f}"), zone={"low": lower, "high": close})
    if close >= upper and rsi >= 65:
        return StrategyCandidate("MEAN_REVERSION", "SELL", "READY", 5, ("upper band", "RSI extreme"), (), ("Price at/above upper Bollinger band", f"RSI={rsi:.1f}"), zone={"low": close, "high": upper})
    return StrategyCandidate("MEAN_REVERSION", None, "WAIT", 2, ("band extreme", "RSI extreme"), ("mean-reversion extreme",), ("Price/RSI not at a mean-reversion extreme",))


def _smc_proxy(structure: dict[str, Any] | None, trends: dict[str, str]) -> StrategyCandidate:
    if not structure:
        return StrategyCandidate("SMC", None, "WAIT", 0, (), ("SMC analysis",), ("SMC analysis unavailable",))
    assessment = structure.get("setup_assessment", {}) or {}
    decision = structure.get("decision")
    direction = structure.get("direction")
    if decision in {"BUY_PLAN_READY", "SELL_PLAN_READY"} and direction in {"BUY", "SELL"}:
        return StrategyCandidate("SMC", direction, "READY", 8, tuple(assessment.get("required", ())), tuple(assessment.get("missing", ())), (assessment.get("reason", "SMC setup complete"),), zone=assessment.get("zone"), target=(assessment.get("target_liquidity") or {}).get("price") if isinstance(assessment.get("target_liquidity"), dict) else None, metadata={"setup": assessment})
    return StrategyCandidate("SMC", direction if direction in {"BUY", "SELL"} else None, "WAIT", 2, tuple(assessment.get("required", ())), tuple(assessment.get("missing", ())) or ("complete SMC setup",), (assessment.get("reason", "SMC setup incomplete"),), zone=assessment.get("zone"), metadata={"setup": assessment})


def _amd_strategy(structure: dict[str, Any] | None, setup_tf: str) -> StrategyCandidate:
    smc = (structure or {}).get("smc", {}) or {}
    setup = smc.get(setup_tf, {}) or {}
    amd = setup.get("amd", {}) or {}
    required = ("accumulation", "manipulation", "structure_shift", "displacement", "entry_zone", "retracement")
    if amd.get("status") == "insufficient":
        return StrategyCandidate("AMD", None, "WAIT", 0, required, ("AMD history",), ("Insufficient closed candles for AMD",), metadata={"amd": amd})
    direction = str(amd.get("trade_direction") or "").upper()
    shift = str(setup.get("structure_shift") or "")
    displacement = bool(setup.get("displacement"))
    directional_shift = (direction == "BUY" and shift.startswith("bullish")) or (direction == "SELL" and shift.startswith("bearish"))
    fvg_or_ob = any(g.get("type") == ("bullish" if direction == "BUY" else "bearish") and g.get("classification") in {"QUALIFIED_FVG", "TRADEABLE_FVG"} and g.get("price_in_zone") for g in setup.get("fair_value_gaps", []) if isinstance(g, dict)) or bool(setup.get("order_block", {}).get("price_in_zone"))
    complete = bool(amd.get("accumulation") and amd.get("manipulation") and directional_shift and displacement and fvg_or_ob)
    missing = []
    if not amd.get("accumulation"): missing.append("accumulation")
    if not amd.get("manipulation"): missing.append("manipulation")
    if not directional_shift: missing.append("structure_shift")
    if not displacement: missing.append("displacement")
    if not fvg_or_ob: missing.extend(["entry_zone", "retracement"])
    if complete and direction in {"BUY", "SELL"}:
        return StrategyCandidate("AMD", direction, "READY", 9, required, (), (f"{setup_tf} AMD accumulation→manipulation→distribution confirmed", "Liquidity raid and displacement confirmed"), metadata={"amd": amd, "setup": setup})
    return StrategyCandidate("AMD", direction if direction in {"BUY", "SELL"} else None, "WAIT", 3 if direction in {"BUY", "SELL"} else 1, required, tuple(dict.fromkeys(missing)), ("AMD sequence is incomplete",), metadata={"amd": amd, "setup": setup})


def select_strategy(*, timeframes, indicators, trends, structure=None, preferred="AUTO", setup_tf="M15") -> dict[str, Any]:
    candidates = [
        _smc_proxy(structure, trends),
        _amd_strategy(structure, setup_tf),
        _trend_following(indicators, trends, "H1"),
        _momentum(indicators, trends, "M15"),
        _breakout(timeframes, indicators, "M15"),
        _mean_reversion(timeframes, indicators, "M15"),
    ]
    preferred = str(preferred or "AUTO").upper()
    if preferred != "AUTO":
        candidates = [c for c in candidates if c.name == preferred] or candidates
    ready = [c for c in candidates if c.state == "READY"]
    best = max(ready or candidates, key=lambda c: c.score)
    return {
        "selected": best.__dict__,
        "candidates": [c.__dict__ for c in candidates],
        "regime": "TRENDING" if best.name == "TREND_FOLLOWING" else "RANGE" if best.name == "MEAN_REVERSION" else "MIXED",
    }
