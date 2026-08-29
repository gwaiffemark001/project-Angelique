from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .indicators import snapshot
from .smc import detect_smc

# Import ICT core concepts
try:
    from skills.trading.ict_core import (
        detect_amd_phase,
        is_prime_time,
        analyze_premium_discount,
        identify_ote_zone,
    )
    ICT_AVAILABLE = True
except ImportError:
    ICT_AVAILABLE = False


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
    ict: dict[str, Any] = field(default_factory=dict)
    direction: str | None = None
    confluence: dict[str, Any] = field(default_factory=dict)


def build_market_context(timeframes: dict[str, list[dict[str, Any]]]) -> MarketContext:
    trends = {timeframe: _trend(candles) for timeframe, candles in timeframes.items()}
    indicator_data = {timeframe: snapshot(candles) for timeframe, candles in timeframes.items()}
    smc_data = {timeframe: detect_smc(candles) for timeframe, candles in timeframes.items()}
    
    # Build ICT context if available
    ict_data = {}
    if ICT_AVAILABLE:
        try:
            # Get current UTC time for session analysis
            current_time = datetime.now(timezone.utc)
            
            # Detect AMD phase using the most recent timeframe data
            latest_timeframe = list(timeframes.keys())[-1] if timeframes else None
            if latest_timeframe and timeframes[latest_timeframe]:
                # Convert candles to DataFrame format for ICT analysis
                import pandas as pd
                candles_df = pd.DataFrame(timeframes[latest_timeframe])
                if not candles_df.empty:
                    # AMD Cycle Detection
                    amd_cycle = detect_amd_phase(candles_df, current_time)
                    ict_data["amd_phase"] = amd_cycle.current_phase.value
                    ict_data["amd_cycle"] = {
                        "phase": amd_cycle.current_phase.value,
                        "accumulation_range": (amd_cycle.accumulation_low, amd_cycle.accumulation_high),
                        "is_complete": amd_cycle.is_complete,
                    }
                    
                    # Session Timing
                    ict_data["is_prime_time"] = is_prime_time(current_time)
                    ict_data["current_session"] = "unknown"
                    from skills.trading.ict_core import get_current_session
                    session = get_current_session(current_time)
                    if session:
                        ict_data["current_session"] = session.name
                        ict_data["session_is_prime"] = session.is_prime
                    
                    # Premium/Discount Analysis
                    pd_analysis = analyze_premium_discount(candles_df, lookback=50)
                    ict_data["premium_discount"] = pd_analysis
                    
                    # OTE Zone Detection
                    ote_zone = identify_ote_zone(candles_df, lookback=20)
                    if ote_zone:
                        ict_data["ote_zone"] = ote_zone
        except Exception:
            # Fallback if ICT analysis fails
            ict_data = {"error": "ICT analysis unavailable", "fallback": True}
    
    return MarketContext(trends=trends, indicators=indicator_data, smc=smc_data, ict=ict_data)
