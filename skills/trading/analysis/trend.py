import pandas as pd
from core import config

def determine_trend(candles: list, df: pd.DataFrame, fast_ema: int | None = None, slow_ema: int | None = None) -> str:
    """Determines trend using Market Structure and EMAs."""
    fast_ema = fast_ema or config.TRADING_EMA_FAST
    slow_ema = slow_ema or config.TRADING_EMA_SLOW
    lookback = max(fast_ema, slow_ema)
    if len(candles) < lookback:
        return "Sideways"

    last_close = candles[-1]["close"]
    ema_fast = df.iloc[-1].get(f"EMA_{fast_ema}", 0)
    ema_slow = df.iloc[-1].get(f"EMA_{slow_ema}", 0)

    if last_close > ema_fast > ema_slow:
        return "Bullish"
    elif last_close < ema_fast < ema_slow:
        return "Bearish"
    return "Sideways"
