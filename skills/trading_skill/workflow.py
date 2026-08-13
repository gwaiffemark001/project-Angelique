from __future__ import annotations

from __future__ import annotations

from datetime import datetime, timezone
from .account import account_snapshot, normalize_mode
from .account_manager import account_manager
from .analysis import analyze_structure
from .event_logging import log_event
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
        self._active_plans: dict[str, TradePlan] = {}

    def _is_expired(self, plan: TradePlan) -> bool:
        try:
            return datetime.fromisoformat(plan.expires_at) <= datetime.now(timezone.utc)
        except Exception:
            return False

    def _build_plan_id(self, symbol: str, direction: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{symbol}-{direction}-{timestamp}"

    def _revalidate_plan(self, plan: TradePlan) -> tuple[bool, str]:
        if self._is_expired(plan):
            return False, "Opportunity expired before confirmation."

        raw_account = self.adapter.account(plan.account_mode)
        fresh_account = account_snapshot(raw_account, plan.account_mode)
        if not fresh_account.connected:
            return False, "Account disconnected or mode mismatch on revalidation."

        raw_market = self.adapter.market(plan.mt5_symbol, self.REQUIRED_TIMEFRAMES, plan.account_mode, 100)
        market = MarketSnapshot(plan.requested_symbol, plan.mt5_symbol, raw_market.get("timeframes", {}), raw_market.get("bid"), raw_market.get("ask"), raw_market.get("spread"), bool(raw_market.get("stale")), raw_market.get("error"))
        if market.error or market.stale or any(not market.timeframes.get(tf) for tf in self.REQUIRED_TIMEFRAMES):
            return False, "Market data unavailable or stale during revalidation."

        if market.bid is None or market.ask is None:
            return False, "Fresh bid/ask data unavailable during revalidation."

        current_price = market.ask if plan.direction == "BUY" else market.bid
        slippage = abs(current_price - plan.entry)
        acceptable_slippage = max(plan.entry * 0.0005, 0.0005)
        if slippage > acceptable_slippage:
            return False, f"Price moved too far from the approved entry ({current_price:.6f} vs {plan.entry:.6f})."

        try:
            risk = build_risk(
                plan.entry,
                plan.stop_loss,
                fresh_account.equity,
                self.risk_percent,
                raw_market.get("symbol_specs", {}),
                free_margin=fresh_account.free_margin,
                used_margin=fresh_account.used_margin,
                minimum_free_margin=config.TRADING_MIN_FREE_MARGIN,
                current_margin_level=fresh_account.margin_level,
            )
        except ValueError as exc:
            return False, f"Risk revalidation failed: {exc}"

        safety = validate_trade_setup(
            direction=plan.direction,
            entry=plan.entry,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            risk_amount=risk["risk_amount"],
            risk_percent=self.risk_percent,
            volume=risk["volume"],
            margin_required=risk["margin_required"],
            free_margin_after=risk["free_margin_after"],
            minimum_free_margin=config.TRADING_MIN_FREE_MARGIN,
            current_margin_level=fresh_account.margin_level,
            spread=market.spread,
            minimum_rr=self.minimum_rr,
        )
        if not safety["valid"]:
            return False, f"Revalidation safety failed: {'; '.join(safety['reasons'])}"

        if abs(risk["volume"] - plan.volume) > 1e-8:
            return False, "Calculated volume changed during revalidation."
        return True, "Revalidation passed."

    def prepare(self, requested_symbol: str, account_mode: str = "demo", count: int = 200) -> WorkflowResult:
        mode = normalize_mode(account_mode)
        raw_account = self.adapter.account(mode)
        account = account_snapshot(raw_account, mode)
        if not account.connected:
            return WorkflowResult(WorkflowState.NO_SETUP, "NO_SETUP: the selected MT5 account is not connected.", account=account)
        authorized, authorization_message, _ = account_manager.validate_authorization(mode)
        if not authorized:
            log_event(30, "workflow.authorization_rejected", requested_mode=account_mode, resolved_mode=mode, message=authorization_message)
            return WorkflowResult(WorkflowState.NO_SETUP, f"NO_SETUP: {authorization_message}", account=account, details={"authorization": authorization_message})

        available = self.adapter.symbols(mode)
        mt5_symbol = resolve(requested_symbol, available)
        if not mt5_symbol:
            return WorkflowResult(WorkflowState.NO_SETUP, "NO_SETUP: the requested symbol is not available in MT5.", account=account, details={"available_symbols": available})

        active_key = f"{mt5_symbol}:{mode}"
        existing_plan = self._active_plans.get(active_key)
        if existing_plan:
            if self._is_expired(existing_plan):
                self._active_plans.pop(active_key, None)
                self._plans.pop(existing_plan.confirmation_phrase, None)
            else:
                return WorkflowResult(
                    WorkflowState.APPROVAL_REQUIRED,
                    "APPROVAL_REQUIRED: a pending opportunity for this symbol already exists.",
                    plan=existing_plan,
                    account=account,
                )

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
            return WorkflowResult(WorkflowState.REJECTED, f"REJECTED: {exc}", account=account, market=market, details={"analysis": analysis})

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

        plan = TradePlan(
            requested_symbol,
            mt5_symbol,
            analysis["direction"],
            "MARKET",
            entry,
            stop_loss,
            take_profit,
            risk["volume"],
            self.risk_percent,
            risk["risk_amount"],
            risk["margin_required"],
            risk["free_margin_after"],
            risk["projected_margin_level"],
            self.minimum_rr,
            mode,
            self._build_plan_id(mt5_symbol, analysis["direction"]),
            tuple(rationale_items),
            f"CONFIRM {analysis['direction']} {mt5_symbol} {risk['volume']} {entry} {stop_loss} {take_profit}",
        )
        self._plans[plan.confirmation_phrase] = plan
        self._active_plans[active_key] = plan
        return WorkflowResult(
            WorkflowState.APPROVAL_REQUIRED,
            "APPROVAL_REQUIRED: trade plan ready for your review.",
            plan=plan,
            account=account,
            market=market,
            details={"analysis": analysis, "safety": safety, "confluence": confluence, "pipeline": ["DETECTED", "ANALYZING", "VALIDATING_SETUP", "RISK_CHECK"]},
        )

    def approve(self, confirmation_phrase: str) -> WorkflowResult:
        plan = self._plans.get(confirmation_phrase)
        if plan is None:
            return WorkflowResult(WorkflowState.REJECTED, "Approval rejected: the confirmation does not match a current plan.")
        if self._is_expired(plan):
            self._plans.pop(confirmation_phrase, None)
            self._active_plans.pop(f"{plan.mt5_symbol}:{plan.account_mode}", None)
            return WorkflowResult(WorkflowState.EXPIRED, "EXPIRED: the opportunity expired before approval.", plan=plan)
        return WorkflowResult(WorkflowState.APPROVED, "APPROVED: plan approved; execution is now permitted.", plan=plan)

    def execute(self, confirmation_phrase: str) -> WorkflowResult:
        approval = self.approve(confirmation_phrase)
        if approval.state is WorkflowState.EXPIRED or approval.plan is None:
            return approval
        if approval.state is not WorkflowState.APPROVED:
            return approval
        plan = approval.plan
        valid, message = self._revalidate_plan(plan)
        if not valid:
            if "expired" in message.lower():
                return WorkflowResult(WorkflowState.EXPIRED, f"EXPIRED: {message}", plan=plan)
            return WorkflowResult(WorkflowState.REJECTED, f"REFUSED: {message}", plan=plan)

        response = self.adapter.execute(plan.as_dict(), plan.account_mode)
        if not response.get("success"):
            return WorkflowResult(WorkflowState.REJECTED, f"MT5 did not confirm execution: {response.get('error', 'unknown error')}", plan=plan, details=response)

        self._active_plans.pop(f"{plan.mt5_symbol}:{plan.account_mode}", None)
        self._plans.pop(plan.confirmation_phrase, None)
        return WorkflowResult(WorkflowState.EXECUTED, "EXECUTED: MT5 confirmed the order execution.", plan=plan, details=response)
