from __future__ import annotations

from .account_manager import account_manager
from .compat import build_default_workflow
from .journal import record_trade
from .event_logging import log_event
from .position_monitor import position_monitor
from .universe import eligible_symbols

_workflow = None


def workflow():
    global _workflow
    if _workflow is None:
        _workflow = build_default_workflow()
    return _workflow


def set_trading_mode(trading_mode: str):
    active = workflow()
    if active.trading_mode.value != str(trading_mode).upper():
        active.clear_pending_plans()
    active.set_trading_mode(trading_mode)
    return active.profile.as_dict()


def get_account_snapshot(account_mode: str = "demo", force_refresh: bool = False):
    authorized, message, snapshot = account_manager.validate_authorization(account_mode)
    if force_refresh:
        snapshot = account_manager.get_snapshot(account_mode, True)
    return {"authorized": authorized, "message": message, "snapshot": snapshot}


def get_open_positions(account_mode: str = "demo", symbol: str | None = None):
    return position_monitor.get_open_positions(account_mode, symbol)


def monitor_positions(account_mode: str = "demo", symbol: str | None = None, market_by_symbol: dict | None = None):
    return position_monitor.monitor_once(account_mode, symbol, market_by_symbol)


def prepare_trade(symbol: str, account_mode: str = "demo", trading_mode: str = "DAY_TRADING"):
    set_trading_mode(trading_mode)
    return workflow().prepare(symbol, account_mode)


def prepare_trade_payload(symbol: str, account_mode: str = "demo", risk_percent: float = 1.0):
    active = workflow()
    previous_risk = active.risk_percent
    active.risk_percent = risk_percent
    try:
        result = active.prepare(symbol, account_mode)
    finally:
        active.risk_percent = previous_risk
    return {
        "state": result.state.value,
        "message": result.message,
        "plan": result.plan.as_dict() if result.plan else None,
        "details": result.details,
    }


def approve_trade(confirmation_phrase: str):
    return workflow().approve(confirmation_phrase)


def execute_trade(confirmation_phrase: str):
    result = workflow().execute(confirmation_phrase)
    if result.plan is not None and result.state.value in {"EXECUTED", "REJECTED", "EXPIRED"}:
        record_trade(
            result.plan.as_dict(),
            {
                **(result.details or {}),
                "status": result.state.value,
                "message": result.message,
            },
        )
    return result


def scan_universe(account_mode: str = "demo", trading_mode: str = "DAY_TRADING"):
    active = workflow()
    active.set_trading_mode(trading_mode)
    available = active.adapter.symbols(account_mode)
    candidates = eligible_symbols(available)
    results = []
    for symbol in candidates:
        result = active.prepare(symbol, account_mode)
        entry = {
            "symbol": symbol,
            "state": result.state.value,
            "message": result.message,
            "result": result,
        }
        results.append(entry)
        if result.plan is not None:
            return {
                "state": "OPPORTUNITY_FOUND",
                "candidates": candidates,
                "scanned": len(results),
                "opportunity": {
                    "state": result.state.value,
                    "message": result.message,
                    "plan": result.plan.as_dict(),
                    "account": result.account,
                    "market": result.market,
                    "details": result.details,
                    "candidate": entry,
                },
            }
    return {"state": "WAITING", "candidates": candidates, "scanned": len(results), "results": results}


def monitor_universe(account_mode: str = "demo", trading_mode: str = "DAY_TRADING"):
    scan = scan_universe(account_mode, trading_mode)
    if scan["state"] != "OPPORTUNITY_FOUND":
        log_event(20, "service.monitor_universe.waiting", account_mode=account_mode, scanned=scan["scanned"])
        return scan

    opportunity = scan["opportunity"]
    from brain.cognitive_loop import review_market_opportunity

    candidate = {
        "symbol": opportunity["candidate"]["symbol"],
        "plan": opportunity["plan"],
        "market": opportunity["market"],
        "analysis": opportunity["details"].get("analysis", {}),
    }
    review = review_market_opportunity(candidate)
    if review["decision"] != "PLAN":
        log_event(20, "service.monitor_universe.review_rejected", account_mode=account_mode, symbol=candidate["symbol"], decision=review["decision"])
        opportunity["brain_review"] = review
        return {**scan, "state": "WAITING", "opportunity": opportunity}

    log_event(20, "service.monitor_universe.opportunity_confirmed", account_mode=account_mode, symbol=candidate["symbol"], decision=review["decision"])
    return {
        "state": "OPPORTUNITY_FOUND",
        "candidates": scan["candidates"],
        "scanned": scan["scanned"],
        "opportunity": {**opportunity, "brain_review": review},
    }
