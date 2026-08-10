"""Legacy function facade over the fresh TradingWorkflow."""

from skills.trading_skill.compat import build_default_workflow


def create_trade_plan(symbol, timeframe="H1", risk_percent=1.0, entry_price=None, account_mode="demo"):
    result = build_default_workflow(risk_percent=risk_percent).prepare(symbol, account_mode)
    payload = result.plan.as_dict() if result.plan else {"symbol": symbol, "timeframe": timeframe, "error": result.message}
    payload.update({"timeframe": timeframe, "brief": result.message, "approved": result.state.value == "APPROVED", "workflow_state": result.state.value, "analysis": result.details.get("analysis", {})})
    if entry_price is not None:
        payload["requested_entry"] = entry_price
    return payload


def analyze_and_recommend(symbol, timeframe="H1", risk_percent=1.0, entry_price=None, auto_execute=False, account_mode="demo"):
    result = create_trade_plan(symbol, timeframe, risk_percent, entry_price, account_mode)
    if auto_execute:
        return "AUTO-TRADE BLOCKED: exact approval is required before execution."
    return result.get("brief", "No trade plan available.")


def execute_approved_trade(plan, confirmation):
    workflow = build_default_workflow()
    phrase = confirmation or plan.get("confirmation_phrase", "")
    result = workflow.execute(phrase)
    return {"success": result.state.value == "EXECUTED", "status": result.state.value, "message": result.message, **result.details}
