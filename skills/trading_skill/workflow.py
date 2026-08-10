from __future__ import annotations

from .account import account_snapshot, normalize_mode
from .analysis import analyze_structure
from .models import MarketSnapshot, TradePlan, WorkflowResult, WorkflowState
from core import config
from .risk import build_risk
from .symbols import resolve


class TradingWorkflow:
    """The only orchestration API for analysis, planning, approval, and execution."""

    REQUIRED_TIMEFRAMES = ("H4", "H1", "M15", "M5")

    def __init__(self, adapter, risk_percent: float = 1.0, minimum_rr: float = 2.0):
        self.adapter = adapter
        self.risk_percent = risk_percent
        self.minimum_rr = minimum_rr
        self._plans: dict[str, TradePlan] = {}

    def prepare(self, requested_symbol: str, account_mode: str = "demo", count: int = 200) -> WorkflowResult:
        mode = normalize_mode(account_mode)
        raw_account = self.adapter.account(mode)
        account = account_snapshot(raw_account, mode)
        if not account.connected:
            return WorkflowResult(WorkflowState.REJECTED, "NO TRADE: the selected MT5 account is not connected.", account=account)
        available = self.adapter.symbols(mode)
        mt5_symbol = resolve(requested_symbol, available)
        if not mt5_symbol:
            return WorkflowResult(WorkflowState.REJECTED, "NO TRADE: the requested symbol is not available in MT5.", account=account, details={"available_symbols": available})
        raw_market = self.adapter.market(mt5_symbol, self.REQUIRED_TIMEFRAMES, mode, count)
        market = MarketSnapshot(requested_symbol, mt5_symbol, raw_market.get("timeframes", {}), raw_market.get("bid"), raw_market.get("ask"), raw_market.get("spread"), bool(raw_market.get("stale")), raw_market.get("error"))
        if market.error or market.stale or any(not market.timeframes.get(tf) for tf in self.REQUIRED_TIMEFRAMES):
            return WorkflowResult(WorkflowState.REJECTED, "NO TRADE: MT5 market data is missing or stale.", account=account, market=market)
        analysis = analyze_structure(market.timeframes)
        if not analysis["valid"]:
            return WorkflowResult(WorkflowState.REJECTED, f"NO TRADE: {analysis['reason']}", account=account, market=market, details={"analysis": analysis})
        latest = market.timeframes["M5"][-1]
        entry = float(market.ask if analysis["direction"] == "BUY" and market.ask else market.bid if analysis["direction"] == "SELL" and market.bid else latest["close"])
        lows = [float(c["low"]) for c in market.timeframes["M15"][-20:]]
        highs = [float(c["high"]) for c in market.timeframes["M15"][-20:]]
        stop_loss = min(lows) if analysis["direction"] == "BUY" else max(highs)
        distance = abs(entry - stop_loss)
        take_profit = entry + distance * self.minimum_rr if analysis["direction"] == "BUY" else entry - distance * self.minimum_rr
        specs = raw_market.get("symbol_specs", {})
        try:
            risk = build_risk(
                entry,
                stop_loss,
                account.equity,
                self.risk_percent,
                specs,
                free_margin=account.free_margin,
                used_margin=account.used_margin,
                minimum_free_margin=config.TRADING_MIN_FREE_MARGIN,
                current_margin_level=account.margin_level,
            )
        except ValueError as exc:
            return WorkflowResult(WorkflowState.REJECTED, f"NO TRADE: {exc}", account=account, market=market, details={"analysis": analysis})
        plan = TradePlan(requested_symbol, mt5_symbol, analysis["direction"], "MARKET", entry, stop_loss, take_profit, risk["volume"], self.risk_percent, risk["risk_amount"], risk["margin_required"], risk["free_margin_after"], risk["projected_margin_level"], self.minimum_rr, mode, (analysis["reason"], *analysis.get("indicator_reasons", []), "Stop loss is structural invalidation.", "Volume was calculated from MT5 tick and margin specifications.", "No execution occurs before exact approval."), f"CONFIRM {analysis['direction']} {mt5_symbol} {risk['volume']} {entry} {stop_loss} {take_profit}")
        self._plans[plan.confirmation_phrase] = plan
        return WorkflowResult(WorkflowState.APPROVAL_REQUIRED, "Trade plan ready. Waiting for your exact approval.", plan=plan, account=account, market=market, details={"analysis": analysis})

    def approve(self, confirmation_phrase: str) -> WorkflowResult:
        plan = self._plans.get(confirmation_phrase)
        if plan is None:
            return WorkflowResult(WorkflowState.REJECTED, "Approval rejected: the confirmation does not match a current plan.")
        return WorkflowResult(WorkflowState.APPROVED, "Plan approved. Execution is now permitted.", plan=plan)

    def execute(self, confirmation_phrase: str) -> WorkflowResult:
        approval = self.approve(confirmation_phrase)
        if approval.state != WorkflowState.APPROVED or approval.plan is None:
            return approval
        response = self.adapter.execute(approval.plan.as_dict(), approval.plan.account_mode)
        if not response.get("success"):
            return WorkflowResult(WorkflowState.REJECTED, f"MT5 did not confirm execution: {response.get('error', 'unknown error')}", plan=approval.plan, details=response)
        return WorkflowResult(WorkflowState.EXECUTED, "MT5 confirmed the order execution.", plan=approval.plan, details=response)
