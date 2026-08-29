from __future__ import annotations

from typing import Any
from .context import build_market_context
from .confluence import evaluate_confluence
from .strategy import identify_setup
from .strategy_engine import select_strategy
from .smc import ZoneRegistry
from .data_quality import assess_candles
from .session_manager import current_session


def _support_resistance(candles: list[dict[str, Any]], timeframe: str) -> dict[str, Any]:
    from .smc import _swing_points
    highs, lows = _swing_points(candles)
    current = float(candles[-1].get("close", 0) or 0) if candles else 0
    latest_high_idx = highs[-1][0] if highs else None
    latest_low_idx = lows[-1][0] if lows else None
    resistance = [{"price": p, "type": "resistance", "timeframe": timeframe, "strength": "major" if i == latest_high_idx else "intermediate", "active": p > current} for i, p in highs]
    support = [{"price": p, "type": "support", "timeframe": timeframe, "strength": "major" if i == latest_low_idx else "intermediate", "active": p < current} for i, p in lows]
    return {"resistance": resistance, "support": support}


def analyze_structure(timeframes: dict[str, list[dict[str, Any]]], profile=None, registry: ZoneRegistry | None = None) -> dict[str, Any]:
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
    # The largest required indicator warm-up is 200 candles. Keeping that as a
    # hard data gate prevents recursive indicators from becoming actionable
    # merely because a shorter series can produce a numeric result.
    quality = {
        tf: assess_candles(timeframes.get(tf, []), tf, minimum_candles=200, require_closed=True)
        for tf in required
    }
    blockers = {tf: result for tf, result in quality.items() if result.get("status") != "fresh"}
    if blockers:
        return {
            "valid": False,
            "decision": "BLOCKED_BY_DATA",
            "reason": "Required market history is missing, insufficient, invalid, or stale.",
            "trends": {},
            "indicators": {},
            "smc": {},
            "data_quality": quality,
        }

    windows = {tf: profile.analysis_windows(tf) for tf in timeframes}
    context = build_market_context(timeframes, windows=windows, registry=registry)
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

    strategy_result = select_strategy(
        timeframes=timeframes,
        indicators=indicators,
        trends=trends,
        structure=smc_structure,
        preferred=getattr(profile, "strategy_mode", "AUTO"),
        setup_tf=setup_tf,
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
    confluence = evaluate_confluence(
        selected.get("direction") or expected_direction or "BUY",
        trends,
        indicators,
        smc,
        profile=profile,
        strategy_name=selected.get("name") or "SMC",
    )
    score = float(confluence.get("score", 0) or 0)
    minimum_score = int(profile.minimum_score)
    confluence = {**confluence, "minimum_score": minimum_score, "score_passed": score >= minimum_score}

    session_context = current_session()
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
        "session_context": session_context,
        "setup_assessment": setup_assessment,
        "confluence": confluence,
        "data_quality": quality,
        "indicator_reasons": [f"{tf}: RSI={float(v.get('rsi_14', 0) or 0):.1f}, MACD hist={float(v.get('macd_histogram', 0) or 0):.6f}, ADX={float(v.get('adx_14', 0) or 0):.1f}" for tf, v in indicators.items() if v.get("readiness", {}).get("rsi_14")],
        "smc_reasons": [f"{tf}: liquidity={v.get('liquidity_sweep') or 'none'}, shift={v.get('structure_shift') or 'none'}, FVGs={len(v.get('fair_value_gaps', []))}, OB={'present' if v.get('order_block') else 'none'}, location={v.get('location', 'unknown')}" for tf, v in smc.items()],
        "stages": {
            "higher_timeframe_context": {context_tf: trends.get(context_tf), trend_tf: trends.get(trend_tf)},
            "market_structure": {tf: v.get("structure", {}).get("bias", "unknown") for tf, v in smc.items()},
            "support_resistance": sr,
            "entry_model": selected.get("name"),
            "strategy_selection": strategy_result,
        },
    }
