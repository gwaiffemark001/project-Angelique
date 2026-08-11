from __future__ import annotations

from .account import account_snapshot, normalize_mode
from .analysis import analyze_structure
from .models import MarketSnapshot, TradePlan, WorkflowResult, WorkflowState
from core import config
from .risk import build_risk
from .safety import validate_trade_setup
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
            return WorkflowResult(WorkflowState.NO_SETUP, "NO_SETUP: the selected MT5 account is not connected.", account=account)
        available = self.adapter.symbols(mode)
        mt5_symbol = resolve(requested_symbol, available)
        if not mt5_symbol:
            return WorkflowResult(WorkflowState.NO_SETUP, "NO_SETUP: the requested symbol is not available in MT5.", account=account, details={"available_symbols": available})
        raw_market = self.adapter.market(mt5_symbol, self.REQUIRED_TIMEFRAMES, mode, count)
        market = MarketSnapshot(requested_symbol, mt5_symbol, raw_market.get("timeframes", {}), raw_market.get("bid"), raw_market.get("ask"), raw_market.get("spread"), bool(raw_market.get("stale")), raw_market.get("error"))
        if market.error or market.stale or any(not market.timeframes.get(tf) for tf in self.REQUIRED_TIMEFRAMES):
            return WorkflowResult(WorkflowState.NO_SETUP, "NO_SETUP: MT5 market data is missing or stale.", account=account, market=market)
        analysis = analyze_structure(market.timeframes)
        if not analysis["valid"]:
            return WorkflowResult(WorkflowState.REJECTED, f"REJECTED: {analysis['reason']}", account=account, market=market, details={"analysis": analysis})
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
            return WorkflowResult(WorkflowState.NO_SETUP, f"NO_SETUP: {exc}", account=account, market=market, details={"analysis": analysis})

        safety = validate_trade_setup(
            direction=analysis["direction"],
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_amount=risk["risk_amount"],
            risk_percent=self.risk_percent,
            volume=risk["volume"],
            margin_required=risk["margin_required"],
            free_margin_after=risk["free_margin_after"],
            minimum_free_margin=config.TRADING_MIN_FREE_MARGIN,
            current_margin_level=account.margin_level,
            spread=market.spread,
            minimum_rr=self.minimum_rr,
        )
        if not safety["valid"]:
            return WorkflowResult(WorkflowState.REJECTED, f"REJECTED: {'; '.join(safety['reasons'])}", account=account, market=market, details={"analysis": analysis, "safety": safety})
        confluence = analysis.get("confluence", {})
        rationale_items = [
            analysis["reason"],
            confluence.get("summary", "Confluence is being monitored."),
            *confluence.get("agree", [])[:5],
            *confluence.get("disagree", [])[:5],
            *analysis.get("smc_reasons", []),
            *analysis.get("indicator_reasons", []),
            "SMC evidence supports context but is not a standalone entry signal.",
            "Stop loss is structural invalidation.",
            "Volume is calculated from equity risk and stop distance, never from leverage.",
            "Leverage affects required margin only.",
            "No execution occurs before exact approval.",
        ]
        plan = TradePlan(requested_symbol, mt5_symbol, analysis["direction"], "MARKET", entry, stop_loss, take_profit, risk["volume"], self.risk_percent, risk["risk_amount"], risk["margin_required"], risk["free_margin_after"], risk["projected_margin_level"], self.minimum_rr, mode, tuple(rationale_items), f"CONFIRM {analysis['direction']} {mt5_symbol} {risk['volume']} {entry} {stop_loss} {take_profit}")
        self._plans[plan.confirmation_phrase] = plan
        return WorkflowResult(WorkflowState.APPROVAL_REQUIRED, "APPROVAL_REQUIRED: trade plan ready for your review.", plan=plan, account=account, market=market, details={"analysis": analysis, "safety": safety, "confluence": confluence})

    def approve(self, confirmation_phrase: str) -> WorkflowResult:
        plan = self._plans.get(confirmation_phrase)
        if plan is None:
            return WorkflowResult(WorkflowState.REJECTED, "Approval rejected: the confirmation does not match a current plan.")
        return WorkflowResult(WorkflowState.APPROVED, "APPROVED: plan approved; execution is now permitted.", plan=plan)

    def execute(self, confirmation_phrase: str) -> WorkflowResult:
        approval = self.approve(confirmation_phrase)
        if approval.state not in {WorkflowState.APPROVED, WorkflowState.TRADE_READY} or approval.plan is None:
            return approval
        response = self.adapter.execute(approval.plan.as_dict(), approval.plan.account_mode)
        if not response.get("success"):
            return WorkflowResult(WorkflowState.REJECTED, f"MT5 did not confirm execution: {response.get('error', 'unknown error')}", plan=approval.plan, details=response)
        return WorkflowResult(WorkflowState.EXECUTED, "MT5 confirmed the order execution.", plan=approval.plan, details=response)
