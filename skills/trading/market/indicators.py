import pandas as pd
from core import config

def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates all necessary indicators using pandas_ta."""
    try:
        import pandas_ta as ta
        df.ta.ema(length=config.TRADING_EMA_FAST, append=True)
        df.ta.ema(length=config.TRADING_EMA_SLOW, append=True)
        df.ta.rsi(length=config.TRADING_RSI_PERIOD, append=True)
        df.ta.macd(append=True)
        df.ta.atr(length=config.TRADING_ATR_PERIOD, append=True)
        df.ta.bbands(length=config.TRADING_BBANDS_PERIOD, append=True)
        return df
    except Exception as e:
        print(f"⚠️ Indicator calculation failed: {e}")
        return df
