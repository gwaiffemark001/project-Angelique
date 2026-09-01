from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone, timedelta
from typing import Any


class WorkflowState(str, Enum):
    WAITING = "WAITING"
    DETECTED = "DETECTED"
    ANALYZING = "ANALYZING"
    VALIDATING_SETUP = "VALIDATING_SETUP"
    RISK_CHECK = "RISK_CHECK"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    OPEN = "OPEN"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"
    NO_SETUP = "NO_SETUP"
    TRADE_READY = "TRADE_READY"
    BLOCKED_BY_DATA = "BLOCKED_BY_DATA"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    BROKER_METADATA_INCOMPLETE = "BROKER_METADATA_INCOMPLETE"
    WAIT = "WAIT"
    BUY_PLAN_READY = "BUY_PLAN_READY"
    SELL_PLAN_READY = "SELL_PLAN_READY"
    BLOCKED_BY_RISK = "BLOCKED_BY_RISK"
    INVALID_SETUP = "INVALID_SETUP"


@dataclass(frozen=True)
class AccountSnapshot:
    requested_mode: str
    actual_mode: str
    connected: bool
    login: int | None
    balance: float = 0.0
    equity: float = 0.0
    used_margin: float = 0.0
    free_margin: float = 0.0
    margin_level: float = 0.0
    leverage: int = 0
    currency: str = "USD"
    error: str | None = None
    broker: str = ""
    platform: str = "MT5"
    daily_loss_percent: float | None = None
    weekly_loss_percent: float | None = None
    drawdown_percent: float = 0.0
    consecutive_losses: int = 0


@dataclass(frozen=True)
class MarketSnapshot:
    requested_symbol: str
    mt5_symbol: str | None
    timeframes: dict[str, list[dict[str, Any]]]
    bid: float | None = None
    ask: float | None = None
    spread: float | None = None
    # Normalized market tick information
    tick_size: float | None = None
    tick_value: float | None = None
    # Spread expressed in pips (normalized unit) when available
    spread_pips: float | None = None
    stale: bool = False
    error: str | None = None
    spread_points: float | None = None
    spread_ticks: float | None = None
    spread_price: float | None = None
    spread_unit: str | None = None
    instrument_class: str | None = None
    maximum_spread_value: float | None = None
    maximum_spread_unit: str | None = None
    maximum_spread_price: float | None = None


@dataclass(frozen=True)
class TradePlan:
    requested_symbol: str
    mt5_symbol: str
    direction: str
    order_type: str
    entry: float
    stop_loss: float
    take_profit: float
    volume: float
    risk_percent: float
    risk_amount: float
    margin_required: float
    free_margin_after: float
    projected_margin_level: float
    reward_to_risk: float
    account_mode: str
    opportunity_id: str
    rationale: tuple[str, ...]
    confirmation_phrase: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = field(default_factory=lambda: (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat())
    trading_mode: str = "DAY_TRADING"
    profile: dict[str, Any] = field(default_factory=dict)
    smc_analysis: dict[str, Any] = field(default_factory=dict)
    news_context: dict[str, Any] = field(default_factory=dict)
    equity_at_decision: float | None = None
    spread_price: float | None = None
    spread_points: float | None = None
    spread_pips: float | None = None
    calculated_volume: float | None = None
    actual_risk_amount: float | None = None
    actual_risk_percent: float | None = None
    strategy: str = "SMC"
    stop_basis: str = ""
    target_basis: str = ""
    stop_swing_id: str | None = None
    target_swing_id: str | None = None
    stop_swing_time: str | None = None
    target_swing_time: str | None = None
    stop_timeframe: str | None = None
    target_timeframe: str | None = None
    expected_profit_at_tp: float | None = None
    estimated_swap_cost: float | None = None
    estimated_spread_cost: float | None = None
    estimated_commission: float | None = None
    weekend_exposure: bool = False
    expected_hold_days: int = 1
    broker: str = ""
    platform: str = "MT5"
    account_login: int | None = None
    analysis_audit: dict[str, Any] = field(default_factory=dict)
    # When True, this plan is NOT auto-executable: a high-impact calendar
    # event is imminent or scraped news bias conflicts with the SMC
    # direction. Every other gate (setup completeness, risk, margin,
    # spread, RR, portfolio limits) has already passed by the time this
    # plan exists -- this is the one condition where a human should look
    # at it before it goes live.
    requires_manual_approval: bool = False
    manual_approval_reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_symbol": self.requested_symbol,
            "mt5_symbol": self.mt5_symbol,
            "symbol": self.mt5_symbol,
            "direction": self.direction,
            "order_type": self.order_type,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "volume": self.volume,
            "risk_percent": self.risk_percent,
            "risk_amount": self.risk_amount,
            "margin_required": self.margin_required,
            "free_margin_after": self.free_margin_after,
            "projected_margin_level": self.projected_margin_level,
            "reward_to_risk": self.reward_to_risk,
            "account_mode": self.account_mode,
            "opportunity_id": self.opportunity_id,
            "rationale": list(self.rationale),
            "confirmation_phrase": self.confirmation_phrase,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "trading_mode": self.trading_mode,
            "profile": dict(self.profile),
            "smc_analysis": dict(self.smc_analysis),
            "news_context": dict(self.news_context),
            "equity_at_decision": self.equity_at_decision,
            "spread_price": self.spread_price,
            "spread_points": self.spread_points,
            "spread_ticks": self.spread_ticks,
            "spread_pips": self.spread_pips,
            "calculated_volume": self.calculated_volume,
            "actual_risk_amount": self.actual_risk_amount,
            "actual_risk_percent": self.actual_risk_percent,
            "strategy": self.strategy,
            "stop_basis": self.stop_basis,
            "target_basis": self.target_basis,
            "stop_swing_id": self.stop_swing_id,
            "target_swing_id": self.target_swing_id,
            "stop_swing_time": self.stop_swing_time,
            "target_swing_time": self.target_swing_time,
            "stop_timeframe": self.stop_timeframe,
            "target_timeframe": self.target_timeframe,
            "expected_profit_at_tp": self.expected_profit_at_tp,
            "estimated_swap_cost": self.estimated_swap_cost,
            "estimated_spread_cost": self.estimated_spread_cost,
            "estimated_commission": self.estimated_commission,
            "weekend_exposure": self.weekend_exposure,
            "expected_hold_days": self.expected_hold_days,
            "broker": self.broker,
            "platform": self.platform,
            "account_login": self.account_login,
            "analysis_audit": dict(self.analysis_audit),
            "requires_manual_approval": self.requires_manual_approval,
            "manual_approval_reason": self.manual_approval_reason,
        }


@dataclass(frozen=True)
class WorkflowResult:
    state: WorkflowState
    message: str
    decision_state: str | None = None
    plan: TradePlan | None = None
    account: AccountSnapshot | None = None
    market: MarketSnapshot | None = None
    details: dict[str, Any] = field(default_factory=dict)
