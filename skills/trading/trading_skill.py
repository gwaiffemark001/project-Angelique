import pandas as pd
from core import config
from skills.trading.engine.account import get_account_summary
from skills.trading.market.market_data import market
from skills.trading.analysis.trend import determine_trend
from skills.trading.risk.trade_validator import validate_trade
from skills.trading.risk.lot_size import calculate_lot_size
from skills.trading.execution.trade_execution import execute_market_order
from skills.trading.ai.trade_reasoner import generate_trade_brief
from skills.trading.learning.journal import log_trade


def analyze_and_recommend(symbol: str, timeframe: str = "H1", risk_percent: float | None = None) -> str:
    """
    The main entry point for Angelique's trading skill.
    Fetches data, analyzes it against the 10 Rules, and returns a recommendation.
    """
    risk_percent = risk_percent if risk_percent is not None else config.TRADING_DEFAULT_RISK_PERCENT

    account = get_account_summary()
    if "error" in account:
        return f"Account Error: {account['error']}"

    market_data = market.get_candles_and_indicators(symbol, timeframe)
    if "error" in market_data:
        return f"Market Error: {market_data['error']}"

    candles = market_data.get("candles", [])
    if not candles:
        return "Market Error: No candles available for analysis."

    latest = market_data.get("latest_candle", candles[-1])
    indicators = market_data.get("indicators", {})
    trend = determine_trend(candles, pd.DataFrame(candles))
    atr = max(indicators.get("atr", 0), 0)
    sl_pips = max(5.0, atr * 1.5) if atr else 25.0
    tp_pips = sl_pips * max(config.TRADING_MIN_RR_RATIO, 2.0)
    direction = "BUY" if trend == "Bullish" else "SELL" if trend == "Bearish" else "HOLD"

    current_price = latest.get("close", 0)
    sl_price = current_price - (sl_pips * 0.0001) if direction == "BUY" else current_price + (sl_pips * 0.0001)
    tp_price = current_price + (tp_pips * 0.0001) if direction == "BUY" else current_price - (tp_pips * 0.0001)

    analysis = {
        "symbol": symbol,
        "direction": direction,
        "current_price": current_price,
        "trend": trend,
        "at_key_level": bool(indicators.get("bb_upper") and indicators.get("bb_lower")),
        "confirmation_candle": True,
        "high_impact_news": False,
        "spread_pips": round(max(0.0, indicators.get("atr", 0) * 0.1), 2),
        "rr_ratio": tp_pips / sl_pips if sl_pips else 0,
        "sl_pips": round(sl_pips, 2),
        "tp_pips": round(tp_pips, 2),
        "sl_price": round(sl_price, 6),
        "tp_price": round(tp_price, 6),
        "risk_percent": risk_percent,
        "reasoning_text": (
            f"Trend is {trend}. ATR-based stop loss set to {round(sl_pips,2)} pips and "
            f"take profit at {round(tp_pips,2)} pips for a dynamic R/R of {round(tp_pips/sl_pips,2)}."
        )
    }

    rules = {"max_spread": config.TRADING_MAX_SPREAD}
    validation = validate_trade(analysis, account, rules)

    lot_size = calculate_lot_size(
        account.get("balance", 0),
        risk_percent,
        analysis.get("sl_pips", 25),
        config.TRADING_PIP_VALUE,
    )

    return generate_trade_brief(analysis, validation, lot_size)

def execute_approved_trade(symbol: str, order_type: str, lot_size: float, sl: float, tp: float) -> str:
    """Executes a trade after user confirmation."""
    result = execute_market_order(symbol, order_type, lot_size, sl, tp)
    if "✅" in result:
        log_trade({
            "symbol": symbol,
            "type": order_type,
            "lots": lot_size,
            "sl": sl,
            "tp": tp,
            "result": "SUCCESS",
        })
    return result
