from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .news import get_forex_news, get_market_calendar

HIGH_IMPACT_WORDS = {
    "interest rate", "rate decision", "central bank", "fomc", "fed ",
    "ecb", "boe", "boj", "employment", "nonfarm", "nfp", "cpi",
    "inflation", "gdp", "pmi", "retail sales", "payroll", "powell",
    "president", "election", "war", "sanctions", "emergency",
}
BULLISH_WORDS = {"hawkish", "raises rates", "strong growth", "beats expectations", "surges", "rises", "gains"}
BEARISH_WORDS = {"dovish", "cuts rates", "weak growth", "misses expectations", "falls", "drops", "losses"}


def _currencies(symbol: str) -> set[str]:
    letters = "".join(char for char in str(symbol).upper() if char.isalpha())
    if len(letters) >= 6:
        return {letters[:3], letters[3:6]}
    if "XAU" in letters:
        return {"XAU", "USD"}
    return set()


def _text(item: dict[str, Any]) -> str:
    return f"{item.get('title', '')} {item.get('body', '')} {item.get('event', '')}".strip()


def assess_news(symbol: str, direction: str) -> dict[str, Any]:
    """Assess news as a risk/confirmation input; never use it as a trade signal alone."""
    try:
        headlines = get_forex_news(symbol)
        calendar = get_market_calendar(symbol=symbol)
    except Exception as exc:
        return {
            "status": "unavailable",
            "score_adjustment": 0,
            "high_impact": False,
            "directional_conflict": False,
            "reason": f"News unavailable; no score adjustment applied: {exc}",
            "headlines": [],
            "calendar": [],
        }

    currencies = _currencies(symbol)
    relevant_headlines = []
    high_impact_events = []
    imminent_events = []
    bullish = 0
    bearish = 0
    for item in headlines or []:
        text = _text(item)
        upper = text.upper()
        relevant = not currencies or any(currency in upper for currency in currencies)
        if relevant and text.lower() != "news unavailable":
            relevant_headlines.append(item)
            bullish += sum(word in text.lower() for word in BULLISH_WORDS)
            bearish += sum(word in text.lower() for word in BEARISH_WORDS)
    for item in calendar or []:
        text = _text(item)
        if str(item.get("impact", "")).lower() in {"high", "red", "3"} or any(word in text.lower() for word in HIGH_IMPACT_WORDS):
            high_impact_events.append(item)
            scheduled_at = item.get("scheduled_at")
            if scheduled_at:
                try:
                    event_time = datetime.fromisoformat(str(scheduled_at).replace("Z", "+00:00"))
                    minutes = (event_time - datetime.now(timezone.utc)).total_seconds() / 60
                    if -30 <= minutes <= 120:
                        imminent_events.append(item)
                except (TypeError, ValueError):
                    pass

    news_bias = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"
    expected = "bullish" if direction == "BUY" else "bearish"
    conflict = news_bias in {"bullish", "bearish"} and news_bias != expected
    # News is an execution-routing input, not a technical-plan blocker.
    # Directional headlines remain visible as context and high-impact events
    # route a completed plan to manual approval, but neither one downgrades
    # the strategy confluence score or invalidates an otherwise complete plan.
    adjustment = 0

    reasons = []
    if imminent_events:
        reasons.append(f"High-impact calendar event is imminent ({len(imminent_events)} event(s)); avoid entry near release.")
    elif high_impact_events:
        reasons.append(f"High-impact calendar event detected ({len(high_impact_events)} event(s)); timing was not available.")
    if conflict:
        reasons.append(f"News bias is {news_bias}, conflicting with the {direction} SMC direction.")
    elif news_bias != "neutral":
        reasons.append(f"News bias is {news_bias} and does not conflict with the {direction} SMC direction.")
    if not relevant_headlines:
        reasons.append("No reliable symbol-specific headline confirmation was found.")
    return {
        "status": "ready" if relevant_headlines or high_impact_events else "unavailable",
        "score_adjustment": adjustment,
        "high_impact": bool(high_impact_events),
        "high_impact_imminent": bool(imminent_events),
        "data_quality": {
            "headlines": "available" if relevant_headlines else "unavailable",
            "calendar": "available" if calendar and not all(item.get("freshness") == "unavailable" for item in calendar) else "unavailable",
        },
        "directional_conflict": conflict,
        "bias": news_bias,
        "reason": " ".join(reasons) or "News context is neutral; SMC remains the primary decision framework.",
        "headlines": relevant_headlines[:8],
        "calendar": high_impact_events[:8],
        "calendar_events": [item for item in (calendar or []) if item.get("freshness") != "unavailable"][:20],
    }