from __future__ import annotations

from typing import Any
from .context import build_market_context
from .confluence import evaluate_confluence
from .strategy import identify_setup
from .strategy_engine import select_strategy
from .smc import ZoneRegistry


def _support_resistance(candles: list[dict[str, Any]], timeframe: str) -> dict[str, Any]:
    from .smc import _swing_points
    highs, lows = _swing_points(candles)
    current = float(candles[-1].get("close", 0) or 0) if candles else 0
    resistance = [{"price": p, "type": "resistance", "timeframe": timeframe, "strength": "major" if i == highs[-1][0] else "intermediate", "active": p > current} for i,p in highs]
    support = [{"price": p, "type": "support", "timeframe": timeframe, "strength": "major" if i == lows[-1][0] else "intermediate", "active": p < current} for i,p in lows]
    return {"resistance":resistance,"support":support}


def analyze_structure(timeframes: dict[str,list[dict[str,Any]]], profile=None, registry: ZoneRegistry|None=None) -> dict[str,Any]:
    if not timeframes:
        return {"valid": False, "decision":"BLOCKED_BY_DATA", "reason":"No timeframe candles were provided.", "trends":{}, "indicators":{}, "smc":{}}
    windows={tf:profile.analysis_windows(tf) for tf in timeframes} if profile is not None else {}
    context=build_market_context(timeframes, windows=windows, registry=registry)
    trends, indicators, smc=context.trends, context.indicators, context.smc
    context_tf=getattr(profile,"context_timeframe","H4")
    trend_tf=getattr(profile,"trend_timeframe","H1")
    setup_tf=getattr(profile,"setup_timeframe","M15")
    entry_tf=getattr(profile,"entry_timeframe","M5")
    # Do not require all HTF frames to agree. The active mode chooses which
    # context matters; conflicting frames become evidence and may result in WAIT.
    expected_direction="BUY" if trends.get(trend_tf)=="bullish" else "SELL" if trends.get(trend_tf)=="bearish" else None
    smc_setup=smc.get(setup_tf,{})
    smc_entry=smc.get(entry_tf,{})
    smc_assessment=identify_setup(expected_direction, smc_setup, smc_entry) if expected_direction else {"model":"UNSUPPORTED","complete":False,"missing":["directional bias"],"reason":"No directional trend on the primary timeframe."}
    if isinstance(smc_setup, dict):
        smc_assessment = {
            **smc_assessment,
            "target_liquidity": smc_setup.get("target_liquidity"),
            "support_resistance": smc_setup.get("support_resistance"),
            "structure": smc_setup.get("structure"),
            "location": smc_setup.get("location"),
        }
    smc_structure={"decision":"WAIT","direction":expected_direction,"setup_assessment":smc_assessment}
    smc_full={"decision":"WAIT","direction":expected_direction,"valid":True,"setup_assessment":smc_assessment,"trends":trends,"indicators":indicators,"smc":smc,"reason":smc_assessment.get("reason","SMC setup incomplete")}
    if smc_assessment.get("complete"):
        smc_full["decision"]="BUY_PLAN_READY" if expected_direction=="BUY" else "SELL_PLAN_READY"
        smc_full["direction"]=expected_direction
    strategy_result=select_strategy(
        timeframes=timeframes,
        indicators=indicators,
        trends=trends,
        structure=smc_full,
        preferred=getattr(profile,"strategy_mode","AUTO"),
    )
    selected=strategy_result["selected"]
    decision=selected.get("state")
    if selected.get("direction") in {"BUY","SELL"} and selected.get("state")=="READY":
        final_decision="BUY_PLAN_READY" if selected["direction"]=="BUY" else "SELL_PLAN_READY"
    elif selected.get("state")=="WAIT":
        final_decision="WAIT"
    else:
        final_decision="NO_SETUP"
    required=getattr(profile,"analysis_required_timeframes",tuple(timeframes))
    missing=[tf for tf in required if not timeframes.get(tf)]
    if missing:
        return {"valid":False,"decision":"BLOCKED_BY_DATA","reason":f"Required data missing: {', '.join(missing)}.","trends":trends,"indicators":indicators,"smc":smc,"strategy":strategy_result,"setup_assessment":smc_assessment}

    sr={tf:_support_resistance(c[-windows.get(tf,{}).get("support_resistance",len(c)):],tf) for tf,c in timeframes.items() if c}
    confluence=evaluate_confluence(selected.get("direction") or expected_direction or "BUY",trends,indicators,smc,profile=profile,strategy_name=selected.get("name") or "SMC")
    score=float(confluence.get("score",0) or 0)
    minimum_score=int(getattr(profile,"minimum_score",0) or 0)
    confluence={**confluence,"minimum_score":minimum_score,"score_passed":score>=minimum_score}
    # Scoring is evidence returned by analysis. The canonical Workflow owns
    # the execution-readiness gate so UI/scanner/workflow share one authority.
    reason_override=None
    return {
        "valid":True,
        "direction":selected.get("direction") or expected_direction,
        "decision":final_decision,
        "reason": reason_override or (("Strategy selected: " + str(selected.get("name")) + ". " + " ".join(selected.get("reasons",[]))) if selected.get("reasons") else selected.get("state","WAIT")),
        "trends":trends,
        "indicators":indicators,
        "smc":smc,
        "setup_assessment":selected.get("metadata",{}).get("setup",smc_assessment) if isinstance(selected.get("metadata"),dict) else smc_assessment,
        "strategy":strategy_result,
        "confluence":confluence,
        "indicator_reasons":[f"{tf}: RSI={float(v.get('rsi_14',0) or 0):.1f}, MACD hist={float(v.get('macd_histogram',0) or 0):.6f}, ADX={float(v.get('adx_14',0) or 0):.1f}" for tf,v in indicators.items() if v.get("status")=="ready"],
        "smc_reasons":[f"{tf}: liquidity={v.get('liquidity_sweep') or 'none'}, shift={v.get('structure_shift') or 'none'}, FVGs={len(v.get('fair_value_gaps',[]))}, OB={'present' if v.get('order_block') else 'none'}, location={v.get('location','unknown')}" for tf,v in smc.items()],
        "stages":{"higher_timeframe_context":{context_tf:trends.get(context_tf),trend_tf:trends.get(trend_tf)},"market_structure":{tf:v.get('structure',{}).get('bias','unknown') for tf,v in smc.items()},"support_resistance":sr,"entry_model":selected.get("name"),"strategy_selection":strategy_result},
    }
