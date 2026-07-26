from core import config

def calculate_confidence_score(analysis: dict) -> dict:
    """
    Calculates the trade confidence score based on the Angelique Trading Constitution.
    Weights: Trend 25%, S/R 20%, Price Action 20%, EMA 10%, RSI 10%, Volume 5%, News 10%
    """
    score = 0
    breakdown = {}
    
    # 1. Trend Alignment (25%)
    if analysis.get("trend") in ["Bullish", "Bearish"]:
        score += 25
        breakdown["Trend"] = 25
    else:
        breakdown["Trend"] = 0
        
    # 2. Support/Resistance Interaction (20%)
    if analysis.get("at_key_level"):
        score += 20
        breakdown["S/R"] = 20
    else:
        breakdown["S/R"] = 0
        
    # 3. Price Action Confirmation (20%)
    if analysis.get("confirmation_candle"):
        score += 20
        breakdown["Price Action"] = 20
    else:
        breakdown["Price Action"] = 0
        
    # 4. EMA Alignment (10%)
    if analysis.get("ema_aligned"):
        score += 10
        breakdown["EMA"] = 10
    else:
        breakdown["EMA"] = 0
        
    # 5. RSI Condition (10%)
    rsi = analysis.get("rsi", 50)
    if config.TRADING_RSI_MIN < rsi < config.TRADING_RSI_MAX:
        score += 10
        breakdown["RSI"] = 10
    else:
        breakdown["RSI"] = 0
        
    # 6. Volume (5%)
    if analysis.get("volume_high"):
        score += 5
        breakdown["Volume"] = 5
    else:
        breakdown["Volume"] = 0
        
    # 7. News Filter (10%)
    if not analysis.get("high_impact_news"):
        score += 10
        breakdown["News"] = 10
    else:
        breakdown["News"] = 0
        
    return {"total_score": score, "breakdown": breakdown, "pass": score >= config.TRADING_CONFIDENCE_THRESHOLD}
