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


def _directional_trend(trends: dict[str, str], direction: str | None, tf: str) -> bool:
    if direction not in {"BUY", "SELL"}:
        return False
    return str(trends.get(tf) or "").lower() == ("bullish" if direction == "BUY" else "bearish")


def _quality_score(weighted: list[tuple[float, float]]) -> int:
    total = sum(max(0.0, w) for _, w in weighted)
    if total <= 0:
        return 0
    earned = sum(max(0.0, min(1.0, q)) * w for q, w in weighted)
    return int(round(100.0 * earned / total))


def _trend_following(indicators, trends, tf="H1") -> StrategyCandidate:
    i = _ind(indicators, tf)
    ok, missing = _ready(i, ("ema_20", "ema_50", "ema_200", "adx_14", "last_close"))
    if not ok:
        return StrategyCandidate("TREND_FOLLOWING", None, "WAIT", 0, ("EMA alignment", "ADX", "price alignment", "HTF context"), missing, (f"{tf} indicator history is not ready",))
    close, ema20, ema50, ema200, adx = (float(i[k]) for k in ("last_close", "ema_20", "ema_50", "ema_200", "adx_14"))
    direction = "BUY" if close > ema20 > ema50 > ema200 else "SELL" if close < ema20 < ema50 < ema200 else None
    ema_align = direction is not None
    if not ema_align:
        return StrategyCandidate("TREND_FOLLOWING", None, "WAIT", 45, ("EMA alignment", "ADX", "price alignment", "HTF context"), ("directional EMA alignment",), (f"{tf} trend-following structure is mixed",), metadata={"regime": "mixed", "score_basis": "graded"})
    adx_quality = 0.0 if adx < 20 else min(1.0, (adx - 20.0) / 15.0 + 0.35)
    htf = _directional_trend(trends, direction, "D1") or _directional_trend(trends, direction, "H4")
    ltf = _directional_trend(trends, direction, "M15") and _directional_trend(trends, direction, "M5")
    atr = float(i.get("atr_14", 0) or 0)
    extension = abs(close - ema20) / atr if atr > 0 else 99.0
    location_quality = 1.0 if extension <= 1.0 else 0.8 if extension <= 1.5 else 0.35 if extension <= 2.0 else 0.0
    score = _quality_score([(1.0 if ema_align else 0.0, 30), (adx_quality, 25), (1.0 if htf else 0.0, 20), (1.0 if ltf else 0.0, 15), (location_quality, 10)])
    playbook = {
        "name": "TREND_FOLLOWING",
        "stages": ["EMA trend alignment", "ADX trend-strength confirmation", "HTF context", "non-extended entry location", "structural invalidation", "minimum-RR target"],
        "complete": True,
    }
    return StrategyCandidate("TREND_FOLLOWING", direction, "READY" if adx >= 20 and htf and ltf else "WAIT", score,
                             ("EMA alignment", "ADX", "price alignment", "HTF context", "non-extended location", "structural invalidation", "minimum-RR target"),
                             tuple(x for x, ok_ in (("ADX >= 20", adx >= 20), ("HTF context", htf), ("lower timeframe alignment", ltf)) if not ok_),
                             (f"{tf} directional EMA stack", f"ADX={adx:.1f}", f"HTF={'aligned' if htf else 'mixed'}", f"entry extension={extension:.2f} ATR"), metadata={"regime": "trend", "strategy_plan": playbook, "score_basis": "graded_normalized_100"})


def _momentum(indicators, trends, tf="M15") -> StrategyCandidate:
    i = _ind(indicators, tf)
    ok, missing = _ready(i, ("rsi_14", "macd_histogram", "macd", "macd_signal", "last_close"))
    if not ok or trends.get(tf) not in {"bullish", "bearish"}:
        return StrategyCandidate("MOMENTUM", None, "WAIT", 0, ("RSI", "MACD", "trend", "entry confirmation", "HTF context"), missing or ("trend",), (f"{tf} momentum data is not ready or trend is mixed",))
    direction = "BUY" if trends.get(tf) == "bullish" else "SELL"
    rsi = float(i["rsi_14"]); hist = float(i["macd_histogram"]); macd = float(i["macd"]); signal = float(i["macd_signal"])
    rsi_quality = ((rsi - 50) / 20) if direction == "BUY" else ((50 - rsi) / 20)
    rsi_quality = max(0.0, min(1.0, rsi_quality)) if (52 <= rsi <= 70 if direction == "BUY" else 30 <= rsi <= 48) else max(0.0, min(0.45, rsi_quality))
    macd_ok = macd > signal and hist > 0 if direction == "BUY" else macd < signal and hist < 0
    entry = _directional_trend(trends, direction, "M5")
    htf = _directional_trend(trends, direction, "D1") or _directional_trend(trends, direction, "H4")
    score = _quality_score([(1.0 if trends.get(tf) == ("bullish" if direction == "BUY" else "bearish") else 0.0, 25), (rsi_quality, 20), (1.0 if macd_ok else 0.0, 30), (1.0 if entry else 0.0, 10), (1.0 if htf else 0.0, 15)])
    ready = bool(macd_ok and entry)
    return StrategyCandidate("MOMENTUM", direction, "READY" if ready else "WAIT", score,
                             ("RSI quality", "MACD line/signal + histogram", "setup trend", "entry confirmation", "HTF context", "structural invalidation", "minimum-RR target"),
                             tuple(x for x, ok_ in (("RSI quality", rsi_quality >= 0.65), ("MACD confirmation", macd_ok), ("entry confirmation", entry), ("HTF context", htf)) if not ok_),
                             (f"RSI={rsi:.1f}", f"MACD histogram={hist:.6f}", f"HTF={'aligned' if htf else 'mixed'}"), metadata={"strategy_plan": {"name": "MOMENTUM", "stages": ["Trend direction", "RSI confirmation", "MACD line/signal confirmation", "Entry confirmation", "Structural invalidation", "Minimum-RR target"], "complete": ready}, "score_basis": "graded_normalized_100"})


def _breakout(timeframes, indicators, tf="M15") -> StrategyCandidate:
    candles = timeframes.get(tf, []) or []
    i = _ind(indicators, tf)
    if len(candles) < 30 or i.get("status") != "ready":
        return StrategyCandidate("BREAKOUT", None, "WAIT", 0, ("range definition", "range break", "displacement", "closed-candle confirmation", "structural invalidation", "minimum-RR target"), ("sufficient closed history",), ("Insufficient closed candles for breakout analysis",))
    last = _last(candles); prior = candles[-21:-1]
    high = max(float(c.get("high", 0) or 0) for c in prior); low = min(float(c.get("low", 0) or 0) for c in prior)
    close = float((last or {}).get("close", 0) or 0); atr = float(i.get("atr_14", 0) or 0)
    body = abs(float((last or {}).get("close", 0) or 0) - float((last or {}).get("open", 0) or 0))
    body_ratio = body / atr if atr > 0 else 0.0
    displacement_quality = max(0.0, min(1.0, (body_ratio - 0.8) / 1.2))
    direction = "BUY" if close > high else "SELL" if close < low else None
    break_distance = ((close - high) / atr if direction == "BUY" and atr > 0 else (low - close) / atr if direction == "SELL" and atr > 0 else 0.0)
    break_quality = max(0.0, min(1.0, break_distance / 0.75))
    # Trend evidence is available through indicator data only here; structural alignment is captured by the break itself.
    if direction:
        score = _quality_score([(1.0, 20), (break_quality, 25), (displacement_quality, 25), (1.0 if body_ratio >= 1.2 else 0.0, 15), (1.0 if close > high or close < low else 0.0, 15)])
        ready = bool(displacement_quality >= 0.7 and break_quality >= 0.5)
    else:
        score = 20
        ready = False
    required = ("range definition", "range break", "displacement", "closed-candle confirmation", "structural invalidation", "minimum-RR target")
    if direction and ready:
        target = high + atr * 2 if direction == "BUY" else low - atr * 2
        return StrategyCandidate("BREAKOUT", direction, "READY", score, required, (), (f"Close {'>' if direction == 'BUY' else '<'} range boundary", f"body={body_ratio:.2f} ATR", f"break={break_distance:.2f} ATR"), target=target, metadata={"break_level": high if direction == "BUY" else low, "range_low": low, "range_high": high, "strategy_plan": {"name": "BREAKOUT", "stages": ["Range definition", "Displacement breakout", "Closed-candle confirmation", "Stop back inside range", "ATR-derived target"], "complete": True}, "score_basis": "graded_normalized_100"})
    return StrategyCandidate("BREAKOUT", direction, "WAIT", score, required, ("confirmed breakout with displacement",), (f"Range {low:.5f}-{high:.5f} not validly broken with sufficient displacement",), metadata={"break_high": high, "break_low": low, "score_basis": "graded_normalized_100"})


def _mean_reversion(timeframes, indicators, trends, tf="M15") -> StrategyCandidate:
    i = _ind(indicators, tf)
    ok, missing = _ready(i, ("bollinger_lower", "bollinger_upper", "bollinger_middle", "rsi_14", "last_close", "adx_14"))
    if not ok:
        return StrategyCandidate("MEAN_REVERSION", None, "WAIT", 0, ("range regime", "band extreme", "RSI", "mean target", "structural invalidation"), missing, (f"{tf} mean-reversion indicators are not ready",))
    close = float(i["last_close"]); upper = float(i["bollinger_upper"]); lower = float(i["bollinger_lower"]); middle = float(i["bollinger_middle"]); rsi = float(i["rsi_14"]); adx = float(i["adx_14"])
    direction = "BUY" if close <= lower and rsi <= 35 else "SELL" if close >= upper and rsi >= 65 else None
    range_quality = 1.0 if adx < 20 else 0.75 if adx < 25 else 0.0
    extreme = direction is not None
    if direction == "BUY":
        rsi_q = max(0.0, min(1.0, (35.0 - rsi) / 15.0 + 0.65)) if rsi <= 35 else 0.0
        target_ok = middle > close
    elif direction == "SELL":
        rsi_q = max(0.0, min(1.0, (rsi - 65.0) / 15.0 + 0.65)) if rsi >= 65 else 0.0
        target_ok = middle < close
    else:
        rsi_q = 0.0; target_ok = False
    htf_neutral = str(trends.get("H1") or "") == "mixed" or str(trends.get("H4") or "") == "mixed" if isinstance(trends, dict) else False
    score = _quality_score([(range_quality, 30), (1.0 if extreme else 0.0, 30), (rsi_q, 20), (1.0 if target_ok else 0.0, 10), (1.0 if htf_neutral else 0.0, 10)])
    ready = bool(direction and range_quality >= 0.75 and target_ok)
    if direction and ready:
        return StrategyCandidate("MEAN_REVERSION", direction, "READY", score, ("range regime", "band extreme", "RSI confirmation", "mean target", "structural invalidation"), (), (f"Price reached {'lower' if direction=='BUY' else 'upper'} Bollinger band", f"RSI={rsi:.1f}", f"ADX={adx:.1f}"), zone={"low": lower, "high": close} if direction == "BUY" else {"low": close, "high": upper}, target=middle, metadata={"strategy_plan": {"name": "MEAN_REVERSION", "stages": ["Range regime", "Band extreme", "RSI confirmation", "Mean target", "Structural invalidation"], "complete": True}, "mean_target": middle, "score_basis": "graded_normalized_100"})
    return StrategyCandidate("MEAN_REVERSION", direction, "WAIT", score, ("range regime", "band extreme", "RSI confirmation", "mean target", "structural invalidation"), ("confirmed mean-reversion extreme" if not direction else "range/target prerequisites",), (f"Price/RSI/ADX not yet sufficient for mean reversion",), metadata={"score_basis": "graded_normalized_100"})


def _smc_proxy(structure: dict[str, Any] | None, trends: dict[str, str]) -> StrategyCandidate:
    if not structure:
        return StrategyCandidate("SMC", None, "WAIT", 0, (), ("SMC analysis",), ("SMC analysis unavailable",))
    assessment = structure.get("setup_assessment", {}) or {}
    decision = structure.get("decision"); direction = structure.get("direction")
    stages = assessment.get("stages", {}) if isinstance(assessment.get("stages"), dict) else {}
    if decision in {"BUY_PLAN_READY", "SELL_PLAN_READY"} and direction in {"BUY", "SELL"}:
        required_count = len(assessment.get("required", ()) or ())
        complete_ratio = 1.0
        if required_count:
            complete_ratio = max(0.0, min(1.0, (required_count - len(assessment.get("missing", ()) or ())) / required_count))
        location = str(assessment.get("location") or "")
        htf = _directional_trend(trends, direction, "D1") or _directional_trend(trends, direction, "H4")
        optional_bonus = 1.0 if stages.get("entry_confirmation") else 0.0
        score = _quality_score([(complete_ratio, 55), (1.0 if htf else 0.0, 20), (1.0 if location in {"discount", "premium"} else 0.0, 10), (optional_bonus, 15)])
        return StrategyCandidate("SMC", direction, "READY", score, tuple(assessment.get("required", ())), tuple(assessment.get("missing", ())), (assessment.get("reason", "SMC setup complete"),), zone=assessment.get("zone"), target=(assessment.get("target_liquidity") or {}).get("price") if isinstance(assessment.get("target_liquidity"), dict) else None, metadata={"setup": assessment, "score_basis": "graded_normalized_100"})
    score = 45 if direction in {"BUY", "SELL"} else 0
    return StrategyCandidate("SMC", direction if direction in {"BUY", "SELL"} else None, "WAIT", score, tuple(assessment.get("required", ())), tuple(assessment.get("missing", ())) or ("complete SMC setup",), (assessment.get("reason", "SMC setup incomplete"),), zone=assessment.get("zone"), metadata={"setup": assessment, "score_basis": "graded_normalized_100"})


def _amd_strategy(structure: dict[str, Any] | None, setup_tf: str, trends: dict[str, str]) -> StrategyCandidate:
    smc = (structure or {}).get("smc", {}) or {}; setup = smc.get(setup_tf, {}) or {}; amd = setup.get("amd", {}) or {}
    required = ("accumulation", "manipulation", "structure_shift", "displacement", "entry_zone", "retracement")
    if amd.get("status") == "insufficient":
        return StrategyCandidate("AMD", None, "WAIT", 0, required, ("AMD history",), ("Insufficient closed candles for AMD",))
    direction = str(amd.get("trade_direction") or "").upper(); shift = str(setup.get("structure_shift") or ""); displacement = bool(setup.get("displacement"))
    directional_shift = (direction == "BUY" and shift.startswith("bullish")) or (direction == "SELL" and shift.startswith("bearish"))
    zone_present = any(g.get("type") == ("bullish" if direction == "BUY" else "bearish") and g.get("classification") in {"QUALIFIED_FVG", "TRADEABLE_FVG"} and g.get("status") not in {"FULLY_MITIGATED", "INVALIDATED"} for g in setup.get("fair_value_gaps", []) if isinstance(g, dict)) or bool((setup.get("order_block") or {}).get("type") == ("bullish" if direction == "BUY" else "bearish"))
    retracement = any(g.get("type") == ("bullish" if direction == "BUY" else "bearish") and g.get("classification") in {"QUALIFIED_FVG", "TRADEABLE_FVG"} and g.get("price_in_zone") for g in setup.get("fair_value_gaps", []) if isinstance(g, dict)) or bool((setup.get("order_block") or {}).get("price_in_zone"))
    entry_confirm = _directional_trend(trends, direction, "M5")
    htf = _directional_trend(trends, direction, "D1") or _directional_trend(trends, direction, "H4")
    factors = [(1.0 if amd.get("accumulation") else 0.0, 10), (1.0 if amd.get("manipulation") else 0.0, 20), (1.0 if directional_shift else 0.0, 20), (1.0 if displacement else 0.0, 15), (1.0 if zone_present else 0.0, 15), (1.0 if retracement else 0.0, 10), (1.0 if entry_confirm else 0.0, 5), (1.0 if htf else 0.0, 5)]
    score = _quality_score(factors)
    complete = bool(amd.get("accumulation") and amd.get("manipulation") and directional_shift and displacement and zone_present and retracement and entry_confirm)
    missing = [name for name, ok in (("accumulation", bool(amd.get("accumulation"))), ("manipulation", bool(amd.get("manipulation"))), ("structure_shift", directional_shift), ("displacement", displacement), ("entry_zone", zone_present), ("retracement", retracement), ("entry_confirmation", entry_confirm)) if not ok]
    if complete and direction in {"BUY", "SELL"}:
        return StrategyCandidate("AMD", direction, "READY", score, required, tuple(missing), (f"{setup_tf} AMD accumulation→manipulation→distribution confirmed", "Liquidity raid and displacement confirmed"), metadata={"amd": amd, "setup": setup, "strategy_plan": {"name": "AMD", "stages": list(required), "complete": True}, "score_basis": "graded_normalized_100"})
    return StrategyCandidate("AMD", direction if direction in {"BUY", "SELL"} else None, "WAIT", score, required, tuple(dict.fromkeys(missing)), ("AMD sequence is incomplete",), metadata={"amd": amd, "setup": setup, "score_basis": "graded_normalized_100"})


def select_strategy(*, timeframes, indicators, trends, structure=None, preferred="AUTO", setup_tf="M15") -> dict[str, Any]:
    candidates = [
        _smc_proxy(structure, trends),
        _amd_strategy(structure, setup_tf, trends),
        _trend_following(indicators, trends, "H1"),
        _momentum(indicators, trends, "M15"),
        _breakout(timeframes, indicators, "M15"),
        _mean_reversion(timeframes, indicators, trends, "M15"),
    ]
    preferred = str(preferred or "AUTO").upper()
    if preferred != "AUTO":
        candidates = [c for c in candidates if c.name == preferred] or candidates
    ready = [c for c in candidates if c.state == "READY" and c.score >= 70]
    best = max(ready or candidates, key=lambda c: c.score)
    return {
        "selected": best.__dict__,
        "candidates": [c.__dict__ for c in candidates],
        "score_scale": {"minimum": 70, "maximum": 100, "note": "Normalized strategy-quality score; not a win probability."},
        "regime": "TRENDING" if best.name == "TREND_FOLLOWING" else "RANGE" if best.name == "MEAN_REVERSION" else "MIXED",
    }
