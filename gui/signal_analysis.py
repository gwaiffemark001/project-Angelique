"""Trading Hub signal presentation adapter.

The signal page consumes the canonical TradingWorkflow result exactly once. It
never invents a separate SL/TP or execution decision. Account mode and actual
MT5 mode are part of the returned contract so the UI cannot display stale data
from the other environment.
"""
from __future__ import annotations

from typing import Any

from skills.trading_skill.profiles import get_trading_profile
from skills.trading_skill.service import auto_execution_enabled, prepare_trade


def _required_timeframes(profile: Any) -> tuple[str, ...]:
    return profile.required_timeframes


def _signal_timeframe_requirements(profile: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return profile.analysis_required_timeframes, profile.analysis_optional_timeframes


def signal_ui_contract(report: dict[str, Any]) -> dict[str, Any]:
    confluence = report.get("confluence") or {}
    structure = report.get("structure") or {}
    assessment = structure.get("setup_assessment") or {}
    strategy = (structure.get("strategy") or {}).get("selected", {})
    plan = report.get("advisory_plan") or {}
    account = report.get("account") or {}
    execution = report.get("execution") or {}
    return {
        "symbol": report.get("symbol"),
        "state": report.get("decision_state", report.get("signal", "WAIT")),
        "score": confluence.get("score"),
        "minimum_score": confluence.get("minimum_score", 0),
        "score_passed": confluence.get("score_passed"),
        "model": strategy.get("name") or assessment.get("model"),
        "spread_pips": report.get("spread_pips"),
        "spread_points": report.get("spread_points"),
        "spread_unit": report.get("spread_unit"),
        "direction": plan.get("direction"),
        "entry": plan.get("entry"),
        "stop_loss": plan.get("stop_loss"),
        "take_profit": plan.get("take_profit"),
        "reward_to_risk": plan.get("reward_to_risk"),
        "account_mode": report.get("account_mode"),
        "actual_account_mode": account.get("actual_mode"),
        "mode_match": account.get("mode_match", account.get("requested_mode") == account.get("actual_mode")),
        "requires_manual_approval": bool(plan.get("requires_manual_approval")),
        "execution_state": execution.get("state"),
        "execution_message": execution.get("message"),
        "supporting_evidence": report.get("setup_evidence") or assessment.get("supporting_evidence", {}),
    }


def _account_dict(account: Any) -> dict[str, Any]:
    return dict(account.__dict__) if account is not None else {}


def _market_dict(market: Any) -> dict[str, Any]:
    return dict(market.__dict__) if market is not None else {}


def analyze_symbol(symbol: str, account_mode: str, timeframes: list[str], trading_mode: str) -> dict[str, Any]:
    profile = get_trading_profile(trading_mode)
    result = prepare_trade(symbol, account_mode, trading_mode)
    details = result.details or {}
    analysis = details.get("analysis", {}) or {}
    account = _account_dict(result.account)
    market = _market_dict(result.market)
    plan = result.plan.as_dict() if result.plan else None
    decision_state = result.decision_state or result.state.value
    direction = plan.get("direction") if plan else analysis.get("direction") or "NONE"
    confluence = analysis.get("confluence", details.get("confluence", {})) or {}
    strategy_selected = (analysis.get("strategy") or {}).get("selected", {}) or {}
    execution_state = "NO_EXECUTION"
    if plan:
        execution_state = "MANUAL_APPROVAL_REQUIRED" if plan.get("requires_manual_approval") else (
            "AUTO_ENABLED" if auto_execution_enabled(account_mode) else "MANUAL_APPROVAL_REQUIRED"
        )

    # Build explicit evidence rows from the canonical analysis. These values are
    # the same ones the workflow used to make its decision.
    smc = analysis.get("smc", {}) or {}
    setup_assessment = analysis.get("setup_assessment", {}) or {}
    evidence = {
        "market_structure": analysis.get("stages", {}).get("market_structure", {}),
        "trends": analysis.get("trends", {}),
        "liquidity": {tf: v.get("liquidity_sweep") for tf, v in smc.items()},
        "bos_choch": {tf: v.get("structure_shift") for tf, v in smc.items()},
        "fvg": {tf: v.get("fair_value_gaps", []) for tf, v in smc.items()},
        "order_blocks": {tf: v.get("order_block") for tf, v in smc.items()},
        "locations": {tf: v.get("location") for tf, v in smc.items()},
        "setup_model": setup_assessment.get("model") or strategy_selected.get("name"),
        "setup_missing": setup_assessment.get("missing", []),
        "setup_reason": setup_assessment.get("reason"),
        "confluence": confluence,
        "indicator_reasons": analysis.get("indicator_reasons", []),
        "smc_reasons": analysis.get("smc_reasons", []),
        "session_context": analysis.get("session_context", {}),
    }

    return {
        "symbol": symbol,
        "requested_symbol": symbol,
        "account_mode": account_mode,
        "actual_account_mode": account.get("actual_mode"),
        "mode_match": bool(account.get("connected") and account.get("actual_mode") == account.get("requested_mode")),
        "generated_at": result.plan.created_at if result.plan else None,
        "signal": direction if plan else ("WAIT" if decision_state == "WAIT" else direction),
        "direction": analysis.get("direction") or "NONE",
        "trade_allowed": bool(plan),
        "decision_state": decision_state,
        "workflow_state": result.state.value,
        "required_timeframes": list(profile.analysis_required_timeframes),
        "optional_timeframes": list(profile.analysis_optional_timeframes),
        "data_blockers": details.get("data_blockers", []),
        "data_quality": analysis.get("data_quality", {}),
        "candle_windows": analysis.get("candle_windows", {}),
        "htf_bias": analysis.get("htf_bias"),
        "execution_bias": analysis.get("execution_bias"),
        "reason": result.message,
        "trends": analysis.get("trends", {}),
        "smc": smc,
        "structure": analysis,
        "setup_evidence": evidence,
        "confluence": confluence,
        "reasons": analysis.get("reasons", []),
        "market_errors": analysis.get("market_errors", {}),
        "latest": market,
        "account": account,
        "symbol_specs": market.get("symbol_specs", {}) if isinstance(market.get("symbol_specs"), dict) else {},
        "spread_pips": market.get("spread_pips"),
        "spread_points": market.get("spread_points"),
        "spread_unit": market.get("spread_unit"),
        "advisory_plan": plan or {
            "status": "WAITING" if decision_state == "WAIT" else "NOT_EXECUTABLE",
            "direction": direction if direction in {"BUY", "SELL"} else "NONE",
            "entry": None,
            "stop_loss": None,
            "take_profit": None,
            "reward_to_risk": None,
            "strategy": strategy_selected.get("name"),
            "requires_manual_approval": False,
        },
        "execution": {
            "state": execution_state,
            "auto_enabled": auto_execution_enabled(account_mode),
            "requires_manual_approval": bool(plan and plan.get("requires_manual_approval")),
        },
        "timeframes": timeframes,
        "session_context": analysis.get("session_context", {}),
    }
