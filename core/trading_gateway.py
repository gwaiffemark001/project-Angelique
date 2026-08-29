from __future__ import annotations

from typing import Any

from core.tool_registry import GLOBAL_TOOL_REGISTRY, ToolSchema


def execute_approved_trade(confirmation_phrase: str) -> dict[str, Any]:
    from skills.trading_skill.service import execute_trade

    result = execute_trade(confirmation_phrase)
    return {
        "success": result.state.value == "EXECUTED",
        "state": result.state.value,
        "message": result.message,
        "plan": result.plan.as_dict() if result.plan else None,
        "details": result.details,
    }


def close_position(symbol: str, account_mode: str = "demo", ticket: int | None = None) -> dict[str, Any]:
    from skills.trading_skill.account_manager import account_manager
    from skills.trading_skill.bridge import WineBridgeClient
    from core.trading_routing import broker_for_symbol

    required_broker = broker_for_symbol(symbol)
    authorized, message, _ = account_manager.validate_authorization(account_mode)
    if not authorized:
        return {"success": False, "status": "error", "error": f"Account authorization failed: {message}"}

    bridge = WineBridgeClient(broker=required_broker)
    if ticket is None:
        positions = bridge.request("positions", {"account_mode": account_mode}).get("positions", [])
        matches = [position for position in positions if str(position.get("symbol", "")).upper() == symbol.upper()]
        if len(matches) != 1:
            return {
                "success": False,
                "status": "error",
                "error": "Manual exit requires a unique position ticket for the selected symbol.",
            }
        ticket = int(matches[0].get("ticket"))
    payload: dict[str, Any] = {"symbol": symbol, "account_mode": account_mode}
    payload["ticket"] = ticket
    return bridge.request("close_position", payload)


def close_all_positions(account_mode: str = "demo") -> dict[str, Any]:
    from skills.trading_skill.account_manager import account_manager
    from skills.trading_skill.bridge import WineBridgeClient

    authorized, message, _ = account_manager.validate_authorization(account_mode)
    if not authorized:
        return {"success": False, "status": "error", "error": f"Account authorization failed: {message}"}

    bridge = WineBridgeClient()
    return bridge.request("close_all_positions", {"account_mode": account_mode})


def register_trading_tools() -> None:
    schemas = (
        ToolSchema(
            name="trading.execute_approved_trade",
            description="Execute an already approved, unexpired TradePlan through the TradingWorkflow.",
            parameters={"confirmation_phrase": "Exact TradePlan confirmation phrase."},
            required=["confirmation_phrase"],
            param_types={"confirmation_phrase": "string"},
            risk_level="FINANCIAL",
            category="trading",
            executor=execute_approved_trade,
            confirmation_policy="never",
        ),
        ToolSchema(
            name="trading.close_position",
            description="Close a selected open position through the MT5 bridge.",
            parameters={"symbol": "MT5 symbol.", "account_mode": "Account environment.", "ticket": "Optional position ticket."},
            required=["symbol"],
            param_types={"symbol": "string", "account_mode": "string", "ticket": "int"},
            enums={"account_mode": ["demo", "real", "live"]},
            risk_level="FINANCIAL",
            category="trading",
            executor=close_position,
            confirmation_policy="never",
        ),
        ToolSchema(
            name="trading.close_all_positions",
            description="Close every open position on the account through the MT5 bridge. Used by the manual 'close all positions' control and the daily-loss kill switch.",
            parameters={"account_mode": "Account environment."},
            required=[],
            param_types={"account_mode": "string"},
            enums={"account_mode": ["demo", "real", "live"]},
            risk_level="FINANCIAL",
            category="trading",
            executor=close_all_positions,
            confirmation_policy="never",
        ),
    )
    for schema in schemas:
        if GLOBAL_TOOL_REGISTRY.get(schema.name) is None:
            GLOBAL_TOOL_REGISTRY.register(schema)


register_trading_tools()