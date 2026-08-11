from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .indicators import snapshot
from .smc import detect_smc


def _trend(candles: list[dict[str, Any]]) -> str:
    closes = [float(c.get("close", 0)) for c in candles if float(c.get("close", 0)) > 0]
    if len(closes) < 3:
        return "unknown"
    if closes[-1] > closes[0] and closes[-1] > closes[-2]:
        return "bullish"
    if closes[-1] < closes[0] and closes[-1] < closes[-2]:
        return "bearish"
    return "sideways"


@dataclass(frozen=True)
class MarketContext:
    trends: dict[str, str]
    indicators: dict[str, dict[str, Any]]
    smc: dict[str, dict[str, Any]]
    direction: str | None = None
    confluence: dict[str, Any] = field(default_factory=dict)


def build_market_context(timeframes: dict[str, list[dict[str, Any]]]) -> MarketContext:
    trends = {timeframe: _trend(candles) for timeframe, candles in timeframes.items()}
    indicator_data = {timeframe: snapshot(candles) for timeframe, candles in timeframes.items()}
    smc_data = {timeframe: detect_smc(candles) for timeframe, candles in timeframes.items()}
    return MarketContext(trends=trends, indicators=indicator_data, smc=smc_data)
