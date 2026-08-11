from __future__ import annotations

from .compat import build_default_workflow
from .universe import eligible_symbols
from .journal import record_trade

_workflow = None


def workflow():
    global _workflow
    if _workflow is None:
        _workflow = build_default_workflow()
    return _workflow


def prepare_trade(symbol: str, account_mode: str = "demo"):
    return workflow().prepare(symbol, account_mode)


def prepare_trade_payload(symbol: str, account_mode: str = "demo", risk_percent: float = 1.0):
    active = workflow()
    active.risk_percent = risk_percent
    result = active.prepare(symbol, account_mode)
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
    if result.state.value == "EXECUTED" and result.plan is not None:
        record_trade(result.plan.as_dict(), result.details)
    return result


def monitor_universe(account_mode: str = "demo"):
    active = workflow()
    available = active.adapter.symbols(account_mode)
    candidates = eligible_symbols(available)
    results = []
    for symbol in candidates:
        result = active.prepare(symbol, account_mode)
        results.append({"symbol": symbol, "state": result.state.value, "message": result.message, "result": result})
        if result.plan is not None:
            from brain.cognitive_loop import review_market_opportunity
            candidate = {"symbol": symbol, "plan": result.plan.as_dict(), "market": result.market, "analysis": result.details.get("analysis", {})}
            review = review_market_opportunity(candidate)
            if review["decision"] != "PLAN":
                results[-1]["brain_review"] = review
                continue
            return {"state": "OPPORTUNITY_FOUND", "candidates": candidates, "scanned": len(results), "opportunity": {"state": result.state.value, "message": result.message, "plan": result.plan.as_dict(), "account": result.account, "market": result.market, "details": result.details, "brain_review": review}}
    return {"state": "WAITING", "candidates": candidates, "scanned": len(results), "results": results}
