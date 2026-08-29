from __future__ import annotations

from threading import RLock
from datetime import datetime, timezone
from typing import Any
from .account import account_snapshot, normalize_mode
from .account_manager import account_manager
from .analysis import analyze_structure
from .data_quality import assess_candles
from .event_logging import log_event
from .models import MarketSnapshot, TradePlan, WorkflowResult, WorkflowState
from .smc import ZoneRegistry
from .profiles import TradingMode, get_trading_profile, max_spread_for_symbol, max_spread_points_for_symbol, normalize_trading_mode
from core import config
from .risk import build_risk, validate_profile_limits, effective_risk_percent
from .safety import validate_trade_setup
from .news_context import assess_news
from .symbols import resolve
from core.price_units import normalize_spread


class TradingWorkflow:
    """The only orchestration API for analysis, planning, approval, and execution."""

    def __init__(self, adapter, risk_percent: float | None = None, minimum_rr: float | None = None, trading_mode: TradingMode | str | None = None):
        self.adapter = adapter
        self.trading_mode = normalize_trading_mode(trading_mode)
        self.profile = get_trading_profile(self.trading_mode)
        self.risk_percent = self.profile.risk_per_trade if risk_percent is None else risk_percent
        self.minimum_rr = self.profile.minimum_rr if minimum_rr is None else minimum_rr
        self._plans: dict[str, TradePlan] = {}
        self._active_plans: dict[str, TradePlan] = {}
        self._execution_lock = RLock()
        self._zone_registry = ZoneRegistry()

    def _is_expired(self, plan: TradePlan) -> bool:
        try:
            return datetime.fromisoformat(plan.expires_at) <= datetime.now(timezone.utc)
        except Exception:
            return True

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
        if (fresh_news.get("high_impact_imminent") or fresh_news.get("directional_conflict")) and not plan.requires_manual_approval:
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
                new_risk_percent=plan.risk_percent,
            )
            if not portfolio["valid"]:
                return False, f"Portfolio limit failed during revalidation: {'; '.join(portfolio['reasons'])}"

        required_timeframes = plan_profile.analysis_required_timeframes
        revalidation_count = max(plan_profile.candle_count(timeframe) for timeframe in required_timeframes)
        raw_market = self.adapter.market(plan.mt5_symbol, required_timeframes, plan.account_mode, revalidation_count)
        specs = raw_market.get("symbol_specs", {}) or {}
        tick_size = specs.get("tick_size")
        tick_value = specs.get("tick_value")
        spread_raw = raw_market.get("spread")
        spread_pips = None
        spread_points = None
        spread_price = float(spread_raw) if spread_raw is not None else None
        spread_unit = None
        try:
            if spread_raw is not None:
                normalized = normalize_spread(plan.mt5_symbol, float(spread_raw), specs)
                spread_pips = normalized.get("spread_pips")
                spread_points = normalized.get("spread_points")
                spread_price = normalized.get("spread_price")
                spread_unit = normalized.get("spread_unit")
        except Exception:
            spread_pips = spread_points = None


        market = MarketSnapshot(plan.requested_symbol, plan.mt5_symbol, raw_market.get("timeframes", {}), raw_market.get("bid"), raw_market.get("ask"), spread_raw, tick_size, tick_value, spread_pips, bool(raw_market.get("stale")), raw_market.get("error"), spread_points=spread_points, spread_price=spread_price, spread_unit=spread_unit)
        if market.error or market.stale or any(not market.timeframes.get(tf) for tf in required_timeframes):
            return False, "Market data unavailable or stale during revalidation."
        if any(assess_candles(market.timeframes.get(tf, []), tf)["status"] == "stale" for tf in required_timeframes):
            return False, "Required candle data is stale during revalidation."

        if market.bid is None or market.ask is None:
            return False, "Fresh bid/ask data unavailable during revalidation."

        current_price = market.ask if plan.direction == "BUY" else market.bid
        slippage = abs(current_price - plan.entry)
        acceptable_slippage = max(plan.entry * 0.0005, 0.0005)
        if slippage > acceptable_slippage:
            return False, f"Price moved too far from the approved entry ({current_price:.6f} vs {plan.entry:.6f})."

        fresh_analysis = analyze_structure(market.timeframes, profile=plan_profile, registry=self._zone_registry)
        expected_decision = "BUY_PLAN_READY" if plan.direction == "BUY" else "SELL_PLAN_READY"
        if not fresh_analysis.get("valid"):
            return False, "Technical setup changed before execution; the approved plan is stale."
        fresh_score = float((fresh_analysis.get("confluence") or {}).get("score", 0) or 0)
        fresh_minimum = int(plan_profile.minimum_score)
        if fresh_score < fresh_minimum:
            return False, f"Fresh confluence score {fresh_score:.0f}/10 is below the required {fresh_minimum}/10."
        if fresh_analysis.get("decision") != expected_decision:
            return False, "Technical setup changed before execution; the approved plan is stale."

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
            symbol=plan.mt5_symbol,
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
            projected_margin_level=risk["projected_margin_level"],
            spread=market.spread,
            spread_pips=market.spread_pips,
            spread_points=market.spread_points,
            minimum_rr=plan_profile.minimum_rr,
            maximum_spread_pips=max_spread_for_symbol(plan.mt5_symbol, plan_profile.mode),
            maximum_spread_points=max_spread_points_for_symbol(plan.mt5_symbol, plan_profile.mode),
        )
        if not safety["valid"]:
            return False, f"Revalidation safety failed: {'; '.join(safety['reasons'])}"

        if abs(risk["volume"] - plan.volume) > 1e-8:
            return False, "Calculated volume changed during revalidation."
        return True, "Revalidation passed."

    def prepare(self, requested_symbol: str, account_mode: str = "demo", count: int | None = None, risk_percent: float | None = None) -> WorkflowResult:
        mode = normalize_mode(account_mode)
        try:
            raw_account = self.adapter.account(mode, symbol=requested_symbol)
        except TypeError:
            raw_account = self.adapter.account(mode)
        account = account_snapshot(raw_account, mode)
        try:
            effective_risk = effective_risk_percent(
                account.equity,
                self.risk_percent if risk_percent is None else risk_percent,
            )
        except ValueError as exc:
            return WorkflowResult(
                WorkflowState.REJECTED,
                f"REJECTED: risk policy could not be determined: {exc}",
                decision_state="REJECTED",
                account=account,
            )
        if not account.connected:
            return WorkflowResult(WorkflowState.NO_SETUP, "NO_SETUP: the selected MT5 account is not connected.", decision_state="NO_SETUP", account=account)
        authorized, authorization_message, _ = account_manager.validate_authorization(mode)
        if not authorized:
            log_event(30, "workflow.authorization_rejected", requested_mode=account_mode, resolved_mode=mode, message=authorization_message)
            return WorkflowResult(WorkflowState.NO_SETUP, f"NO_SETUP: authorization failed: {authorization_message}", decision_state="NO_SETUP", account=account, details={"authorization": authorization_message})

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
        try:
            available = self.adapter.symbols(mode, requested_symbol)
        except TypeError:
            available = self.adapter.symbols(mode)
        mt5_symbol = resolve(requested_symbol, available)
        if not mt5_symbol:
            return WorkflowResult(WorkflowState.NO_SETUP, "NO_SETUP: the requested symbol is not available in MT5.", account=account, details={"available_symbols": available})

        portfolio = validate_profile_limits(
            raw_account,
            list(positions_response.get("positions", []) or []),
            self.profile,
            new_risk_percent=effective_risk,
            symbol=mt5_symbol,
        )
        if not portfolio["valid"]:
            return WorkflowResult(
                WorkflowState.REJECTED,
                f"REJECTED: {'; '.join(portfolio['reasons'])}",
                account=account,
                details={"portfolio_limits": portfolio},
            )

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

        required_timeframes = self.profile.analysis_required_timeframes
        request_count = count if count is not None else max(self.profile.candle_count(timeframe) for timeframe in required_timeframes)
        raw_market = self.adapter.market(mt5_symbol, required_timeframes, mode, request_count)
        # Extract tick specs when provided by the bridge so we can normalize
        # spread into pips (symbol-dependent). The bridge returns 'symbol_specs'
        # with 'tick_size' and 'tick_value' where available.
        specs = raw_market.get("symbol_specs", {}) or {}
        tick_size = specs.get("tick_size")
        tick_value = specs.get("tick_value")
        spread_raw = raw_market.get("spread")
        spread_pips = None
        spread_points = None
        spread_price = float(spread_raw) if spread_raw is not None else None
        spread_unit = None
        try:
            if spread_raw is not None:
                normalized = normalize_spread(mt5_symbol, float(spread_raw), specs)
                spread_pips = normalized.get("spread_pips")
                spread_points = normalized.get("spread_points")
                spread_price = normalized.get("spread_price")
                spread_unit = normalized.get("spread_unit")
        except Exception:
            spread_pips = spread_points = None


        market = MarketSnapshot(
            requested_symbol, mt5_symbol, raw_market.get("timeframes", {}),
            raw_market.get("bid"), raw_market.get("ask"), spread_raw,
            tick_size, tick_value, spread_pips, bool(raw_market.get("stale")),
            raw_market.get("error"), spread_points=spread_points,
            spread_price=spread_price, spread_unit=spread_unit,
        )
        quality = {tf: assess_candles(market.timeframes.get(tf, []), tf) for tf in required_timeframes}
        missing_data = [tf for tf, result in quality.items() if result["status"] != "fresh"]
        missing_specs = [name for name, value in {
            "tick_size": tick_size,
            "tick_value": tick_value,
            "volume_min": specs.get("volume_min"),
            "volume_step": specs.get("volume_step"),
        }.items() if value in (None, 0, "")]
        missing_market = [name for name, value in {"bid": market.bid, "ask": market.ask, "spread": market.spread}.items() if value is None]
        missing_specs.extend(name for name, value in {"point": specs.get("point"), "digits": specs.get("digits")}.items() if value in (None, 0, ""))
        if market.error or market.stale or missing_data or missing_specs or missing_market or (spread_pips is None and spread_points is None):
            blockers = {
                "candles": {tf: quality[tf] for tf in missing_data},
                "symbol_specs": missing_specs,
                "market": missing_market,
                "spread": ["normalized_spread"] if (spread_pips is None and spread_points is None) else [],
            }
            return WorkflowResult(WorkflowState.BLOCKED_BY_DATA, "BLOCKED_BY_DATA: required broker data is missing, invalid, or stale.", decision_state="BLOCKED_BY_DATA", account=account, market=market, details={"data_blockers": blockers})

        analysis = analyze_structure(market.timeframes, profile=self.profile, registry=self._zone_registry)
        if not analysis["valid"]:
            return WorkflowResult(WorkflowState.NO_SETUP, f"NO_SETUP: {analysis['reason']}", decision_state="NO_SETUP", account=account, market=market, details={"analysis": analysis})
        if analysis.get("decision") != ("BUY_PLAN_READY" if analysis.get("direction") == "BUY" else "SELL_PLAN_READY"):
            decision = analysis.get("decision", "NO_SETUP")
            state = WorkflowState.WAITING if decision == "WAIT" else WorkflowState.NO_SETUP
            return WorkflowResult(
                state,
                f"{decision}: {analysis.get('reason', 'SMC sequence is incomplete.')}",
                decision_state=decision,
                account=account,
                market=market,
                details={"analysis": analysis, "decision": decision, "audit": analysis.get("setup_assessment", {})},
            )

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
        score_passed = adjusted_score >= self.profile.minimum_score
        analysis["confluence"] = {**analysis["confluence"], "score_passed": score_passed, "minimum_score": self.profile.minimum_score}
        if not score_passed:
            return WorkflowResult(
                WorkflowState.WAIT,
                f"WAIT: confluence score {adjusted_score:.0f}/10 is below the required {self.profile.minimum_score}/10.",
                decision_state="WAIT",
                account=account,
                market=market,
                details={
                    "analysis": analysis,
                    "failure_stage": "confluence_score",
                    "score": adjusted_score,
                    "minimum_score": self.profile.minimum_score,
                    "score_passed": False,
                },
            )

        # A high-impact calendar release is imminent, or scraped headline
        # bias conflicts with the SMC direction: don't block the plan
        # outright, hold it for explicit approval instead. Every other
        # gate below (structure, risk, margin, spread, RR, portfolio
        # limits) still applies in full; this only changes whether the
        # finished plan is allowed to auto-execute at the bottom of this
        # method.
        manual_hold = bool(news_context.get("high_impact_imminent") or news_context.get("directional_conflict"))
        manual_hold_reason = news_context.get("reason", "") if manual_hold else ""

        latest = market.timeframes[self.profile.entry_timeframe][-1]
        entry = float(market.ask if analysis["direction"] == "BUY" and market.ask else market.bid if analysis["direction"] == "SELL" and market.bid else latest["close"])
        setup_candles = market.timeframes[self.profile.setup_timeframe][-20:]
        lows = [float(c["low"]) for c in setup_candles]
        highs = [float(c["high"]) for c in setup_candles]
        tick_size = float(specs.get("tick_size", 0) or 0)
        structural_buffer = tick_size * 2 if tick_size > 0 else 0.0
        selected_zone = analysis.get("setup_assessment", {}).get("zone")
        if not isinstance(selected_zone, dict):
            selected_zone = ((analysis.get("strategy") or {}).get("selected", {}) or {}).get("zone")
        zone_low = float(selected_zone.get("low", 0) or 0) if isinstance(selected_zone, dict) else 0.0
        zone_high = float(selected_zone.get("high", 0) or 0) if isinstance(selected_zone, dict) else 0.0
        stop_loss = (
            min(zone_low if zone_low > 0 else min(lows), min(lows)) - structural_buffer
            if analysis["direction"] == "BUY"
            else max(zone_high if zone_high > 0 else max(highs), max(highs)) + structural_buffer
        )
        distance = abs(entry - stop_loss)
        smc_data = analysis.get("smc", {}) or {}
        structural_target_data = analysis.get("setup_assessment", {}).get("target_liquidity")
        structural_target = structural_target_data.get("price") if isinstance(structural_target_data, dict) else None
        if structural_target is None:
            selected_strategy = (analysis.get("strategy") or {}).get("selected", {})
            structural_target = selected_strategy.get("target")

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
                WorkflowState.BLOCKED_BY_RISK,
                "REJECTED: Structural target cannot provide the configured minimum risk/reward.",
                decision_state="BLOCKED_BY_RISK",
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
                effective_risk,
                specs,
                free_margin=account.free_margin,
                used_margin=account.used_margin,
                minimum_free_margin=config.TRADING_MIN_FREE_MARGIN,
                current_margin_level=account.margin_level,
            )
        except ValueError as exc:
            return WorkflowResult(WorkflowState.BLOCKED_BY_RISK, f"BLOCKED_BY_RISK: {exc}", decision_state="BLOCKED_BY_RISK", account=account, market=market, details={"analysis": analysis})

        safety = validate_trade_setup(
            symbol=mt5_symbol,
            direction=analysis["direction"],
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_amount=risk["risk_amount"],
            risk_percent=effective_risk,
            volume=risk["volume"],
            margin_required=risk["margin_required"],
            free_margin_after=risk["free_margin_after"],
            minimum_free_margin=risk["minimum_free_margin"],
            projected_margin_level=risk["projected_margin_level"],
            spread=market.spread,
            spread_pips=market.spread_pips,
            spread_points=market.spread_points,
            minimum_rr=self.minimum_rr,
            maximum_spread_pips=max_spread_for_symbol(mt5_symbol, self.profile.mode),
            maximum_spread_points=max_spread_points_for_symbol(mt5_symbol, self.profile.mode),
        )
        if not safety["valid"]:
            return WorkflowResult(WorkflowState.BLOCKED_BY_RISK, f"BLOCKED_BY_RISK: {'; '.join(safety['reasons'])}", decision_state="BLOCKED_BY_RISK", account=account, market=market, details={"analysis": analysis, "safety": safety})

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
            "Automatic execution is permitted when all gates pass; high-impact/news-conflict plans require explicit approval.",
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
            effective_risk,
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
            analysis_audit={
                "decision_state": "BUY_PLAN_READY" if analysis["direction"] == "BUY" else "SELL_PLAN_READY",
                "setup_assessment": analysis.get("setup_assessment", {}),
                "support_resistance": analysis.get("stages", {}).get("support_resistance", {}),
                "confluence": confluence,
            },
            requires_manual_approval=manual_hold,
            manual_approval_reason=manual_hold_reason,
        )
        self._plans[plan.confirmation_phrase] = plan
        self._active_plans[active_key] = plan
        return WorkflowResult(
            WorkflowState.APPROVAL_REQUIRED,
            (
                f"APPROVAL_REQUIRED: news risk requires your review. {manual_hold_reason}"
                if manual_hold else
                "APPROVAL_REQUIRED: trade plan ready; auto-execution is permitted."
            ),
            decision_state="BUY_PLAN_READY" if analysis["direction"] == "BUY" else "SELL_PLAN_READY",
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
        with self._execution_lock:
            return self._execute_locked(confirmation_phrase)

    def _execute_locked(self, confirmation_phrase: str) -> WorkflowResult:
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

        # Consume the approval BEFORE the network submission. An accepted, rejected,
        # timed-out, or otherwise failed order must never re-open the same approval popup.
        self._active_plans.pop(f"{plan.mt5_symbol}:{plan.account_mode}", None)
        self._plans.pop(plan.confirmation_phrase, None)
        response = self.adapter.execute(plan.as_dict(), plan.account_mode)
        if not response.get("success"):
            return WorkflowResult(
                WorkflowState.REJECTED,
                f"MT5 did not accept the order: {response.get('error', 'unknown error')}",
                plan=plan,
                details={"failure_stage": response.get("failure_stage", "mt5_order_send"), "reason": response.get("error", "unknown error"), "mt5_response": response},
            )
        verification = response.get("verification", "accepted")
        return WorkflowResult(WorkflowState.EXECUTED, f"EXECUTED: MT5 accepted the order ({verification}).", plan=plan, details=response)
