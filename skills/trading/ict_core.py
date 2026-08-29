"""
ICT Core Concepts Module
Implements: Power of Three (AMD), Session Timing, Optimal Trade Entry (OTE)
"""
import pandas as pd
import numpy as np
from datetime import datetime, time
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

def identify_ote_zone(df: pd.DataFrame, lookback: int = 20) -> Optional[Dict[str, float]]:
    """
    Identify Optimal Trade Entry zone based on recent swing high/low
    Focuses on the 0.618 - 0.786 Fibonacci region
    """
    if len(df) < lookback:
        return None
        
    recent_data = df.tail(lookback)
    
    # Simple swing detection
    swing_high = recent_data['high'].max()
    swing_low = recent_data['low'].min()
    
    if swing_high == swing_low:
        return None
        
    fib_levels = calculate_fib_retracements(swing_high, swing_low)
    
    # Determine trend direction to know which retracement to use
    current_price = df['close'].iloc[-1]
    mid_point = fib_levels["0.500"]
    
    zone = {
        "swing_high": swing_high,
        "swing_low": swing_low,
        "ote_lower": fib_levels["0.618"],
        "ote_upper": fib_levels["0.786"],
        "sweet_spot": fib_levels["0.705"],
        "is_discount": current_price < mid_point,  # Buy zone
        "is_premium": current_price > mid_point    # Sell zone
    }
    
    return zone

def detect_amd_phase(df: pd.DataFrame, current_time: datetime) -> AMDCycle:
    """
    Detect the current Power of Three phase based on price action and time
    Logic:
    1. Accumulation: Range bound during Asian session
    2. Manipulation: False break (Judas Swing) during London/NY open
    3. Distribution: Real move in opposite direction
    """
    # Default unknown cycle
    cycle = AMDCycle(
        start_time=current_time,
        accumulation_low=df['low'].iloc[-1],
        accumulation_high=df['high'].iloc[-1],
        manipulation_low=df['low'].iloc[-1],
        manipulation_high=df['high'].iloc[-1],
        current_phase=MarketPhase.UNKNOWN,
        is_complete=False
    )
    
    # Find today's range so far
    today_data = df[df.index.date == current_time.date()]
    if len(today_data) == 0:
        return cycle
        
    day_open = today_data['open'].iloc[0]
    day_high = today_data['high'].max()
    day_low = today_data['low'].min()
    current_price = df['close'].iloc[-1]
    
    # Determine Phase based on Time and Price Action
    current_hour = current_time.hour
    
    # 1. Accumulation (Asian Session usually)
    if 0 <= current_hour < 7:
        cycle.current_phase = MarketPhase.ACCUMULATION
        cycle.accumulation_low = day_low
        cycle.accumulation_high = day_high
        
    # 2. Manipulation (London Open 7-10 UTC or NY Open 13-16 UTC)
    elif (7 <= current_hour < 10) or (13 <= current_hour < 16):
        cycle.current_phase = MarketPhase.MANIPULATION
        # Check for Judas Swing (False break of Asian range)
        asian_high = cycle.accumulation_high
        asian_low = cycle.accumulation_low
        
        if current_price > asian_high and day_low < asian_low:
            # Possible manipulation high formed
            cycle.manipulation_high = day_high
        elif current_price < asian_low and day_high > asian_high:
            # Possible manipulation low formed
            cycle.manipulation_low = day_low
            
    # 3. Distribution (The real move)
    else:
        cycle.current_phase = MarketPhase.DISTRIBUTION
        # If price moved significantly away from manipulation zone
        if current_hour >= 10 and current_hour < 13:
             # Post-London distribution
             cycle.is_complete = (day_high - day_low) > (cycle.accumulation_high - cycle.accumulation_low) * 1.5
    
    return cycle

def get_current_session(current_time: datetime) -> Optional[SessionWindow]:
    """Returns the current active trading session"""
    current_t = current_time.time()
    
    for session in ICT_SESSIONS:
        if session.start <= current_t <= session.end:
            return session
            
    return None

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
