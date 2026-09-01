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
    max_spread_points: float
    max_open_risk: float
    max_positions: int
    max_daily_loss: float
    max_weekly_loss: float
    minimum_score: int = 7
    #: Minimum strategy_quality_score (0-100) for an executable setup.
    #: POLICY, not a statistically validated threshold.
    minimum_quality_score: int = 70
    minimum_rr: float = config.TRADING_MIN_RR
    sl_atr_multiplier: float = 0.5
    monitor_interval_seconds: int = 10
    expected_hold_days: int = 1
    allow_weekend_holding: bool = False
    strategy_mode: str = "AUTO"
    # For non-FX instruments we use an explicit MT5-point ceiling rather than
    # pretending that a universal FX "pip" has the same meaning everywhere.
    max_spread_metal_points: float = 350.0

    @property
    def required_timeframes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((
            self.context_timeframe,
            self.trend_timeframe,
            self.structure_timeframe,
            self.setup_timeframe,
            self.entry_timeframe,
        )))

    @property
    def analysis_required_timeframes(self) -> tuple[str, ...]:
        if self.mode is TradingMode.SWING:
            return ("W1", "D1", "H4", "H1")
        return ("H4", "H1", "M15", "M5")

    @property
    def analysis_optional_timeframes(self) -> tuple[str, ...]:
        if self.mode is TradingMode.SWING:
            return ("M15", "MN")
        return ("D1", "M30", "M1", "W1", "MN")

    def candle_count(self, timeframe: str) -> int:
        """Candles to request.

        The depth is driven by the indicator warm-up requirements rather than
        by round numbers: a 200-period EMA cannot be evaluated on 250 candles,
        and silently reporting one anyway is how bad signals are produced.
        """
        from .indicators import required_history

        tf = str(timeframe).upper()
        if self.mode is TradingMode.SWING:
            base = {"W1": 220, "D1": 400, "H4": 400, "H1": 350, "M15": 250, "MN": 120}.get(tf, 250)
        else:
            base = {"D1": 300, "H4": 400, "H1": 400, "M30": 350, "M15": 350, "M5": 300, "M1": 250}.get(tf, 250)
        # Long-history timeframes (W1/MN) are limited by what exists at all.
        if tf in {"W1", "MN"}:
            return base
        return max(base, required_history())

    def analysis_windows(self, timeframe: str) -> dict[str, int]:
        depth = self.candle_count(timeframe)
        return {
            "market_structure": min(depth, 250),
            "support_resistance": min(depth, 400),
            "smc_liquidity": min(depth, 200),
            "entry_setup": min(depth, 75),
            "fvg_order_blocks": min(depth, 150),
            "trend": min(depth, 250),
            "recent_price_action": min(depth, 30),
            "bos_confirmation": min(depth, 150),
        }

    def as_dict(self) -> dict[str, object]:
        values = asdict(self)
        values["mode"] = self.mode.value
        values["required_timeframes"] = list(self.required_timeframes)
        values["analysis_required_timeframes"] = list(self.analysis_required_timeframes)
        values["analysis_optional_timeframes"] = list(self.analysis_optional_timeframes)
        return values


DAY_PROFILE = TradingProfile(
    mode=TradingMode.DAY,
    context_timeframe="H4",
    trend_timeframe="H1",
    structure_timeframe="M15",
    setup_timeframe="M15",
    entry_timeframe="M5",
    risk_per_trade=config.TRADING_RISK_PER_TRADE_PERCENT,
    max_spread_pips=1.5,
    max_spread_points=15.0,
    max_open_risk=1.0,
    max_positions=config.TRADING_MAX_SIMULTANEOUS_TRADES,
    max_daily_loss=config.TRADING_DAILY_LOSS_LIMIT_PERCENT,
    max_weekly_loss=config.TRADING_WEEKLY_LOSS_LIMIT_PERCENT,
    sl_atr_multiplier=0.5,
    monitor_interval_seconds=10,
)

SWING_PROFILE = TradingProfile(
    mode=TradingMode.SWING,
    context_timeframe="W1",
    trend_timeframe="D1",
    structure_timeframe="H4",
    setup_timeframe="H4",
    entry_timeframe="H1",
    risk_per_trade=config.TRADING_RISK_PER_TRADE_PERCENT,
    max_spread_pips=3.0,
    max_spread_points=30.0,
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
        raise ValueError(f"Unsupported trading mode: {mode}. Use DAY_TRADING or SWING_TRADING.") from exc


def max_spread_for_symbol(symbol: str, mode: TradingMode | str | None = None) -> float:
    """Return the maximum spread in the configured unit.

    For FX this is pips. For metals, callers should use max_spread_for_symbol
    only for UI text; enforcement is performed by safety.py using MT5 points.
    """
    profile = get_trading_profile(mode)
    return float(profile.max_spread_pips)


def is_metal_symbol(symbol: str) -> bool:
    name=str(symbol or "").upper()
    return any(token in name for token in ("XAU", "XAG", "XPT", "XPD", "GOLD", "SILVER"))


def max_spread_points_for_symbol(symbol: str, mode: TradingMode | str | None = None) -> float:
    profile=get_trading_profile(mode)
    return float(profile.max_spread_metal_points if is_metal_symbol(symbol) else profile.max_spread_points)


def get_trading_profile(mode: TradingMode | str | None = None) -> TradingProfile:
    return PROFILES[normalize_trading_mode(mode)]
