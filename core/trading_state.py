from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SUPPORTED_BROKER = "VALETAX"


@dataclass
class AccountState:
    requested_mode: str = "demo"
    actual_mode: str = "demo"
    connected: bool = False
    login: int | None = None
    balance: float = 0.0
    equity: float = 0.0
    used_margin: float = 0.0
    free_margin: float = 0.0
    margin_level: float = 0.0
    leverage: int = 0
    currency: str = "USD"
    broker: str = SUPPORTED_BROKER
    platform: str = "MT5"
    daily_loss_percent: float = 0.0
    weekly_loss_percent: float = 0.0
    status: str = "UNKNOWN"
    error: str | None = None
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class MarketState:
    symbol: str = ""
    resolved_symbol: str | None = None
    bid: float | None = None
    ask: float | None = None
    spread: float | None = None
    spread_pips: float | None = None
    stale: bool = False
    error: str | None = None
    timeframes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class SetupState:
    symbol: str = ""
    direction: str = ""
    state: str = "NO_SETUP"
    score: float | None = None
    risk_percent: float | None = None
    risk_amount: float | None = None
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    broker: str = SUPPORTED_BROKER
    requires_manual_approval: bool = False
    manual_approval_reason: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class TradingState:
    broker: str = SUPPORTED_BROKER
    account: AccountState = field(default_factory=AccountState)
    market: MarketState = field(default_factory=MarketState)
    setup: SetupState = field(default_factory=SetupState)
    auto_trading_enabled: bool = False
    system_health: str = "GREEN"
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def snapshot(self) -> dict[str, Any]:
        return {
            "broker": self.broker,
            "auto_trading_enabled": self.auto_trading_enabled,
            "system_health": self.system_health,
            "account": self.account.__dict__,
            "market": self.market.__dict__,
            "setup": self.setup.__dict__,
            "updated_at": self.updated_at,
        }
