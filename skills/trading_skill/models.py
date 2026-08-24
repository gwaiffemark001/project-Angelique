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
    estimated_swap_cost: float | None = None
    estimated_spread_cost: float | None = None
    estimated_commission: float | None = None
    weekend_exposure: bool = False
    expected_hold_days: int = 1
    broker: str = ""
    platform: str = "MT5"
    account_login: int | None = None

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
            "spread_pips": self.spread_pips,
            "calculated_volume": self.calculated_volume,
            "actual_risk_amount": self.actual_risk_amount,
            "estimated_swap_cost": self.estimated_swap_cost,
            "estimated_spread_cost": self.estimated_spread_cost,
            "estimated_commission": self.estimated_commission,
            "weekend_exposure": self.weekend_exposure,
            "expected_hold_days": self.expected_hold_days,
            "broker": self.broker,
            "platform": self.platform,
            "account_login": self.account_login,
        }


@dataclass(frozen=True)
class WorkflowResult:
    state: WorkflowState
    message: str
    plan: TradePlan | None = None
    account: AccountSnapshot | None = None
    market: MarketSnapshot | None = None
    details: dict[str, Any] = field(default_factory=dict)
