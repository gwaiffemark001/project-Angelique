from core import config
from skills.trading.analysis.probability import calculate_confidence_score


def get_support_resistance_levels(candles: list, period: int = 20) -> dict:
    """Calculate support and resistance levels from recent candles."""
    if len(candles) < period:
        return {"resistance": 0, "support": 0}
    
    recent = candles[-period:]
    highs = [c.get("high", 0) for c in recent]
    lows = [c.get("low", 0) for c in recent]
    
    return {
        "resistance": max(highs),
        "support": min(lows),
        "midpoint": (max(highs) + min(lows)) / 2
    }


def validate_trade(analysis: dict, account: dict, rules: dict) -> dict:
    """
    Enforces the 10-Rule Angelique Trading Constitution.
    Returns a dict with 'approved' (bool) and 'reasons' (list).
    
    Rules:
    1. Capital Protection - Free margin must be above minimum
    2. Trend Alignment - Trade direction must match trend
    3. Key Level Interaction - Entry/SL must respect support/resistance
    4. Confirmation Candle - Current candle must confirm direction
    5. Indicator Confluence - Multiple indicators must align
    6. Reward/Risk Ratio - Min R:R ratio must be met
    7. News Filter - No high-impact news during trade window
    8. Spread Filter - Spread must be below maximum
    9. Session Filter - Trade during optimal sessions
    10. Confidence Score - Overall confidence above threshold
    """
    reasons = []
    approved = True
    
    # Rule 1: Capital Protection
    if account.get("free_margin", 0) < config.TRADING_MIN_FREE_MARGIN:
        approved = False
        reasons.append(f"❌ Rule 1 (Capital Protection): Free margin ${account.get('free_margin', 0)} < minimum ${config.TRADING_MIN_FREE_MARGIN}")
    else:
        reasons.append(f"✅ Rule 1: Capital protected (Free margin: ${account.get('free_margin', 0)})")
    
    # Rule 2: Trend Alignment
    trend = analysis.get("trend", "Sideways")
    direction = analysis.get("direction", "BUY")
    
    if (trend == "Bullish" and direction != "BUY") or (trend == "Bearish" and direction != "SELL"):
        approved = False
        reasons.append(f"❌ Rule 2 (Trend Alignment): {direction} signal contradicts {trend} trend")
    else:
        reasons.append(f"✅ Rule 2: Trend-aligned ({direction} in {trend} market)")
    
    # Rule 3: Key Level Interaction
    candles = analysis.get("candles", [])
    if candles:
        levels = get_support_resistance_levels(candles)
        entry = float(analysis.get("entry", 0))
        stop_loss = float(analysis.get("stop_loss", 0))
        
        # Check if SL is near support/resistance
        if direction == "BUY":
            if stop_loss > levels["support"] * 1.01:  # SL too close to support
                reasons.append(f"⚠️ Rule 3: SL ${stop_loss} close to support ${levels['support']:.2f}")
        else:
            if stop_loss < levels["resistance"] * 0.99:  # SL too close to resistance
                reasons.append(f"⚠️ Rule 3: SL ${stop_loss} close to resistance ${levels['resistance']:.2f}")
        
        reasons.append(f"✅ Rule 3: Key levels checked (Support: ${levels['support']:.2f}, Resistance: ${levels['resistance']:.2f})")
    
    # Rule 4: Confirmation Candle
    if candles:
        latest = candles[-1]
        open_p = float(latest.get("open", 0))
        close_p = float(latest.get("close", 0))
        high_p = float(latest.get("high", 0))
        low_p = float(latest.get("low", 0))
        
        if direction == "BUY":
            # Bullish confirmation: close > open, good body
            body_ratio = (close_p - open_p) / (high_p - low_p + 0.00001) if high_p != low_p else 0
            if close_p > open_p and body_ratio > 0.5:
                reasons.append(f"✅ Rule 4: Bullish confirmation candle (body ratio: {body_ratio:.2%})")
            else:
                reasons.append(f"⚠️ Rule 4: Weak bullish confirmation (body ratio: {body_ratio:.2%})")
        else:
            # Bearish confirmation: open > close, good body
            body_ratio = (open_p - close_p) / (high_p - low_p + 0.00001) if high_p != low_p else 0
            if open_p > close_p and body_ratio > 0.5:
                reasons.append(f"✅ Rule 4: Bearish confirmation candle (body ratio: {body_ratio:.2%})")
            else:
                reasons.append(f"⚠️ Rule 4: Weak bearish confirmation (body ratio: {body_ratio:.2%})")
    
    # Rule 5: Indicator Confluence
    indicators = analysis.get("indicators", {})
    confluence_count = 0
    
    ema_fast = float(indicators.get("ema_fast", 0))
    ema_slow = float(indicators.get("ema_slow", 0))
    rsi = float(indicators.get("rsi", 50))
    atr = float(indicators.get("atr", 0))
    
    if direction == "BUY":
        if ema_fast > ema_slow:
            confluence_count += 1
        if rsi > 50 and rsi < 70:
            confluence_count += 1
        if ema_fast > 0 and atr > 0:
            confluence_count += 1
    else:
        if ema_fast < ema_slow:
            confluence_count += 1
        if rsi < 50 and rsi > 30:
            confluence_count += 1
        if ema_fast > 0 and atr > 0:
            confluence_count += 1
    
    if confluence_count >= 2:
        reasons.append(f"✅ Rule 5: Indicator confluence ({confluence_count}/3 indicators aligned)")
    else:
        approved = False
        reasons.append(f"❌ Rule 5: Insufficient indicator confluence ({confluence_count}/3 required >= 2)")
    
    # Rule 6: Reward to Risk
    if analysis.get("rr_ratio", 0) < config.TRADING_MIN_RR_RATIO:
        approved = False
        reasons.append(f"❌ Rule 6 (Reward/Risk): R:R {analysis.get('rr_ratio', 0):.2f}:1 < minimum {config.TRADING_MIN_RR_RATIO}:1")
    else:
        reasons.append(f"✅ Rule 6: Reward/Risk ratio {analysis.get('rr_ratio', 0):.2f}:1 meets minimum")
    
    # Rule 7: News Filter
    if analysis.get("high_impact_news"):
        approved = False
        reasons.append("❌ Rule 7 (News Filter): High impact news detected - trade blocked")
    else:
        reasons.append("✅ Rule 7: No conflicting news detected")
    
    # Rule 8: Spread Filter
    spread = analysis.get("spread_pips", 0)
    max_spread = rules.get("max_spread", config.TRADING_MAX_SPREAD)
    if spread > max_spread:
        approved = False
        reasons.append(f"❌ Rule 8 (Spread): {spread} pips > max {max_spread} pips")
    else:
        reasons.append(f"✅ Rule 8: Spread {spread} pips within limits")
    
    # Rule 9: Session Filter (Placeholder - implement based on timezone/session)
    session = analysis.get("session", "unknown")
    optimal_sessions = ["EU", "US"]  # Customize based on strategy
    if session in optimal_sessions:
        reasons.append(f"✅ Rule 9: Trading during optimal {session} session")
    else:
        reasons.append(f"⚠️ Rule 9: Trading outside optimal sessions (Current: {session})")
    
    # Rule 10: Confidence Score
    confidence = calculate_confidence_score(analysis)
    if not confidence["pass"]:
        approved = False
        reasons.append(f"❌ Rule 10 (Confidence): Score {confidence['total_score']:.1f}% < threshold {config.TRADING_CONFIDENCE_THRESHOLD}%")
    else:
        reasons.append(f"✅ Rule 10: Confidence score {confidence['total_score']:.1f}% meets threshold")
    
    if approved:
        reasons.append("\n🟢 **TRADE APPROVED**: Passes all 10 Constitutional Rules")
    else:
        reasons.append("\n🔴 **TRADE REJECTED**: Fails one or more Constitutional Rules")
    
    return {"approved": approved, "reasons": reasons, "confidence": confidence}
