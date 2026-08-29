"""Legacy function facade over the fresh TradingWorkflow."""

from __future__ import annotations

from typing import Any, Callable

from skills.trading_skill.models import TradePlan, WorkflowState
from skills.trading_skill.workflow import TradingWorkflow
from skills.trading_skill.symbols import resolve
from skills.trading.market.fresh_market import market as _market_module
from skills.trading.engine.account import get_account_summary as _get_account_summary
from skills.trading.engine.mt5_bridge import execute as _legacy_execute


class LegacyTradingAdapter:
    def __init__(self, account_func_getter: Callable[[], Any], market_getter: Callable[[], Any]):
        self._account_func_getter = account_func_getter
        self._market_getter = market_getter

    def account(self, mode: str, symbol: str | None = None) -> dict[str, Any]:
        account_func = self._account_func_getter()
        if callable(account_func):
            try:
                return (account_func(mode) if account_func else {}) or {}
            except TypeError:
                return (account_func() if account_func else {}) or {}
        return {}

    def symbols(self, mode: str, symbol: str | None = None) -> list[str]:
        return ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "XAUUSD", "AUDCAD", "XAGUSD", "BTCUSD", "ETHUSD", "EURGBP", "EURJPY", "GBPJPY"]

    def market(self, symbol: str, timeframes: tuple[str, ...], mode: str, count: int) -> dict[str, Any]:
        timeframes_data: dict[str, list[dict[str, Any]]] = {}
        market_module = self._market_getter()
        for timeframe in timeframes:
            if not market_module:
                market_data = {}
            else:
                try:
                    market_data = market_module.get_candles_and_indicators(
                        symbol, timeframe, account_mode=mode, count=count
                    ) or {}
                except TypeError:
                    market_data = market_module.get_candles_and_indicators(
                        symbol, timeframe, account_mode=mode
                    ) or {}
            candles = market_data.get("candles") or []
            timeframes_data[timeframe] = candles

        latest = next((frame[-1] for frame in timeframes_data.values() if frame), {})
        bid = float(latest.get("close", 0) or 0)
        ask = float(latest.get("close", 0) or 0)
        return {
            "timeframes": timeframes_data,
            "bid": bid,
            "ask": ask,
            "spread": 0.0,
            "symbol_specs": {
                "tick_size": 0.0001,
                "tick_value": 1.0,
                "volume_min": 0.01,
                "volume_max": 100.0,
                "volume_step": 0.01,
                "margin_per_volume": 10.0,
            },
        }

    def execute(self, order: dict[str, Any], mode: str) -> dict[str, Any]:
        wrapped = {"account_mode": mode, "order": order}
        return _legacy_execute(wrapped)


_ADAPTER = LegacyTradingAdapter(lambda: _get_account_summary, lambda: _market_module)
_LEGACY_WORKFLOW = TradingWorkflow(_ADAPTER)


def _build_analysis(result: dict[str, Any], plan: TradePlan | None) -> dict[str, Any]:
    analysis = result.get("analysis", {}) if isinstance(result, dict) else {}
    if plan is not None:
        analysis = {
            **analysis,
            "order_type": plan.direction,
            "entry_price": plan.entry,
            "stop_loss": plan.stop_loss,
            "take_profit": plan.take_profit,
        }
    return analysis


def create_trade_plan(symbol, timeframe="H1", risk_percent=None, entry_price=None, account_mode="demo"):
    result = _LEGACY_WORKFLOW.prepare(symbol, account_mode, risk_percent=risk_percent)
    plan = result.plan
    if plan is None:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "brief": result.message,
            "approved": False,
            "workflow_state": result.state.value,
            "analysis": {"order_type": "SELL", "entry_price": float(entry_price or 0), "reason": result.message},
            "error": result.message,
        }

    payload = plan.as_dict()
    payload.update({
        "timeframe": timeframe,
        "brief": f"ANGELIQUE TRADE PROPOSAL: {plan.direction} {plan.mt5_symbol} at {plan.entry:.5f}.",
        "approved": result.state in {WorkflowState.APPROVAL_REQUIRED, WorkflowState.APPROVED},
        "workflow_state": result.state.value,
        "analysis": _build_analysis(result.details, plan),
        "account": getattr(result, "account", None),
        "market": getattr(result, "market", None),
    })
    if entry_price is not None:
        payload["requested_entry"] = entry_price
    return payload


def analyze_and_recommend(symbol, timeframe="H1", risk_percent=None, entry_price=None, auto_execute=False, account_mode="demo"):
    result = create_trade_plan(symbol, timeframe, risk_percent, entry_price, account_mode)
    if auto_execute:
        return "AUTO-TRADE BLOCKED: exact approval is required before execution."
    if result.get("approved"):
        return f"ANGELIQUE TRADE PROPOSAL: {result.get('analysis', {}).get('reason', result.get('brief', 'A trade has been proposed.'))}"
    return f"PROPOSED TRADE REJECTED: {result.get('analysis', {}).get('reason', result.get('error', 'No trade plan available.'))}"


def execute_approved_trade(plan, confirmation):
    phrase = confirmation or (plan.get("confirmation_phrase") if isinstance(plan, dict) else getattr(plan, "confirmation_phrase", ""))
    from core.execution_gateway import GATEWAY
    import core.trading_gateway

    execution = GATEWAY.execute(
        "trading.execute_approved_trade",
        {"confirmation_phrase": phrase},
        user_request="Execute approved trade plan",
        session_id="legacy-trading-facade",
    )
    return execution.output if execution.success else {
        "success": False,
        "status": "REJECTED",
        "message": execution.error or "Gateway rejected trade execution.",
    }


def get_account_summary(account_mode="demo"):
    """Backward-compatible facade without recursive self-shadowing."""
    return _get_account_summary(account_mode)


def market(symbol, timeframe="H1", account_mode="demo"):
    """Backward-compatible facade without recursive self-shadowing."""
    return _market_module.get_candles_and_indicators(symbol, timeframe=timeframe, account_mode=account_mode)
