import pandas as pd
import json
import os
import time
from datetime import datetime
from core import config
from skills.trading.engine.account import get_account_summary
from skills.trading.market.market_data import market
from skills.trading.analysis.trend import determine_trend
from skills.trading.risk.trade_validator import validate_trade
from skills.trading.risk.lot_size import calculate_lot_size
from skills.trading.execution.trade_execution import execute_market_order
from skills.trading.ai.trade_reasoner import generate_trade_brief
from skills.trading.learning.journal import log_trade
from skills.trading.news import get_forex_news, get_market_calendar
from skills.trading.analysis.probability import calculate_confidence_score


def _get_news_context(symbol=None):
    news = get_forex_news(symbol)
    calendar = get_market_calendar()
    return {
        "news": news,
        "calendar": calendar,
        "has_high_impact": any(
            e.get("impact", "").lower() == "high" for e in calendar
        ),
        "news_count": len(news),
        "calendar_count": len(calendar),
    }


def _get_session_filter():
    now = datetime.utcnow()
    hour = now.hour
    if 8 <= hour < 12:
        return "EU"
    elif 13 <= hour < 17:
        return "US"
    elif 17 <= hour < 21:
        return "US/London Overlap"
    else:
        return "ASIA"


def analyze_and_recommend(symbol: str, timeframe: str = config.DEFAULT_TRADING_TIMEFRAME, risk_percent: float | None = None, auto_execute: bool = False, account_mode: str = "demo"):
    risk_percent = risk_percent if risk_percent is not None else config.TRADING_DEFAULT_RISK_PERCENT

    account = get_account_summary(account_mode=account_mode)
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

    news_context = _get_news_context(symbol)

    analysis = {
        "symbol": symbol,
        "direction": direction,
        "current_price": current_price,
        "trend": trend,
        "at_key_level": bool(indicators.get("bb_upper") and indicators.get("bb_lower")),
        "confirmation_candle": True,
        "high_impact_news": news_context.get("has_high_impact", False),
        "news_count": news_context.get("news_count", 0),
        "calendar_count": news_context.get("calendar_count", 0),
        "spread_pips": round(max(0.0, indicators.get("atr", 0) * 0.1), 2),
        "rr_ratio": tp_pips / sl_pips if sl_pips else 0,
        "sl_pips": round(sl_pips, 2),
        "tp_pips": round(tp_pips, 2),
        "sl_price": round(sl_price, 6),
        "tp_price": round(tp_price, 6),
        "risk_percent": risk_percent,
        "session": _get_session_filter(),
        "reasoning_text": (
            f"Trend is {trend}. ATR-based stop loss set to {round(sl_pips, 2)} pips and "
            f"take profit at {round(tp_pips, 2)} pips for a dynamic R/R of {round(tp_pips / sl_pips, 2)}. "
            f"Session: {_get_session_filter()}. "
            f"News articles found: {news_context.get('news_count', 0)}. "
            f"Calendar events: {news_context.get('calendar_count', 0)}. "
            f"High-impact news: {'Yes' if news_context.get('has_high_impact') else 'No - safe to trade'}"
        )
    }

    rules = {
        "max_spread": config.TRADING_MAX_SPREAD,
        "high_impact_news": news_context.get("has_high_impact", False),
    }
    validation = validate_trade(analysis, account, rules)

    lot_size = calculate_lot_size(
        account.get("balance", 0),
        risk_percent,
        analysis.get("sl_pips", 25),
        config.TRADING_PIP_VALUE,
    )

    if auto_execute and validation["approved"]:
        result = execute_approved_trade(symbol, direction, lot_size, sl_price, tp_price, account_mode=account_mode)
        return f"🚀 AUTO-EXECUTED: {result}\n\n📊 Analysis:\n{generate_trade_brief(analysis, validation, lot_size)}"

    brief = generate_trade_brief(analysis, validation, lot_size)

    if not validation["approved"] and auto_execute:
        return f"🚫 AUTO-TRADE BLOCKED: Trade does not pass all 10 Constitutional Rules.\n\n📊 Analysis:\n{brief}"

    if auto_execute:
        return f"🚀 Auto-execute triggered.\n\n{brief}"

    return brief


def execute_approved_trade(symbol: str, order_type: str, lot_size: float, sl: float, tp: float, account_mode: str = "demo") -> str:
    result = execute_market_order(symbol, order_type, lot_size, sl, tp, account_mode=account_mode)
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
    log_trade({
        "symbol": symbol,
        "type": order_type,
        "lots": lot_size,
        "sl": sl,
        "tp": tp,
        "result": "FAILURE",
    })
    return result


def get_trading_guidance(symbol: str = config.DEFAULT_TRADING_SYMBOL, timeframe: str = config.DEFAULT_TRADING_TIMEFRAME) -> str:
    account = get_account_summary()
    if "error" in account:
        return f"Account Error: {account['error']}"

    balance = account.get("balance", 0)
    equity = account.get("equity", 0)
    free_margin = account.get("free_margin", 0)

    guidance_lines = [
        f"📊 **Trading Guidance for {symbol} ({timeframe})**",
        f"",
        f"💰 Account: Balance ${balance:,.2f} | Equity ${equity:,.2f} | Free Margin ${free_margin:,.2f}",
        f"",
        f"🎯 **Core Rules (10-Rule Constitution):**",
        f"  1. Never risk more than {config.TRADING_DEFAULT_RISK_PERCENT}% of your account per trade",
        f"  2. Always use a stop loss (minimum 5 pips, recommended ATR × 1.5)",
        f"  3. Minimum R:R ratio of {config.TRADING_MIN_RR_RATIO}:1 — never trade below this",
        f"  4. Check the economic calendar — avoid trading during high-impact news",
        f"  5. Trade during optimal sessions: EU (08:00-12:00 UTC) and US (13:00-17:00 UTC)",
        f"  6. Wait for indicator confluence (at least 2 indicators aligned)",
        f"  7. Check spread — never trade if spread > {config.TRADING_MAX_SPREAD} pips",
        f"  8. Start with small lot sizes and scale up as you build a track record",
        f"  9. Keep a trading journal — review your wins and losses weekly",
        f" 10. Never revenge-trade — if you hit a loss, take a break",
        f"",
        f"📰 **News Impact:**",
    ]

    news = get_forex_news(symbol)
    if news:
        for item in news[:3]:
            guidance_lines.append(f"  📰 {item.get('title', 'Untitled')}: {item.get('body', '')[:100]}")
    else:
        guidance_lines.append(f"  No major news events currently affecting {symbol}.")

    calendar = get_market_calendar()
    guidance_lines.extend([
        f"",
        f"📅 **Upcoming Calendar Events:**",
    ])
    for event in calendar[:3]:
        guidance_lines.append(f"  🕐 {event.get('time', '?')} - {event.get('event', '?')} [{event.get('impact', '?')}]")

    guidance_lines.extend([
        f"",
        f"💡 **Manual Trading Tips:**",
        f"  • Always set SL and TP BEFORE entering a trade",
        f"  • Use limit orders for entries, not market orders when possible",
        f"  • Scale in gradually — don't go all-in on one trade",
        f"  • Maximum 3-5 open trades at any time",
        f"  • Review Your trades daily and learn from mistakes",
        f"  • Use a demo account to test new strategies first",
        f"  • Keep emotions out — follow your rules mechanically",
        f"",
    ])

    return "\n".join(guidance_lines)


def get_chart_interaction_guide(symbol: str = config.DEFAULT_TRADING_SYMBOL) -> str:
    """Return a short guided routine explaining chart interactions for teaching mode.

    This text can be presented by Angelique to the user when in teaching mode to
    explain how to use tooltips, drag-to-select, zoom controls, and the symbol dropdown.
    """
    lines = [
        f"🎓 Interactive Chart Guide for {symbol}:",
        "",
        "1) Hover over any candle to see detailed OHLC and tick volume information.",
        "2) Use the 'Zoom In' and 'Zoom Out' buttons to change the visible candle range.",
        "3) Click and drag on the chart to select a specific range, then release to zoom into that selection.",
        "4) Use the resize handles (small squares) on the selection to expand or contract the selection before releasing.",
        "5) Use the symbol dropdown when creating demo patterns to choose instruments from the connected bridge.",
        "",
        "Try these now: hover a candle, then drag a mid-range selection — Angelique will narrate and explain what you selected.",
    ]
    return "\n".join(lines)


def auto_trade_scan(symbols=None, timeframe=config.DEFAULT_TRADING_TIMEFRAME, risk_percent=None):
    symbols = symbols or config.TRADING_SYMBOLS
    risk_percent = risk_percent or config.TRADING_DEFAULT_RISK_PERCENT

    results = []
    for symbol in symbols:
        try:
            analysis = analyze_and_recommend(symbol, timeframe, risk_percent)
            results.append({"symbol": symbol, "analysis": analysis})
        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)})

    approved_trades = [r for r in results if "TRADE APPROVED" in r.get("analysis", "")]
    rejected_trades = [r for r in results if "TRADE REJECTED" in r.get("analysis", "")]

    summary = f"🔍 Auto-Trade Scan Complete ({len(symbols)} symbols)\n"
    summary += f"✅ Approved: {len(approved_trades)} | ❌ Rejected: {len(rejected_trades)}\n\n"
    for r in results:
        symbol = r.get("symbol", "Unknown")
        analysis = r.get("analysis", r.get("error", "No result"))
        summary += f"─── {symbol} ───\n{analysis}\n\n"

    return summary