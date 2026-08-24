from __future__ import annotations

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from .account import account_snapshot, normalize_mode
from .account_manager import account_manager
from .analysis import analyze_structure
from .event_logging import log_event
from .models import MarketSnapshot, TradePlan, WorkflowResult, WorkflowState
from .profiles import TradingMode, get_trading_profile, normalize_trading_mode
from core import config
from .risk import build_risk, validate_profile_limits
from .safety import validate_trade_setup
from .news_context import assess_news
from .symbols import resolve


class TradingWorkflow:
    """The only orchestration API for analysis, planning, approval, and execution."""

    def __init__(self, adapter, risk_percent: float | None = None, minimum_rr: float | None = None, trading_mode: TradingMode | str | None = None):
        self.adapter = adapter
        self.trading_mode = normalize_trading_mode(trading_mode)
        self.profile = get_trading_profile(self.trading_mode)
        if trading_mode is None:
            self.profile = replace(self.profile, minimum_score=6)
        self.risk_percent = self.profile.risk_per_trade if risk_percent is None else risk_percent
        self.minimum_rr = self.profile.minimum_rr if minimum_rr is None else minimum_rr
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

    def set_trading_mode(self, mode: TradingMode | str) -> None:
        self.trading_mode = normalize_trading_mode(mode)
        self.profile = get_trading_profile(self.trading_mode)
        self.risk_percent = self.profile.risk_per_trade
        self.minimum_rr = self.profile.minimum_rr

    def clear_pending_plans(self) -> None:
        self._plans.clear()
        self._active_plans.clear()

    def _revalidate_plan(self, plan: TradePlan) -> tuple[bool, str]:
        if self._is_expired(plan):
            return False, "Opportunity expired before confirmation."

        plan_profile = get_trading_profile(plan.trading_mode)

        fresh_news = assess_news(plan.mt5_symbol, plan.direction)
        if fresh_news.get("high_impact_imminent") or fresh_news.get("directional_conflict"):
            return False, f"News risk changed before execution: {fresh_news.get('reason', 'material news risk detected.')}"

        raw_account = self.adapter.account(plan.account_mode)
        fresh_account = account_snapshot(raw_account, plan.account_mode)
        if not fresh_account.connected:
            return False, "Account disconnected or mode mismatch on revalidation."

        authorized, authorization_message, _ = account_manager.validate_authorization(plan.account_mode)
        if not authorized:
            return False, f"Account authorization failed during revalidation: {authorization_message}"

        positions_reader = getattr(self.adapter, "positions", None)
        if callable(positions_reader):
            positions_value = positions_reader(plan.account_mode)
            positions_response: dict[str, Any] = positions_value if isinstance(positions_value, dict) else {}
            if positions_response.get("status") == "error" or positions_response.get("error"):
                return False, "Open-position data unavailable during revalidation."
            portfolio = validate_profile_limits(
                raw_account,
                list(positions_response.get("positions", []) or []),
                plan_profile,
            )
            if not portfolio["valid"]:
                return False, f"Portfolio limit failed during revalidation: {'; '.join(portfolio['reasons'])}"

        required_timeframes = plan_profile.required_timeframes
        raw_market = self.adapter.market(plan.mt5_symbol, required_timeframes, plan.account_mode, 100)
        specs = raw_market.get("symbol_specs", {}) or {}
        tick_size = specs.get("tick_size")
        tick_value = specs.get("tick_value")
        spread_raw = raw_market.get("spread")
        spread_pips = None
        try:
            if spread_raw is not None and tick_size:
                raw = float(spread_raw)
                ts = float(tick_size)
                pip_unit = 0.0001 if ts <= 0.0001 else 0.01 if ts >= 0.01 else 0.0001
                spread_pips = raw / pip_unit
        except Exception:
            spread_pips = None

        market = MarketSnapshot(plan.requested_symbol, plan.mt5_symbol, raw_market.get("timeframes", {}), raw_market.get("bid"), raw_market.get("ask"), spread_raw, tick_size, tick_value, spread_pips, bool(raw_market.get("stale")), raw_market.get("error"))
        if market.error or market.stale or any(not market.timeframes.get(tf) for tf in required_timeframes):
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
                plan.risk_percent,
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
            risk_percent=plan.risk_percent,
            volume=risk["volume"],
            margin_required=risk["margin_required"],
            free_margin_after=risk["free_margin_after"],
            minimum_free_margin=risk["minimum_free_margin"],
            current_margin_level=fresh_account.margin_level,
            spread=market.spread,
            spread_pips=market.spread_pips,
            minimum_rr=plan_profile.minimum_rr,
            maximum_spread_pips=plan_profile.max_spread_pips,
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

        positions_response: dict[str, Any] = {"positions": []}
        positions_reader = getattr(self.adapter, "positions", None)
        if callable(positions_reader):
            positions_value = positions_reader(mode)
            if isinstance(positions_value, dict):
                positions_response = positions_value
            if positions_response.get("status") == "error" or positions_response.get("error"):
                return WorkflowResult(
                    WorkflowState.NO_SETUP,
                    "NO_SETUP: open-position data is unavailable; portfolio risk cannot be verified.",
                    account=account,
                    details={"portfolio_limits": {"valid": False, "reasons": ["Position snapshot unavailable."]}},
                )
        portfolio = validate_profile_limits(
            raw_account,
            list(positions_response.get("positions", []) or []),
            self.profile,
        )
        if not portfolio["valid"]:
            return WorkflowResult(
                WorkflowState.REJECTED,
                f"REJECTED: {'; '.join(portfolio['reasons'])}",
                account=account,
                details={"portfolio_limits": portfolio},
            )

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

        required_timeframes = self.profile.required_timeframes
        raw_market = self.adapter.market(mt5_symbol, required_timeframes, mode, count)
        # Extract tick specs when provided by the bridge so we can normalize
        # spread into pips (symbol-dependent). The bridge returns 'symbol_specs'
        # with 'tick_size' and 'tick_value' where available.
        specs = raw_market.get("symbol_specs", {}) or {}
        tick_size = specs.get("tick_size")
        tick_value = specs.get("tick_value")
        spread_raw = raw_market.get("spread")
        spread_pips = None
        try:
            if spread_raw is not None and tick_size:
                # pips = (ask - bid) / tick_size * (tick_size / pip_unit)
                # For most brokers pip unit is 0.0001 for 5-digit pairs and
                # 0.01 for JPY-like pairs. We compute pips as raw / tick_size
                # multiplied by a standard pip size derived from tick_size.
                raw = float(spread_raw)
                ts = float(tick_size)
                # Determine pip unit: if tick_size < 0.001 use 0.0001, else 0.01
                pip_unit = 0.0001 if ts <= 0.0001 else 0.01 if ts >= 0.01 else 0.0001
                spread_pips = raw / pip_unit
        except Exception:
            spread_pips = None

        market = MarketSnapshot(
            requested_symbol,
            mt5_symbol,
            raw_market.get("timeframes", {}),
            raw_market.get("bid"),
            raw_market.get("ask"),
            spread_raw,
            tick_size,
            tick_value,
            spread_pips,
            bool(raw_market.get("stale")),
            raw_market.get("error"),
        )
        if market.error or market.stale or any(not market.timeframes.get(tf) for tf in required_timeframes):
            return WorkflowResult(WorkflowState.NO_SETUP, "NO_SETUP: MT5 market data is missing or stale.", account=account, market=market)

        analysis = analyze_structure(market.timeframes, profile=self.profile)
        if not analysis["valid"]:
            return WorkflowResult(WorkflowState.REJECTED, f"REJECTED: {analysis['reason']}", account=account, market=market, details={"analysis": analysis})

        news_context = assess_news(mt5_symbol, analysis["direction"])
        analysis = {**analysis, "news_context": news_context}
        base_score = analysis.get("confluence", {}).get("score", 0)
        adjusted_score = max(0, min(10, base_score + news_context.get("score_adjustment", 0)))
        analysis["confluence"] = {
            **analysis.get("confluence", {}),
            "base_score": base_score,
            "news_adjustment": news_context.get("score_adjustment", 0),
            "score": adjusted_score,
            "news_reason": news_context.get("reason", ""),
            "ready": adjusted_score >= self.profile.minimum_score,
        }
        if adjusted_score < self.profile.minimum_score:
            return WorkflowResult(
                WorkflowState.REJECTED,
                f"REJECTED: SMC/indicator score {base_score}/10 adjusted to {adjusted_score}/10 by news risk.",
                account=account,
                market=market,
                details={"analysis": analysis, "news_context": news_context},
            )

        latest = market.timeframes[self.profile.entry_timeframe][-1]
        entry = float(market.ask if analysis["direction"] == "BUY" and market.ask else market.bid if analysis["direction"] == "SELL" and market.bid else latest["close"])
        setup_candles = market.timeframes[self.profile.setup_timeframe][-20:]
        lows = [float(c["low"]) for c in setup_candles]
        highs = [float(c["high"]) for c in setup_candles]
        tick_size = float(specs.get("tick_size", 0) or 0)
        structural_buffer = tick_size * 2 if tick_size > 0 else 0.0
        stop_loss = (
            min(lows) - structural_buffer
            if analysis["direction"] == "BUY"
            else max(highs) + structural_buffer
        )
        distance = abs(entry - stop_loss)
        smc_data = analysis.get("smc", {}) or {}
        structural_target = smc_data.get("opposing_liquidity") or smc_data.get("structural_target")
        minimum_target = (
            entry + distance * self.minimum_rr
            if analysis["direction"] == "BUY"
            else entry - distance * self.minimum_rr
        )
        if structural_target is None:
            take_profit = minimum_target
        elif (
            structural_target >= minimum_target
            if analysis["direction"] == "BUY"
            else structural_target <= minimum_target
        ):
            take_profit = float(structural_target)
        else:
            return WorkflowResult(
                WorkflowState.REJECTED,
                "REJECTED: Structural target cannot provide the configured minimum risk/reward.",
                account=account,
                market=market,
                details={"analysis": analysis, "target": structural_target, "minimum_target": minimum_target},
            )
        specs = raw_market.get("symbol_specs", {})

        point = float(specs.get("point", 0) or 0)
        stops_level = float(specs.get("trade_stops_level", 0) or 0)
        if point > 0 and stops_level > 0 and distance < stops_level * point:
            return WorkflowResult(
                WorkflowState.REJECTED,
                "REJECTED: Structural stop is inside the broker's minimum stop distance.",
                account=account,
                market=market,
                details={"analysis": analysis, "failure_stage": "broker_stop_distance", "stop_distance": distance, "minimum_stop_distance": stops_level * point},
            )

        expected_hold_days = self.profile.expected_hold_days
        weekend_exposure = (
            self.profile.mode.value == "SWING_TRADING"
            and datetime.now(timezone.utc).weekday() + expected_hold_days >= 5
        )
        if weekend_exposure and not self.profile.allow_weekend_holding:
            return WorkflowResult(
                WorkflowState.REJECTED,
                "REJECTED: Swing plan would cross the weekend and weekend holding is disabled.",
                account=account,
                market=market,
                details={"analysis": analysis, "failure_stage": "weekend_policy", "expected_hold_days": expected_hold_days},
            )

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
            minimum_free_margin=risk["minimum_free_margin"],
            current_margin_level=account.margin_level,
            spread=market.spread,
            spread_pips=market.spread_pips,
            minimum_rr=self.minimum_rr,
            maximum_spread_pips=self.profile.max_spread_pips,
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

        spread_cost = None
        if market.spread is not None and market.tick_size and market.tick_value:
            spread_cost = abs(float(market.spread) / float(market.tick_size) * float(market.tick_value) * risk["volume"])
        commission_per_lot = specs.get("commission_per_lot")
        commission_cost = None
        if commission_per_lot is not None:
            commission_cost = abs(float(commission_per_lot) * risk["volume"])

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
            trading_mode=self.trading_mode.value,
            profile=self.profile.as_dict(),
            smc_analysis=analysis.get("smc", {}),
            news_context=news_context,
            equity_at_decision=account.equity,
            spread_price=market.spread,
            spread_points=(float(market.spread) / float(market.tick_size) if market.spread is not None and market.tick_size else None),
            spread_pips=market.spread_pips,
            calculated_volume=risk["calculated_volume"],
            actual_risk_amount=risk["actual_risk_amount"],
            estimated_swap_cost=(
                abs(float(specs.get("swap_long" if analysis["direction"] == "BUY" else "swap_short", 0) or 0))
                * risk["volume"] * expected_hold_days
                if str(specs.get("swap_mode", "")).lower() in {"0", "currency"}
                else None
            ),
            estimated_spread_cost=spread_cost,
            estimated_commission=commission_cost,
            weekend_exposure=weekend_exposure,
            expected_hold_days=expected_hold_days,
            broker=account.broker,
            platform=account.platform,
            account_login=account.login,
        )
        self._plans[plan.confirmation_phrase] = plan
        self._active_plans[active_key] = plan
        return WorkflowResult(
            WorkflowState.APPROVAL_REQUIRED,
            "APPROVAL_REQUIRED: trade plan ready for your review.",
            plan=plan,
            account=account,
            market=market,
            details={"analysis": analysis, "safety": safety, "confluence": confluence, "portfolio_limits": portfolio, "pipeline": ["DETECTED", "ANALYZING", "VALIDATING_SETUP", "RISK_CHECK"]},
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
                return WorkflowResult(
                    WorkflowState.EXPIRED,
                    f"EXPIRED: {message}",
                    plan=plan,
                    details={"failure_stage": "revalidation", "reason": message},
                )
            return WorkflowResult(
                WorkflowState.REJECTED,
                f"REFUSED: {message}",
                plan=plan,
                details={"failure_stage": "revalidation", "reason": message},
            )

        response = self.adapter.execute(plan.as_dict(), plan.account_mode)
        if not response.get("success"):
            return WorkflowResult(
                WorkflowState.REJECTED,
                f"MT5 did not confirm execution: {response.get('error', 'unknown error')}",
                plan=plan,
                details={"failure_stage": "mt5_order_send", "reason": response.get("error", "unknown error"), "mt5_response": response},
            )

        self._active_plans.pop(f"{plan.mt5_symbol}:{plan.account_mode}", None)
        self._plans.pop(plan.confirmation_phrase, None)
        return WorkflowResult(WorkflowState.EXECUTED, "EXECUTED: MT5 confirmed the order execution.", plan=plan, details=response)
