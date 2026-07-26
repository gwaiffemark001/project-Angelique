# skills/trading/market/candles.py
import pandas as pd

def build_candle_objects(raw_candles: list) -> list:
    structured_candles = []
    for c in raw_candles:
        body_size = abs(c["close"] - c["open"])
        structured_candles.append({
            "time": c["time"],
            "open": c["open"],
            "high": c["high"],
            "low": c["low"],
            "close": c["close"],
            "volume": c["tick_volume"],
            "body_size": round(body_size, 5)
        })
    return structured_candles

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    try:
        import pandas_ta as ta
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)
        df.ta.rsi(length=14, append=True)
        return df
    except:
        return df
