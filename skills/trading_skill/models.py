from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timezone
from typing import Any


class WorkflowState(str, Enum):
    REQUESTED = "REQUESTED"
    DATA_READY = "DATA_READY"
    ANALYZED = "ANALYZED"
    PLANNED = "PLANNED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    NO_SETUP = "NO_SETUP"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    TRADE_READY = "TRADE_READY"


@dataclass(frozen=True)
class AccountSnapshot:
    requested_mode: str
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


@dataclass(frozen=True)
class MarketSnapshot:
    requested_symbol: str
    mt5_symbol: str | None
    timeframes: dict[str, list[dict[str, Any]]]
    bid: float | None = None
    ask: float | None = None
    spread: float | None = None
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
    rationale: tuple[str, ...]
    confirmation_phrase: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

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
            "rationale": list(self.rationale),
            "confirmation_phrase": self.confirmation_phrase,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class WorkflowResult:
    state: WorkflowState
    message: str
    plan: TradePlan | None = None
    account: AccountSnapshot | None = None
    market: MarketSnapshot | None = None
    details: dict[str, Any] = field(default_factory=dict)
