from __future__ import annotations

from typing import Any


def _directional(value: Any, direction: str) -> bool:
    expected = "bullish" if direction == "BUY" else "bearish"
    return str(value or "").lower() == expected


def evaluate_confluence(
    direction: str,
    trends: dict[str, str],
    indicator_data: dict[str, dict[str, Any]],
    smc_data: dict[str, dict[str, Any]],
    profile=None,
    strategy_name: str = "SMC",
) -> dict[str, Any]:
    """Score the selected strategy using strategy-specific evidence.

    The previous scorer always required SMC sweep/structure/OB/FVG evidence,
    which unintentionally blocked non-SMC strategies. This implementation
    keeps one 10-point scale but evaluates the requirements of the selected
    strategy family. No individual SMC concept is globally mandatory.
    """
    strategy = str(strategy_name or "SMC").upper()
    expected = "bullish" if direction == "BUY" else "bearish"
    agree: list[str] = []
    disagree: list[str] = []
    score = 0

    context_tf = getattr(profile, "context_timeframe", "H4")
    trend_tf = getattr(profile, "trend_timeframe", "H1")
    setup_tf = getattr(profile, "setup_timeframe", "M15")
    entry_tf = getattr(profile, "entry_timeframe", "M5")

    # Common higher-timeframe context: two points.
    if _directional(trends.get(context_tf), direction) and _directional(trends.get(trend_tf), direction):
        score += 2
        agree.append(f"AGREES: {context_tf}/{trend_tf} context aligns with {direction}.")
    else:
        disagree.append(f"DISAGREES: {context_tf}/{trend_tf} context is not fully aligned.")

    setup_values = smc_data.get(setup_tf, {}) or {}
    entry_values = smc_data.get(entry_tf, {}) or {}
    setup_ind = indicator_data.get(setup_tf, {}) or {}
    trend_ind = indicator_data.get(trend_tf, {}) or {}
    entry_ind = indicator_data.get(entry_tf, {}) or {}

    if strategy == "SMC":
        expected_sweep = "sell_side_liquidity_sweep" if direction == "BUY" else "buy_side_liquidity_sweep"
        if setup_values.get("liquidity_sweep") == expected_sweep:
            score += 2
            agree.append(f"AGREES: {setup_tf} liquidity sweep supports {direction}.")
        else:
            disagree.append(f"DISAGREES: {setup_tf} has no directional liquidity sweep.")

        expected_shifts = {"bullish_BOS", "bullish_CHoCH"} if direction == "BUY" else {"bearish_BOS", "bearish_CHoCH"}
        shift = str(setup_values.get("structure_shift") or "")
        if shift in expected_shifts or shift.startswith(f"{expected}_CHoCH"):
            score += 2
            agree.append(f"AGREES: {setup_tf} BOS/CHoCH supports {direction}.")
        else:
            disagree.append(f"DISAGREES: {setup_tf} has no directional BOS/CHoCH.")

        block = setup_values.get("order_block")
        gaps = setup_values.get("fair_value_gaps", []) or []
        quality_block = isinstance(block, dict) and block.get("type") == expected and float(block.get("score", 0) or 0) >= 5
        quality_gap = any(isinstance(g, dict) and g.get("type") == expected and float(g.get("score", 0) or 0) >= 4 for g in gaps)
        # A zone is supportive evidence, not a universal requirement. The 
        # setup engine is allowed to use other SMC entry models.
        if quality_block or quality_gap:
            score += 1
            agree.append(f"AGREES: qualified {expected} SMC zone is present.")
        else:
            disagree.append("INFO: no qualified FVG/OB; another supported SMC setup may still qualify.")

        if setup_values.get("location") == ("discount" if direction == "BUY" else "premium"):
            score += 1
            agree.append(f"AGREES: price is in preferred {('discount' if direction == 'BUY' else 'premium')} location.")
        else:
            disagree.append("DISAGREES: price is not in preferred premium/discount location.")

    elif strategy == "TREND_FOLLOWING":
        ema = float(trend_ind.get("ema_20", 0) or 0), float(trend_ind.get("ema_50", 0) or 0), float(trend_ind.get("ema_200", 0) or 0)
        close = float(trend_ind.get("last_close", 0) or 0)
        adx = float(trend_ind.get("adx_14", 0) or 0)
        ema_ok = close > ema[0] > ema[1] > ema[2] if direction == "BUY" else close < ema[0] < ema[1] < ema[2]
        if ema_ok:
            score += 3
            agree.append(f"AGREES: {trend_tf} EMA20/50/200 alignment supports {direction}.")
        else:
            disagree.append(f"DISAGREES: {trend_tf} EMA alignment does not support {direction}.")
        if adx >= 20:
            score += 2
            agree.append(f"AGREES: {trend_tf} ADX={adx:.1f} confirms directional strength.")
        else:
            disagree.append(f"DISAGREES: {trend_tf} ADX={adx:.1f} is below 20.")
        if _directional(trends.get(setup_tf), direction) and _directional(trends.get(entry_tf), direction):
            score += 2
            agree.append(f"AGREES: {setup_tf}/{entry_tf} trend alignment supports continuation.")
        else:
            disagree.append("DISAGREES: lower-timeframe trend alignment is incomplete.")

    elif strategy == "MOMENTUM":
        rsi = float(setup_ind.get("rsi_14", 50) or 50)
        hist = float(setup_ind.get("macd_histogram", 0) or 0)
        rsi_ok = rsi >= 55 if direction == "BUY" else rsi <= 45
        macd_ok = hist > 0 if direction == "BUY" else hist < 0
        if rsi_ok:
            score += 2
            agree.append(f"AGREES: {setup_tf} RSI={rsi:.1f} supports {direction} momentum.")
        else:
            disagree.append(f"DISAGREES: {setup_tf} RSI={rsi:.1f} is not at the configured momentum threshold.")
        if macd_ok:
            score += 2
            agree.append("AGREES: MACD histogram confirms directional momentum.")
        else:
            disagree.append("DISAGREES: MACD histogram is not aligned.")
        if _directional(trends.get(setup_tf), direction):
            score += 2
            agree.append(f"AGREES: {setup_tf} directional trend agrees with momentum.")
        else:
            disagree.append(f"DISAGREES: {setup_tf} trend is not aligned with momentum.")
        if _directional(trends.get(entry_tf), direction):
            score += 1
            agree.append(f"AGREES: {entry_tf} trend confirms momentum direction.")
        else:
            disagree.append(f"DISAGREES: {entry_tf} confirmation trend is not aligned.")

    elif strategy == "BREAKOUT":
        candles = []
        # Reuse SMC data's local context when available; the strategy engine
        # itself has already established the breakout state.
        if _directional(trends.get(setup_tf), direction):
            score += 2
            agree.append(f"AGREES: {setup_tf} trend aligns with breakout direction.")
        else:
            disagree.append(f"DISAGREES: {setup_tf} trend is not aligned.")
        structure_shift = str(setup_values.get("structure_shift") or "")
        if (direction == "BUY" and structure_shift.startswith("bullish")) or (direction == "SELL" and structure_shift.startswith("bearish")):
            score += 2
            agree.append("AGREES: structure break supports the breakout.")
        else:
            disagree.append("INFO: strategy-level breakout confirmation is being used; SMC BOS is not mandatory.")
        atr = float(setup_ind.get("atr_14", 0) or 0)
        if atr > 0:
            score += 2
            agree.append(f"AGREES: ATR={atr:.6f} provides a volatility basis for the breakout.")
        else:
            disagree.append("DISAGREES: ATR unavailable for breakout risk/target context.")
        if _directional(trends.get(entry_tf), direction):
            score += 1
            agree.append(f"AGREES: {entry_tf} confirms breakout direction.")
        else:
            disagree.append(f"DISAGREES: {entry_tf} confirmation is not aligned.")

    elif strategy == "MEAN_REVERSION":
        close = float(setup_ind.get("last_close", 0) or 0)
        upper = float(setup_ind.get("bollinger_upper", 0) or 0)
        lower = float(setup_ind.get("bollinger_lower", 0) or 0)
        rsi = float(setup_ind.get("rsi_14", 50) or 50)
        band_ok = close <= lower if direction == "BUY" else close >= upper
        rsi_ok = rsi <= 35 if direction == "BUY" else rsi >= 65
        if band_ok:
            score += 3
            agree.append("AGREES: price is at the configured Bollinger extreme.")
        else:
            disagree.append("DISAGREES: price is not at the required Bollinger extreme.")
        if rsi_ok:
            score += 2
            agree.append(f"AGREES: RSI={rsi:.1f} is at the configured extreme.")
        else:
            disagree.append(f"DISAGREES: RSI={rsi:.1f} is not extreme enough.")
        if not _directional(trends.get(setup_tf), direction):
            score += 1
            agree.append("AGREES: setup timeframe is not strongly trending, which supports mean reversion.")
        else:
            disagree.append("DISAGREES: setup timeframe remains directional; mean-reversion risk is elevated.")
        if setup_values.get("location") in {"premium", "discount"}:
            score += 1
            agree.append("AGREES: price has a defined dealing-range location.")

    # Common momentum/EMA confirmation is capped at two points so the scale
    # stays exactly 0-10 for every strategy family.
    def common_indicator_points(values: dict[str, Any]) -> int:
        if values.get("status") != "ready":
            return 0
        hist = float(values.get("macd_histogram", 0) or 0)
        rsi = float(values.get("rsi_14", 50) or 50)
        momentum = (hist >= 0 and rsi >= 50) if direction == "BUY" else (hist <= 0 and rsi <= 50)
        return 1 if momentum else 0

    if strategy in {"TREND_FOLLOWING", "MOMENTUM", "BREAKOUT", "MEAN_REVERSION"}:
        points = common_indicator_points(entry_ind)
        if points:
            score += 1
            agree.append(f"AGREES: {entry_tf} momentum is directionally supportive.")
        else:
            disagree.append(f"DISAGREES: {entry_tf} momentum is mixed.")

    score = max(0, min(10, int(score)))
    minimum_score = int(getattr(profile, "minimum_score", 7) or 7)
    return {
        "score": score,
        "maximum_score": 10,
        "minimum_score": minimum_score,
        "ready": score >= minimum_score,
        "strategy": strategy,
        "agree": agree,
        "disagree": disagree,
        "summary": f"{strategy} confluence {score}/10 - {len(agree)} supporting checks and {len(disagree)} conflicting checks.",
        "supporting_evidence": {
            "setup_timeframe": setup_tf,
            "entry_timeframe": entry_tf,
            "smc": setup_values,
        },
    }
