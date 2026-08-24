from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from core import config


class TradingMode(str, Enum):
    DAY = "DAY_TRADING"
    SWING = "SWING_TRADING"


@dataclass(frozen=True)
class TradingProfile:
    mode: TradingMode
    context_timeframe: str
    trend_timeframe: str
    structure_timeframe: str
    setup_timeframe: str
    entry_timeframe: str
    risk_per_trade: float
    max_spread_pips: float
    max_open_risk: float
    max_positions: int
    max_daily_loss: float
    max_weekly_loss: float
    minimum_score: int = 7
    minimum_rr: float = config.TRADING_MIN_RR
    sl_atr_multiplier: float = 0.5
    monitor_interval_seconds: int = 10
    expected_hold_days: int = 1
    allow_weekend_holding: bool = False

    @property
    def required_timeframes(self) -> tuple[str, ...]:
        values = (
            self.context_timeframe,
            self.trend_timeframe,
            self.structure_timeframe,
            self.setup_timeframe,
            self.entry_timeframe,
        )
        return tuple(dict.fromkeys(values))

    def as_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["mode"] = self.mode.value
        values["required_timeframes"] = list(self.required_timeframes)
        return values


DAY_PROFILE = TradingProfile(
    mode=TradingMode.DAY,
    context_timeframe="H4",
    trend_timeframe="H1",
    structure_timeframe="M15",
    setup_timeframe="M15",
    entry_timeframe="M5",
    risk_per_trade=config.TRADING_DEFAULT_RISK_PERCENT,
    max_spread_pips=1.5,
    max_open_risk=1.0,
    max_positions=config.TRADING_MAX_SIMULTANEOUS_TRADES,
    max_daily_loss=config.TRADING_DAILY_LOSS_LIMIT_PERCENT,
    max_weekly_loss=config.TRADING_WEEKLY_LOSS_LIMIT_PERCENT,
    sl_atr_multiplier=0.5,
    monitor_interval_seconds=10,
)

SWING_PROFILE = TradingProfile(
    mode=TradingMode.SWING,
    context_timeframe="D1",
    trend_timeframe="D1",
    structure_timeframe="H4",
    setup_timeframe="H4",
    entry_timeframe="H1",
    risk_per_trade=config.TRADING_MAX_RISK_PERCENT,
    max_spread_pips=3.0,
    max_open_risk=2.0,
    max_positions=config.TRADING_MAX_SIMULTANEOUS_TRADES,
    max_daily_loss=config.TRADING_DAILY_LOSS_LIMIT_PERCENT,
    max_weekly_loss=config.TRADING_WEEKLY_LOSS_LIMIT_PERCENT,
    sl_atr_multiplier=1.0,
    monitor_interval_seconds=45,
    expected_hold_days=config.TRADING_SWING_EXPECTED_HOLD_DAYS,
    allow_weekend_holding=config.TRADING_SWING_ALLOW_WEEKEND_HOLDING,
)


PROFILES = {
    TradingMode.DAY: DAY_PROFILE,
    TradingMode.SWING: SWING_PROFILE,
}


def normalize_trading_mode(mode: TradingMode | str | None) -> TradingMode:
    if isinstance(mode, TradingMode):
        return mode
    value = str(mode or TradingMode.DAY.value).strip().upper()
    aliases = {
        "DAY": TradingMode.DAY,
        "DAY_TRADING": TradingMode.DAY,
        "SWING": TradingMode.SWING,
        "SWING_TRADING": TradingMode.SWING,
    }
    try:
        return aliases[value]
    except KeyError as exc:
        raise ValueError(f"Unsupported trading mode: {mode}") from exc


def get_trading_profile(mode: TradingMode | str | None = None) -> TradingProfile:
    return PROFILES[normalize_trading_mode(mode)]