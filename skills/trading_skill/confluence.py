from __future__ import annotations

from typing import Any


STRATEGY_SCORE_CONFIG = {
    "SMC": {"minimum": 70, "countertrend": 100},
    "AMD": {"minimum": 70, "countertrend": 100},
    "TREND_FOLLOWING": {"minimum": 70, "countertrend": 100},
    "MOMENTUM": {"minimum": 70, "countertrend": 100},
    "BREAKOUT": {"minimum": 70, "countertrend": 100},
    "MEAN_REVERSION": {"minimum": 70, "countertrend": 100},
}


def _directional(value: Any, direction: str) -> bool:
    expected = "bullish" if direction == "BUY" else "bearish"
    return str(value or "").lower() == expected


def _record(components: dict[str, int], evidence: dict[str, bool], name: str, points: int, condition: bool, agree: list[str], disagree: list[str], yes: str, no: str) -> None:
    components[name] = points
    evidence[name] = bool(condition)
    (agree if condition else disagree).append(yes if condition else no)


def _weighted_score(components: dict[str, int], evidence: dict[str, bool]) -> tuple[int, int]:
    maximum = sum(components.values())
    earned = sum(points for name, points in components.items() if evidence.get(name, False))
    if maximum <= 0:
        return 0, 0
    return round(100.0 * earned / maximum), maximum


def strategy_score_config(strategy: str) -> dict[str, int]:
    return dict(STRATEGY_SCORE_CONFIG.get(str(strategy or "").upper(), {"minimum": 70, "countertrend": 100}))


def evaluate_confluence(
    direction: str,
    trends: dict[str, str],
    indicator_data: dict[str, dict[str, Any]],
    smc_data: dict[str, dict[str, Any]],
    profile=None,
    strategy_name: str = "SMC",
) -> dict[str, Any]:
    """Score strategy-specific evidence on a normalized 0-100 scale.

    The score is a quality score, not a win probability. Each strategy has its
    own evidence weights and its own hard prerequisites; correlated evidence is
    grouped so one price event is not rewarded repeatedly just because it is
    visible through several labels.
    """
    strategy = str(strategy_name or "SMC").upper()
    cfg = strategy_score_config(strategy)
    agree: list[str] = []
    disagree: list[str] = []
    components: dict[str, int] = {}
    evidence: dict[str, bool] = {}

    context_tf = getattr(profile, "context_timeframe", "H4")
    trend_tf = getattr(profile, "trend_timeframe", "H1")
    setup_tf = getattr(profile, "setup_timeframe", "M15")
    entry_tf = getattr(profile, "entry_timeframe", "M5")
    setup_values = smc_data.get(setup_tf, {}) or {}
    entry_values = smc_data.get(entry_tf, {}) or {}
    setup_ind = indicator_data.get(setup_tf, {}) or {}
    trend_ind = indicator_data.get(trend_tf, {}) or {}
    expected = "bullish" if direction == "BUY" else "bearish"

    context_aligned = _directional(trends.get(context_tf), direction) and _directional(trends.get(trend_tf), direction)
    _record(components, evidence, "htf_alignment", 15, context_aligned, agree, disagree,
            f"AGREES: {context_tf}/{trend_tf} directional context aligns with {direction}.",
            f"DISAGREES: {context_tf}/{trend_tf} context is not fully aligned.")

    if strategy == "SMC":
        ict = setup_values.get("ict", {}) if isinstance(setup_values.get("ict"), dict) else {}
        ote = ict.get("ote", {}) if isinstance(ict.get("ote"), dict) else {}
        amd = ict.get("amd", {}) if isinstance(ict.get("amd"), dict) else (setup_values.get("amd", {}) if isinstance(setup_values.get("amd"), dict) else {})
        expected_sweep = "sell_side_liquidity_sweep" if direction == "BUY" else "buy_side_liquidity_sweep"
        sweep = setup_values.get("liquidity_sweep") == expected_sweep
        _record(components, evidence, "liquidity_event", 15, sweep, agree, disagree,
                f"AGREES: {setup_tf} liquidity sweep supports {direction}.",
                f"DISAGREES: {setup_tf} has no directional liquidity sweep.")

        shift = str(setup_values.get("structure_shift") or "")
        strict_choch = setup_values.get("strict_choch") if isinstance(setup_values.get("strict_choch"), dict) else {}
        shift_ok = shift.startswith(expected + "_BOS") or (shift.startswith(expected + "_CHoCH") and strict_choch.get("valid") is True)
        _record(components, evidence, "structure_confirmation", 15, shift_ok, agree, disagree,
                f"AGREES: {setup_tf} validated BOS/strict CHOCH supports {direction}.",
                f"DISAGREES: {setup_tf} lacks validated directional structure confirmation.")

        block = setup_values.get("order_block")
        gaps = setup_values.get("fair_value_gaps", []) or []
        quality_block = isinstance(block, dict) and block.get("type") == expected and float(block.get("score", 0) or 0) >= 5 and block.get("status") not in {"INVALIDATED", "FULLY_MITIGATED"}
        quality_gap = any(isinstance(g, dict) and g.get("type") == expected and float(g.get("score", 0) or 0) >= 4 and g.get("status") not in {"FULLY_MITIGATED", "INVALIDATED"} for g in gaps)
        zone = quality_block or quality_gap
        _record(components, evidence, "entry_zone_quality", 15, zone, agree, disagree,
                "AGREES: qualified fresh directional FVG/OB is available.",
                "DISAGREES: no qualified fresh directional FVG/OB is available.")

        preferred_location = "discount" if direction == "BUY" else "premium"
        location = setup_values.get("location") == preferred_location
        _record(components, evidence, "dealing_range_location", 10, location, agree, disagree,
                f"AGREES: price is in preferred {preferred_location} dealing-range location.",
                f"DISAGREES: price is not in preferred {preferred_location} location.")

        displacement = bool(setup_values.get("displacement")) or bool(entry_values.get("displacement"))
        _record(components, evidence, "displacement", 10, displacement, agree, disagree,
                "AGREES: displacement confirms directional intent.",
                "DISAGREES: displacement confirmation is missing.")

        entry_confirmation = _directional(trends.get(entry_tf), direction) or _directional((entry_values.get("structure") or {}).get("bias"), direction)
        _record(components, evidence, "entry_confirmation", 10, entry_confirmation, agree, disagree,
                f"AGREES: {entry_tf} supplies directional entry confirmation.",
                f"DISAGREES: {entry_tf} lacks directional entry confirmation.")

        kz = ict.get("kill_zone", {}) if isinstance(ict.get("kill_zone"), dict) else {}
        _record(components, evidence, "timing", 5, kz.get("status") == "ACTIVE", agree, disagree,
                f"AGREES: active ICT timing window ({kz.get('name', 'unknown')}).",
                "DISAGREES: outside an ICT timing window.")

        amd_complete = bool(amd.get("complete")) and bool(amd.get("manipulation"))
        _record(components, evidence, "amd_sequence", 5, amd_complete, agree, disagree,
                "AGREES: AMD manipulation phase is confirmed before directional delivery.",
                "DISAGREES: AMD manipulation sequence is not confirmed.")

        raw_score, raw_max = _weighted_score(components, evidence)
        hard_requirements = {"directional_context": True, "structure_confirmation": shift_ok, "entry_zone_quality": zone, "entry_confirmation": entry_confirmation}

    elif strategy == "AMD":
        setup = setup_values
        amd = setup.get("amd", {}) if isinstance(setup.get("amd"), dict) else {}
        directional_shift = str(setup.get("structure_shift") or "").startswith(expected)
        fvg_or_ob = any(isinstance(g, dict) and g.get("type") == expected and g.get("classification") in {"QUALIFIED_FVG", "TRADEABLE_FVG"} and g.get("price_in_zone") for g in setup.get("fair_value_gaps", []) or []) or bool((setup.get("order_block") or {}).get("price_in_zone"))
        retracement = fvg_or_ob
        factors = [
            ("accumulation", 10, bool(amd.get("accumulation")), "AGREES: accumulation phase identified.", "DISAGREES: accumulation evidence is missing."),
            ("manipulation", 20, bool(amd.get("manipulation")), "AGREES: manipulation/liquidity raid is identified.", "DISAGREES: manipulation phase is not confirmed."),
            ("structure_shift", 20, directional_shift, "AGREES: directional structure shift confirms the intended move.", "DISAGREES: directional structure shift is missing."),
            ("displacement", 15, bool(setup.get("displacement")), "AGREES: displacement confirms distribution intent.", "DISAGREES: displacement confirmation is missing."),
            ("entry_zone", 15, fvg_or_ob, "AGREES: actionable FVG/OB entry zone is present.", "DISAGREES: no actionable FVG/OB entry zone is present."),
            ("retracement", 10, retracement, "AGREES: price has retraced into the actionable zone.", "DISAGREES: retracement into the actionable zone is not confirmed."),
            ("entry_confirmation", 10, _directional(trends.get(entry_tf), direction) or _directional((entry_values.get("structure") or {}).get("bias"), direction), "AGREES: entry timeframe confirms direction.", "DISAGREES: entry timeframe confirmation is missing."),
        ]
        for name, pts, cond, yes, no in factors:
            _record(components, evidence, name, pts, cond, agree, disagree, yes, no)
        raw_score, raw_max = _weighted_score(components, evidence)
        hard_requirements = {"directional_context": context_aligned, "accumulation": bool(amd.get("accumulation")), "manipulation": bool(amd.get("manipulation")), "structure_shift": directional_shift, "displacement": bool(setup.get("displacement")), "entry_zone": fvg_or_ob, "retracement": retracement}

    elif strategy == "TREND_FOLLOWING":
        ema20 = float(trend_ind.get("ema_20", 0) or 0); ema50 = float(trend_ind.get("ema_50", 0) or 0); ema200 = float(trend_ind.get("ema_200", 0) or 0)
        close = float(trend_ind.get("last_close", 0) or 0); adx = float(trend_ind.get("adx_14", 0) or 0); atr = float(trend_ind.get("atr_14", 0) or 0)
        ema_aligned = close > ema20 > ema50 > ema200 if direction == "BUY" else close < ema20 < ema50 < ema200
        _record(components, evidence, "ema_structure", 30, ema_aligned, agree, disagree,
                "AGREES: price and EMA stack form a coherent directional trend.", "DISAGREES: EMA trend structure is incomplete.")
        components["trend_strength"] = 25; evidence["trend_strength"] = adx >= 20
        (agree if adx >= 20 else disagree).append(f"{'AGREES' if adx >= 20 else 'DISAGREES'}: ADX={adx:.1f}.")
        lower_align = _directional(trends.get(setup_tf), direction) and _directional(trends.get(entry_tf), direction)
        _record(components, evidence, "lower_timeframe_alignment", 15, lower_align, agree, disagree,
                "AGREES: setup and entry trends confirm the higher-timeframe direction.", "DISAGREES: lower-timeframe trend alignment is incomplete.")
        pullback = bool(atr > 0 and abs(close - ema20) <= 1.5 * atr)
        _record(components, evidence, "price_location", 10, pullback, agree, disagree,
                "AGREES: price is not excessively extended from EMA20 relative to ATR.", "DISAGREES: price is too extended from EMA20 for a fresh trend entry.")
        _record(components, evidence, "htf_context_quality", 20, context_aligned, agree, disagree,
                "AGREES: H4/D1 context supports the trend.", "DISAGREES: higher-timeframe context is mixed.")
        raw_score, raw_max = _weighted_score(components, evidence)
        hard_requirements = {"ema_structure": ema_aligned, "trend_strength": adx >= 20, "lower_timeframe_alignment": lower_align, "htf_alignment": context_aligned}

    elif strategy == "MOMENTUM":
        rsi = float(setup_ind.get("rsi_14", 50) or 50); hist = float(setup_ind.get("macd_histogram", 0) or 0); macd = float(setup_ind.get("macd", 0) or 0); signal = float(setup_ind.get("macd_signal", 0) or 0)
        setup_trend = _directional(trends.get(setup_tf), direction); entry_trend = _directional(trends.get(entry_tf), direction)
        rsi_ok = 52 <= rsi <= 70 if direction == "BUY" else 30 <= rsi <= 48
        macd_ok = (macd > signal and hist > 0) if direction == "BUY" else (macd < signal and hist < 0)
        _record(components, evidence, "momentum_regime", 20, setup_trend, agree, disagree,
                "AGREES: setup timeframe has directional momentum regime.", "DISAGREES: setup timeframe momentum regime is unclear.")
        _record(components, evidence, "rsi_quality", 20, rsi_ok, agree, disagree,
                f"AGREES: RSI={rsi:.1f} is directional without being at an extreme.", f"DISAGREES: RSI={rsi:.1f} is not in the preferred momentum zone.")
        _record(components, evidence, "macd_confirmation", 25, macd_ok, agree, disagree,
                "AGREES: MACD line/signal and histogram confirm the same direction.", "DISAGREES: MACD confirmation is incomplete.")
        _record(components, evidence, "entry_confirmation", 15, entry_trend, agree, disagree,
                "AGREES: entry timeframe confirms momentum direction.", "DISAGREES: entry timeframe is not aligned.")
        _record(components, evidence, "htf_context", 20, context_aligned, agree, disagree,
                "AGREES: higher-timeframe context supports momentum direction.", "DISAGREES: higher-timeframe context is not aligned.")
        raw_score, raw_max = _weighted_score(components, evidence)
        hard_requirements = {"momentum_regime": setup_trend, "rsi_quality": rsi_ok, "macd_confirmation": macd_ok, "entry_confirmation": entry_trend}

    elif strategy == "BREAKOUT":
        breakout_shift = str(setup_values.get("structure_shift") or "").startswith(expected)
        displacement = bool(setup_values.get("displacement"))
        _record(components, evidence, "range_break_structure", 25, breakout_shift, agree, disagree,
                "AGREES: structural break is aligned with the selected direction.", "DISAGREES: structural breakout confirmation is missing.")
        _record(components, evidence, "displacement", 25, displacement, agree, disagree,
                "AGREES: breakout candle has displacement.", "DISAGREES: breakout displacement is missing.")
        _record(components, evidence, "setup_trend", 15, _directional(trends.get(setup_tf), direction), agree, disagree,
                "AGREES: setup trend supports the breakout.", "DISAGREES: setup trend does not support the breakout.")
        _record(components, evidence, "entry_confirmation", 15, _directional(trends.get(entry_tf), direction), agree, disagree,
                "AGREES: entry timeframe confirms the breakout direction.", "DISAGREES: entry timeframe confirmation is missing.")
        _record(components, evidence, "htf_context", 20, context_aligned, agree, disagree,
                "AGREES: higher-timeframe context supports the breakout.", "DISAGREES: higher-timeframe context is mixed.")
        raw_score, raw_max = _weighted_score(components, evidence)
        hard_requirements = {"range_break_structure": breakout_shift, "displacement": displacement, "setup_trend": _directional(trends.get(setup_tf), direction), "entry_confirmation": _directional(trends.get(entry_tf), direction)}

    elif strategy == "MEAN_REVERSION":
        close = float(setup_ind.get("last_close", 0) or 0); upper = float(setup_ind.get("bollinger_upper", 0) or 0); lower = float(setup_ind.get("bollinger_lower", 0) or 0); middle = float(setup_ind.get("bollinger_middle", 0) or 0); rsi = float(setup_ind.get("rsi_14", 50) or 50); adx = float(setup_ind.get("adx_14", 0) or 0)
        extreme = close <= lower if direction == "BUY" else close >= upper
        rsi_extreme = rsi <= 35 if direction == "BUY" else rsi >= 65
        range_regime = adx < 25
        mean_target_available = middle > 0 and ((middle > close) if direction == "BUY" else (middle < close))
        _record(components, evidence, "range_regime", 25, range_regime, agree, disagree,
                f"AGREES: ADX={adx:.1f} indicates a sufficiently non-trending regime for mean reversion.",
                f"DISAGREES: ADX={adx:.1f} indicates too much trend strength for mean reversion.")
        _record(components, evidence, "band_extreme", 30, extreme, agree, disagree,
                "AGREES: price has reached a Bollinger extreme.", "DISAGREES: price has not reached the required Bollinger extreme.")
        _record(components, evidence, "rsi_extreme", 20, rsi_extreme, agree, disagree,
                f"AGREES: RSI={rsi:.1f} confirms an exhaustion extreme.", "DISAGREES: RSI does not confirm exhaustion.")
        _record(components, evidence, "mean_target", 15, mean_target_available, agree, disagree,
                "AGREES: mean target is on the expected side of entry.", "DISAGREES: mean target is unavailable or on the wrong side.")
        _record(components, evidence, "location_context", 10, setup_values.get("location") in {"premium", "discount"}, agree, disagree,
                "AGREES: dealing-range location is defined.", "DISAGREES: dealing-range location is not defined.")
        raw_score, raw_max = _weighted_score(components, evidence)
        hard_requirements = {"range_regime": range_regime, "band_extreme": extreme, "rsi_extreme": rsi_extreme, "mean_target": mean_target_available}

    else:
        raw_score, raw_max = 0, 0
        hard_requirements = {}

    score = max(0, min(100, int(raw_score)))
    configured_minimum = cfg["minimum"]
    try:
        profile_minimum = int(getattr(profile, "minimum_score", configured_minimum))
    except (TypeError, ValueError):
        profile_minimum = configured_minimum
    # Profile minimums are expressed on the normalized 0-100 scale now.
    minimum_score = max(0, min(100, profile_minimum))
    hard_failed = [name for name, ok in hard_requirements.items() if not ok]
    ready = score >= minimum_score and not hard_failed

    daily_bias = str(trends.get("D1") or "unknown").lower()
    daily_expected = "bullish" if direction == "BUY" else "bearish"
    daily_aligned = daily_bias == daily_expected
    countertrend = daily_bias in {"bullish", "bearish"} and not daily_aligned
    countertrend_allowed = bool(countertrend and score >= cfg["countertrend"] and not hard_failed)

    return {
        "score": score,
        "maximum_score": 100,
        "raw_score": sum(points for name, points in components.items() if evidence.get(name, False)),
        "raw_maximum_score": raw_max,
        "minimum_score": minimum_score,
        "ready": bool(ready),
        "score_passed": bool(score >= minimum_score),
        "hard_requirements": hard_requirements,
        "hard_failures": hard_failed,
        "components": {name: {"points": points, "earned": bool(evidence.get(name, False)), "earned_points": points if evidence.get(name, False) else 0} for name, points in components.items()},
        "strategy": strategy,
        "agree": agree,
        "disagree": disagree,
        "summary": f"{strategy} quality {score}/100 (minimum {minimum_score}) - {len(agree)} supporting checks and {len(disagree)} conflicting checks.",
        "supporting_evidence": {"setup_timeframe": setup_tf, "entry_timeframe": entry_tf, "smc": setup_values},
        "htf_alignment": {"daily_bias": daily_bias, "direction": direction, "aligned": daily_aligned, "countertrend": countertrend, "countertrend_allowed": countertrend_allowed},
    }
