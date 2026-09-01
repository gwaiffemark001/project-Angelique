from __future__ import annotations

from typing import Any
from .context import build_market_context
from .confluence import evaluate_confluence
from .strategy import identify_setup
from .strategy_engine import select_strategy
from .smc import ZoneRegistry
from .data_quality import assess_candles, blocker_for
from .indicators import required_history
from .session_levels import current_session


def _support_resistance(candles: list[dict[str, Any]], timeframe: str) -> dict[str, Any]:
    from .smc import _swing_points
    highs, lows = _swing_points(candles)
    current = float(candles[-1].get("close", 0) or 0) if candles else 0
    latest_high_idx = highs[-1][0] if highs else None
    latest_low_idx = lows[-1][0] if lows else None
    resistance = [{"price": p, "type": "resistance", "timeframe": timeframe, "strength": "major" if i == latest_high_idx else "intermediate", "active": p > current} for i, p in highs]
    support = [{"price": p, "type": "support", "timeframe": timeframe, "strength": "major" if i == latest_low_idx else "intermediate", "active": p < current} for i, p in lows]
    return {"resistance": resistance, "support": support}


def analyze_structure(
    timeframes: dict[str, list[dict[str, Any]]],
    profile=None,
    registry: ZoneRegistry | None = None,
    *,
    symbol: str = "",
    specs: dict[str, Any] | None = None,
    trades_24_7: bool = False,
) -> dict[str, Any]:
    """Run the deterministic strategy analysis pipeline.

    A profile is required for production analysis because it defines the
    strategy timeframes and minimum-score gate. Incomplete history is a hard
    data block, not a low-confidence signal.
    """
    if profile is None:
        return {"valid": False, "decision": "BLOCKED_BY_DATA", "reason": "A TradingProfile is required for production analysis.", "trends": {}, "indicators": {}, "smc": {}}
    if not timeframes:
        return {"valid": False, "decision": "BLOCKED_BY_DATA", "reason": "No timeframe candles were provided.", "trends": {}, "indicators": {}, "smc": {}}

    required = tuple(profile.analysis_required_timeframes)
    # Two distinct concerns, deliberately kept apart:
    #
    #   1. DATA QUALITY asks "did the broker give us the history this profile
    #      asked for?" -- so the gate is the profile's own requested depth.
    #      Very long timeframes (W1) legitimately have less history available.
    #   2. INDICATOR READINESS asks "is this particular indicator trustworthy
    #      on this series?" -- handled per indicator by `indicators.snapshot`,
    #      which returns None until its own warm-up is satisfied.
    #
    # Collapsing the two would block all W1 analysis merely because a 200-EMA
    # cannot be computed there, even though W1 is only used for trend bias.
    quality = {
        tf: assess_candles(
            timeframes.get(tf, []), tf,
            minimum_candles=min(profile.candle_count(tf), required_history()),
            require_closed=True, symbol=symbol, trades_24_7=trades_24_7,
        )
        for tf in required
    }
    blockers = {tf: result for tf, result in quality.items() if not result.get("tradeable")}
    if blockers:
        codes = sorted({blocker_for(result) for result in blockers.values() if blocker_for(result)})
        return {
            "valid": False,
            "decision": "BLOCKED_BY_DATA",
            "blocker_codes": codes,
            "reason": "; ".join(
                f"{tf}: {result.get('reason')}" for tf, result in sorted(blockers.items())
            ),
            "minimum_candles_required": {tf: min(profile.candle_count(tf), required_history())
                                         for tf in required},
            "trends": {},
            "indicators": {},
            "smc": {},
            "data_quality": quality,
        }

    windows = {tf: profile.analysis_windows(tf) for tf in timeframes}
    context = build_market_context(timeframes, windows=windows, registry=registry,
                                   trades_24_7=trades_24_7)
    trends, indicators, smc = context.trends, context.indicators, context.smc
    context_tf = profile.context_timeframe
    trend_tf = profile.trend_timeframe
    setup_tf = profile.setup_timeframe
    entry_tf = profile.entry_timeframe

    expected_direction = "BUY" if trends.get(trend_tf) == "bullish" else "SELL" if trends.get(trend_tf) == "bearish" else None
    smc_setup = smc.get(setup_tf, {})
    smc_entry = smc.get(entry_tf, {})
    smc_assessment = identify_setup(expected_direction, smc_setup, smc_entry) if expected_direction else {"model": "UNSUPPORTED", "complete": False, "missing": ["directional bias"], "reason": "No directional trend on the primary timeframe."}
    if isinstance(smc_setup, dict):
        smc_assessment = {**smc_assessment, "target_liquidity": smc_setup.get("target_liquidity"), "support_resistance": smc_setup.get("support_resistance"), "structure": smc_setup.get("structure"), "location": smc_setup.get("location")}
    smc_structure = {
        "decision": "WAIT",
        "direction": expected_direction,
        "setup_assessment": smc_assessment,
        "smc": smc,
    }
    if smc_assessment.get("complete"):
        smc_structure["decision"] = "BUY_PLAN_READY" if expected_direction == "BUY" else "SELL_PLAN_READY"

    session_context = current_session(trades_24_7=trades_24_7)
    strategy_result = select_strategy(
        timeframes=timeframes,
        indicators=indicators,
        trends=trends,
        structure=smc_structure,
        smc=smc,
        session=session_context,
        profile=profile,
        preferred=getattr(profile, "strategy_mode", "AUTO"),
    )
    selected = strategy_result["selected"]
    decision = selected.get("state")
    if selected.get("direction") in {"BUY", "SELL"} and decision == "READY":
        final_decision = "BUY_PLAN_READY" if selected["direction"] == "BUY" else "SELL_PLAN_READY"
    elif decision == "WAIT":
        final_decision = "WAIT"
    else:
        final_decision = "NO_SETUP"

    sr = {tf: _support_resistance(c[-windows.get(tf, {}).get("support_resistance", len(c)):], tf) for tf, c in timeframes.items() if c}
    # `confluence` is now a VIEW of the selected strategy's own evaluation, not
    # a second competing score. It is handed the exact evaluation object the
    # selector ranked, so the two can never disagree.
    from .strategy_evaluation import StrategyEvaluation
    selected_meta_for_view = (selected.get("metadata") or {}).get("evaluation")
    confluence = evaluate_confluence(
        selected.get("direction") or expected_direction or "BUY",
        trends,
        indicators,
        smc,
        profile=profile,
        strategy_name=selected.get("name") or "SMC",
        session=session_context,
        timeframes_data=timeframes,
    )
    score = float(confluence.get("score", 0) or 0)
    minimum_score = int(confluence.get("minimum_score") or getattr(profile, "minimum_quality_score", 70))
    confluence = {**confluence, "minimum_score": minimum_score, "score_passed": score >= minimum_score}
    selected_meta = selected.get("metadata") or {}
    setup_assessment = selected_meta.get("setup") if isinstance(selected_meta, dict) else None
    if not isinstance(setup_assessment, dict):
        setup_assessment = smc_assessment

    return {
        "valid": True,
        "direction": selected.get("direction") or expected_direction,
        "decision": final_decision,
        "reason": ("Strategy selected: " + str(selected.get("name")) + ". " + " ".join(selected.get("reasons", []))) if selected.get("reasons") else selected.get("state", "WAIT"),
        "trends": trends,
        "indicators": indicators,
        "smc": smc,
        "strategy": strategy_result,
        "strategy_name": selected.get("name"),
        "strategy_quality_score": score,
        "strategy_quality_score_meaning": (
            "Completeness of the selected strategy's own setup definition on a 0-100 scale. "
            "It is NOT a win probability and no probability is implied."
        ),
        "minimum_quality_score": minimum_score,
        "hard_requirements_failed": confluence.get("failed_hard_requirements", []),
        "session_context": session_context,
        "setup_assessment": setup_assessment,
        "confluence": confluence,
        "data_quality": quality,
        "indicator_reasons": [f"{tf}: RSI={float(v.get('rsi_14', 0) or 0):.1f}, MACD hist={float(v.get('macd_histogram', 0) or 0):.6f}, ADX={float(v.get('adx_14', 0) or 0):.1f}" for tf, v in indicators.items() if v.get("readiness", {}).get("rsi_14")],
        "smc_reasons": [
            f"{tf}: liquidity={(v.get('liquidity_sweep') or {}).get('pool', {}).get('kind', 'none')}, "
            f"shift={v.get('structure_shift') or 'none'}, "
            f"tradeable FVGs={len(v.get('tradeable_gaps', []))}/{len(v.get('fair_value_gaps', []))}, "
            f"OB={'present' if v.get('order_block') else 'none'}, "
            f"location={v.get('location', 'unknown')}, "
            f"AMD={(v.get('amd') or {}).get('phase', 'unclear')}"
            for tf, v in smc.items()
        ],
        "stages": {
            "higher_timeframe_context": {context_tf: trends.get(context_tf), trend_tf: trends.get(trend_tf)},
            "market_structure": {tf: (v.get("market_structure") or {}).get("bias", "unknown") for tf, v in smc.items()},
            "support_resistance": sr,
            "entry_model": selected.get("name"),
            "strategy_selection": strategy_result,
        },
    }
