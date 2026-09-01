"""
ICT Core Concepts Module
Implements: Power of Three (AMD), Session Timing, Optimal Trade Entry (OTE)
"""
import pandas as pd
import numpy as np
from datetime import datetime, time, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

class MarketPhase(Enum):
    ACCUMULATION = "accumulation"
    MANIPULATION = "manipulation"
    DISTRIBUTION = "distribution"
    UNKNOWN = "unknown"

@dataclass
class AMDCycle:
    """Represents a Power of Three (Accumulation-Manipulation-Distribution) cycle"""
    start_time: datetime
    accumulation_low: float
    accumulation_high: float
    manipulation_low: float  # The "Judas Swing"
    manipulation_high: float
    current_phase: MarketPhase
    is_complete: bool = False

@dataclass
class SessionWindow:
    """Defines trading session windows for ICT timing"""
    name: str
    start: time
    end: time
    is_prime: bool  # High probability institutional activity

# ICT Session Times (UTC - Adjust based on server timezone if needed)
ICT_SESSIONS = [
    SessionWindow("Asian Range", time(0, 0), time(7, 0), is_prime=False),
    SessionWindow("London Open", time(7, 0), time(10, 0), is_prime=True),  # Key manipulation window
    SessionWindow("New York Open", time(13, 0), time(16, 0), is_prime=True),  # Key distribution window
    SessionWindow("London Close", time(15, 0), time(17, 0), is_prime=False),
]

def calculate_fib_retracements(swing_high: float, swing_low: float) -> Dict[str, float]:
    """
    Calculate key Fibonacci retracement levels for OTE
    Returns levels for 0.5, 0.618, 0.705, 0.786, 0.886
    """
    diff = swing_high - swing_low
    
    return {
        "0.00": swing_low if diff > 0 else swing_high,
        "0.382": swing_low + (diff * 0.382) if diff > 0 else swing_high - (abs(diff) * 0.382),
        "0.500": swing_low + (diff * 0.5),
        "0.618": swing_low + (diff * 0.618) if diff > 0 else swing_high - (abs(diff) * 0.618),
        "0.705": swing_low + (diff * 0.705) if diff > 0 else swing_high - (abs(diff) * 0.705),  # OTE Sweet Spot
        "0.786": swing_low + (diff * 0.786) if diff > 0 else swing_high - (abs(diff) * 0.786),
        "0.886": swing_low + (diff * 0.886) if diff > 0 else swing_high - (abs(diff) * 0.886),
        "1.00": swing_high if diff > 0 else swing_low,
    }

def calculate_ote(swing_high: float, swing_low: float) -> Dict[str, float]:
    """Return direction-aware ICT OTE bounds using 0.618/0.705/0.786."""
    high = float(swing_high)
    low = float(swing_low)
    if high < low:
        high, low = low, high
    span = high - low
    if span <= 0:
        raise ValueError("Swing high and swing low must define a positive range.")
    # Bullish: price retraces down from the high into the 61.8-78.6% zone.
    bullish_lower = high - span * 0.786
    bullish_sweet = high - span * 0.705
    bullish_upper = high - span * 0.618
    # Bearish: price retraces up from the low into the 61.8-78.6% zone.
    bearish_lower = low + span * 0.618
    bearish_sweet = low + span * 0.705
    bearish_upper = low + span * 0.786
    return {
        "swing_high": high, "swing_low": low, "equilibrium": low + span * 0.5,
        "bullish_lower": bullish_lower, "bullish_sweet_spot": bullish_sweet, "bullish_upper": bullish_upper,
        "bearish_lower": bearish_lower, "bearish_sweet_spot": bearish_sweet, "bearish_upper": bearish_upper,
        "range": span,
    }


def identify_ote_zone(df: pd.DataFrame, lookback: int = 50) -> Optional[Dict[str, float]]:
    """Identify the recent dealing range and direction-aware OTE zones."""
    if len(df) < max(20, lookback):
        return None
    recent = df.tail(lookback)
    swing_high = float(recent["high"].max())
    swing_low = float(recent["low"].min())
    current = float(df["close"].iloc[-1])
    levels = calculate_ote(swing_high, swing_low)
    return {
        **levels,
        "current_price": current,
        "is_discount": current < levels["equilibrium"],
        "is_premium": current > levels["equilibrium"],
        "in_bullish_ote": levels["bullish_lower"] <= current <= levels["bullish_upper"],
        "in_bearish_ote": levels["bearish_lower"] <= current <= levels["bearish_upper"],
    }


def detect_amd_phase(df: pd.DataFrame, current_time: datetime) -> AMDCycle:
    """Classify today's Power-of-Three phase from the Asian range and later action.

    This deliberately uses only candles timestamped inside the UTC Asian range for
    accumulation, so London/NY expansion cannot rewrite the accumulation bounds.
    """
    now = current_time if current_time.tzinfo else current_time.replace(tzinfo=None)
    candles = df.copy()
    if not isinstance(candles.index, pd.DatetimeIndex):
        if "time" in candles.columns:
            candles.index = pd.to_datetime(candles["time"], utc=True, errors="coerce")
        elif "timestamp" in candles.columns:
            candles.index = pd.to_datetime(candles["timestamp"], utc=True, errors="coerce")
    if not isinstance(candles.index, pd.DatetimeIndex):
        return AMDCycle(now, 0, 0, 0, 0, MarketPhase.UNKNOWN, False)
    if candles.index.tz is None:
        candles.index = candles.index.tz_localize("UTC")
    else:
        candles.index = candles.index.tz_convert("UTC")
    now_utc = current_time.astimezone(timezone.utc) if current_time.tzinfo else current_time.replace(tzinfo=timezone.utc)
    day = candles[candles.index.date == now_utc.date()]
    if day.empty:
        return AMDCycle(now_utc, 0, 0, 0, 0, MarketPhase.UNKNOWN, False)
    asian = day[(day.index.hour >= 0) & (day.index.hour < 7)]
    if asian.empty:
        fallback = day.head(min(20, len(day)))
        asian = fallback
    accumulation_low = float(asian["low"].min())
    accumulation_high = float(asian["high"].max())
    current_price = float(day["close"].iloc[-1])
    post_asian = day[day.index.hour >= 7]
    manipulation_low = float(post_asian["low"].min()) if not post_asian.empty else accumulation_low
    manipulation_high = float(post_asian["high"].max()) if not post_asian.empty else accumulation_high
    raided_low = not post_asian.empty and float(post_asian["low"].min()) < accumulation_low
    raided_high = not post_asian.empty and float(post_asian["high"].max()) > accumulation_high
    hour = now_utc.hour
    if hour < 7:
        phase = MarketPhase.ACCUMULATION
    elif hour < 10 or 13 <= hour < 16:
        phase = MarketPhase.MANIPULATION if (raided_low or raided_high) else MarketPhase.MANIPULATION
    else:
        phase = MarketPhase.DISTRIBUTION if (raided_low or raided_high) else MarketPhase.UNKNOWN
    # Distribution becomes actionable only once price closes beyond the Asian
    # range after a raid. This is the non-ML approximation of AMD completion.
    distribution = (raided_low and current_price > accumulation_high) or (raided_high and current_price < accumulation_low)
    complete = bool(raided_low or raided_high) and distribution and hour >= 10
    if complete:
        phase = MarketPhase.DISTRIBUTION
    return AMDCycle(now_utc, accumulation_low, accumulation_high, manipulation_low, manipulation_high, phase, complete)


def get_current_session(current_time: datetime) -> Optional[SessionWindow]:
    """Returns the current active trading session"""
    current_t = current_time.time()
    
    for session in ICT_SESSIONS:
        if session.start <= current_t < session.end:
            return session
            
    return None

def is_kill_zone(current_time: datetime | None = None) -> bool:
    """Return True only during configured prime London/NY ICT windows (UTC)."""
    now = current_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    return get_current_session(now) is not None and get_current_session(now).is_prime

def is_prime_time(current_time: datetime) -> bool:
    """Check if current time is within a 'Kill Zone' (Prime ICT time)"""
    session = get_current_session(current_time)
    return session.is_prime if session else False

def analyze_premium_discount(df: pd.DataFrame, lookback: int = 50) -> Dict[str, any]:
    """
    Analyze current price relative to Premium/Discount zones
    Buy in Discount (< 50%), Sell in Premium (> 50%)
    """
    if len(df) < lookback:
        return {"status": "insufficient_data"}
        
    recent = df.tail(lookback)
    high = recent['high'].max()
    low = recent['low'].min()
    current = df['close'].iloc[-1]
    
    equilibrium = (high + low) / 2
    range_size = high - low
    
    if range_size == 0:
        return {"status": "flat_market"}
        
    position = (current - low) / range_size
    
    zone = "equilibrium"
    if position < 0.5:
        zone = "discount"  # Potential Buy Area
    elif position > 0.5:
        zone = "premium"   # Potential Sell Area
        
    return {
        "high": high,
        "low": low,
        "equilibrium": equilibrium,
        "current_price": current,
        "zone": zone,
        "percentage_from_low": position * 100
    }

def get_kill_zone_status(current_time: datetime) -> Tuple[str, str]:
    """
    Determine if current time is within institutional Kill Zones
    Returns: (status, zone_name)
    Status: 'ACTIVE' or 'INACTIVE'
    """
    session = get_current_session(current_time)
    
    if session and session.is_prime:
        return "ACTIVE", session.name
        
    return "INACTIVE", "Off-Hours"

def validate_strict_choch(
    current_price: float,
    last_swing_high: float,
    last_swing_low: float,
    liquidity_swept: bool,
    htf_trend: str
) -> bool:
    """
    Validate Change of Character with strict rules:
    1. Must have liquidity sweep first
    2. Must break structure in opposite direction
    3. Must align with HTF trend
    """
    if not liquidity_swept:
        return False  # No sweep, no valid CHOCH
    
    # Bullish CHOCH: Swept lows, then broke high
    if htf_trend == "BULLISH":
        if current_price > last_swing_high:
            return True
            
    # Bearish CHOCH: Swept highs, then broke low
    elif htf_trend == "BEARISH":
        if current_price < last_swing_low:
            return True
            
    # Reversal scenario (counter-trend) requires stronger confirmation
    # For safety, we only allow CHOCH that aligns with HTF
    return False

def check_ote_entry(current_price: float, swing_high: float, swing_low: float, is_bullish: bool) -> Tuple[float, bool]:
    """
    Quick check if price is in OTE Golden Zone (0.618 - 0.786)
    Returns: (fib_level, is_in_golden_zone)
    """
    if swing_high == swing_low:
        return 0.0, False
    
    range_size = swing_high - swing_low
    
    if is_bullish:
        # Bullish OTE: Retracement from Low to High
        fib_level = (swing_high - current_price) / range_size
    else:
        # Bearish OTE: Retracement from High to Low
        fib_level = (current_price - swing_low) / range_size
    
    # Golden Zone: 0.618 to 0.786
    in_golden_zone = 0.618 <= fib_level <= 0.786
    return fib_level, in_golden_zone
