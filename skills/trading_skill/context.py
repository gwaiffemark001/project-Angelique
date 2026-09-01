from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .indicators import snapshot
from .evidence import detect_candle_pattern, detect_wave_context
from .market_structure import build_structure
from .smc import ZoneRegistry, detect_smc

# ICT helpers are used for supplementary context only. The AMD detector is
# deliberately NOT imported here any more: `smc.detect_smc` already produces
# the sequenced AMD phase machine from `amd.py`, and importing the older
# heuristic detector silently overwrote it.
try:
    from skills.trading.ict_core import is_prime_time, analyze_premium_discount, identify_ote_zone
    ICT_AVAILABLE = True
except ImportError:
    ICT_AVAILABLE = False


def _trend(candles: list[dict[str, Any]]) -> str:
    """Use structure first; fall back to a smoothed price slope.

    A single last-candle comparison was too noisy and could label a whole
    timeframe bullish/bearish from a tiny move.
    """
    if len(candles) < 9:
        return "unknown"
    try:
        bias = build_structure(candles).bias
        if bias in {"bullish", "bearish"}:
            return bias
    except Exception:
        pass
    closes = [float(c.get("close", 0) or 0) for c in candles if float(c.get("close", 0) or 0) > 0]
    if len(closes) < 20:
        return "unknown"
    fast = sum(closes[-10:]) / 10
    slow = sum(closes[-20:]) / 20
    if fast > slow and closes[-1] > closes[-5]:
        return "bullish"
    if fast < slow and closes[-1] < closes[-5]:
        return "bearish"
    return "sideways"


@dataclass(frozen=True)
class MarketContext:
    trends: dict[str, str]
    indicators: dict[str, dict[str, Any]]
    smc: dict[str, dict[str, Any]]
    ict: dict[str, Any] = field(default_factory=dict)
    direction: str | None = None
    confluence: dict[str, Any] = field(default_factory=dict)


def build_market_context(
    timeframes: dict[str, list[dict[str, Any]]],
    windows: dict[str, dict[str, int]] | None = None,
    registry: ZoneRegistry | None = None,
    *,
    trades_24_7: bool = False,
) -> MarketContext:
    windows = windows or {}
    trend_candles = {
        timeframe: candles[-windows.get(timeframe, {}).get("trend", len(candles)):]
        for timeframe, candles in timeframes.items()
    }
    smc_candles = {
        timeframe: candles[-windows.get(timeframe, {}).get("smc_liquidity", len(candles)):]
        for timeframe, candles in timeframes.items()
    }
    trends = {timeframe: _trend(candles) for timeframe, candles in trend_candles.items()}
    indicator_data = {timeframe: snapshot(candles) for timeframe, candles in timeframes.items()}
    smc_data = {}
    for timeframe, candles in smc_candles.items():
        # detect_smc already returns lifecycle-correct FVG/IFVG evidence and the
        # sequenced AMD result. Only genuinely supplementary observations are
        # merged in here -- nothing overwrites the canonical keys.
        evidence = detect_smc(candles, timeframe=timeframe, registry=registry,
                              trades_24_7=trades_24_7)
        evidence.setdefault("candle_pattern", detect_candle_pattern(candles))
        evidence.setdefault("wave_context", detect_wave_context(candles))
        smc_data[timeframe] = evidence
    return MarketContext(trends=trends, indicators=indicator_data, smc=smc_data)
