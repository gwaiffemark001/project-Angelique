from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from core import config
from core.price_units import spread_policy, instrument_class


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
    minimum_score: int = 70
    minimum_rr: float = config.TRADING_MIN_RR
    sl_atr_multiplier: float = 0.5
    monitor_interval_seconds: int = 10
    expected_hold_days: int = 1
    allow_weekend_holding: bool = False
    strategy_mode: str = "AUTO"
    # Retained for compatibility with older callers; symbol-aware policies
    # below are authoritative.
    max_spread_metal_points: float = 40.0

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
        return ("D1", "H4", "H1", "M15", "M5")

    @property
    def analysis_optional_timeframes(self) -> tuple[str, ...]:
        if self.mode is TradingMode.SWING:
            return ("M15", "MN")
        return ("D1", "M30", "M1", "W1", "MN")

    def candle_count(self, timeframe: str) -> int:
        """Return the fetch depth needed by the profile, including indicator warm-up."""
        tf = str(timeframe).upper()
        if self.mode is TradingMode.SWING:
            return {"W1": 220, "D1": 300, "H4": 300, "H1": 250, "M15": 120, "MN": 100}.get(tf, 150)
        return {"D1": 220, "H4": 250, "H1": 250, "M30": 180, "M15": 180, "M5": 120, "M1": 120}.get(tf, 150)

    def minimum_analysis_candles(self, timeframe: str) -> int:
        """Minimum closed history required to compute the actual strategy inputs.

        This is deliberately lower than the fetch depth on short entry frames.
        EMA200 is the deepest common indicator, so trend frames retain a 205+
        requirement while entry/context frames are not unnecessarily blocked.
        """
        tf = str(timeframe).upper()
        if self.mode is TradingMode.SWING:
            return {"W1": 205, "D1": 205, "H4": 205, "H1": 80}.get(tf, 60)
        return {"D1": 205, "H4": 205, "H1": 205, "M15": 80, "M5": 60}.get(tf, 60)

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
    """Return the symbol-aware maximum spread display value."""
    profile = get_trading_profile(mode)
    return float(spread_policy(symbol, {}, profile.mode.value)["max_value"])


def is_metal_symbol(symbol: str) -> bool:
    return instrument_class(symbol) == "METAL"


def max_spread_points_for_symbol(symbol: str, mode: TradingMode | str | None = None) -> float:
    """Compatibility helper returning a point ceiling where it is defined."""
    profile = get_trading_profile(mode)
    policy = spread_policy(symbol, {}, profile.mode.value)
    klass = policy.get("instrument_class")
    if klass in {"FX_MAJOR", "FX_CROSS"}:
        # Conventional 10 MT5 points per FX pip for fractional pricing.
        return float(policy["max_value"]) * 10.0
    return float(policy["max_value"])


def max_spread_policy(symbol: str, specs: dict | None = None, mode: TradingMode | str | None = None) -> dict:
    profile = get_trading_profile(mode)
    return spread_policy(symbol, specs or {}, profile.mode.value)

def get_trading_profile(mode: TradingMode | str | None = None) -> TradingProfile:
    return PROFILES[normalize_trading_mode(mode)]
