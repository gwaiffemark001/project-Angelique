def find_swing_points(candles: list, lookback: int = 5) -> dict:
    """Identifies Swing Highs and Swing Lows for Market Structure."""
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    
    swing_highs = []
    swing_lows = []
    
    for i in range(lookback, len(candles) - lookback):
        if highs[i] == max(highs[i-lookback:i+lookback+1]):
            swing_highs.append({"price": highs[i], "time": candles[i]["time"]})
        if lows[i] == min(lows[i-lookback:i+lookback+1]):
            swing_lows.append({"price": lows[i], "time": candles[i]["time"]})
            
    return {"swing_highs": swing_highs[-3:], "swing_lows": swing_lows[-3:]}
