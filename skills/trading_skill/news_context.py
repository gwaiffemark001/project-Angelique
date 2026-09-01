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


#: Words that make a headline relevant to an asset even without a currency code.
ASSET_KEYWORDS: dict[str, tuple[str, ...]] = {
    "XAU": ("GOLD", "BULLION", "PRECIOUS METAL"),
    "XAG": ("SILVER", "PRECIOUS METAL"),
    "XPT": ("PLATINUM",),
    "XPD": ("PALLADIUM",),
    "BTC": ("BITCOIN", "CRYPTO"),
    "ETH": ("ETHEREUM", "ETHER", "CRYPTO"),
    "WTI": ("OIL", "CRUDE", "OPEC"),
    "XTI": ("OIL", "CRUDE", "OPEC"),
    "XBR": ("OIL", "BRENT", "OPEC"),
}


def _currencies(symbol: str, specs: dict[str, Any] | None = None) -> set[str]:
    """The assets whose news actually moves this instrument.

    Derived from the broker's ``currency_base`` / ``currency_profit`` when they
    are available, so ``EURUSD.VX`` and ``GBPJPYm`` resolve correctly instead of
    being parsed by slicing the raw symbol string. Previously a substring match
    meant a "US jobs" headline was treated as relevant to GBPJPY.
    """
    from .instruments import build_profile
    try:
        return set(build_profile(symbol, specs or {}).relevant_assets())
    except Exception:
        letters = "".join(char for char in str(symbol).upper() if char.isalpha())
        return {letters[:3], letters[3:6]} if len(letters) >= 6 else set()


def _mentions(text_upper: str, assets: set[str]) -> list[str]:
    """Which of the instrument's own assets a headline actually mentions."""
    hits: list[str] = []
    for asset in assets:
        if asset in text_upper:
            hits.append(asset)
            continue
        if any(keyword in text_upper for keyword in ASSET_KEYWORDS.get(asset, ())):
            hits.append(asset)
    return hits


def _text(item: dict[str, Any]) -> str:
    return f"{item.get('title', '')} {item.get('body', '')} {item.get('event', '')}".strip()


def assess_news(symbol: str, direction: str, specs: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assess news as an EXECUTION-TIMING risk input.

    Two rules, both required by the audit:

    1. **Relevance is per-instrument.** Only headlines and calendar events that
       mention this instrument's own currencies/assets are considered. A
       high-impact USD event is irrelevant to EURGBP.
    2. **News never alters the technical score.** ``score_adjustment`` is always
       ``0``. A relevant high-impact event routes the trade to
       ``requires_manual_approval`` instead, because a news release changes
       execution risk (spread, slippage, gapping), not the quality of the
       technical setup.
    """
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

    currencies = _currencies(symbol, specs)
    relevant_headlines = []
    ignored_headlines = 0
    high_impact_events = []
    imminent_events = []
    bullish = 0
    bearish = 0
    for item in headlines or []:
        text = _text(item)
        upper = text.upper()
        if text.lower() == "news unavailable":
            continue
        hits = _mentions(upper, currencies) if currencies else []
        if currencies and not hits:
            ignored_headlines += 1
            continue
        relevant_headlines.append({**item, "matched_assets": hits})
        bullish += sum(word in text.lower() for word in BULLISH_WORDS)
        bearish += sum(word in text.lower() for word in BEARISH_WORDS)
    for item in calendar or []:
        text = _text(item)
        upper = text.upper()
        # Calendar relevance uses the event's own currency field when present.
        event_currency = str(item.get("currency") or item.get("country") or "").upper()
        hits = _mentions(upper, currencies) if currencies else []
        if event_currency and currencies:
            relevant = any(asset in event_currency or event_currency in asset for asset in currencies)
        else:
            relevant = bool(hits) or not currencies
        if not relevant:
            continue
        if str(item.get("impact", "")).lower() in {"high", "red", "3"} or any(word in text.lower() for word in HIGH_IMPACT_WORDS):
            high_impact_events.append({**item, "matched_assets": hits or ([event_currency] if event_currency else [])})
            scheduled_at = item.get("scheduled_at")
            if scheduled_at:
                try:
                    event_time = datetime.fromisoformat(str(scheduled_at).replace("Z", "+00:00"))
                    minutes = (event_time - datetime.now(timezone.utc)).total_seconds() / 60
                    if -30 <= minutes <= 120:
                        imminent_events.append({**item, "minutes_until": minutes})
                except (TypeError, ValueError):
                    pass

    news_bias = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"
    expected = "bullish" if direction == "BUY" else "bearish"
    conflict = news_bias in {"bullish", "bearish"} and news_bias != expected

    # News NEVER changes the technical score. It changes execution risk, so it
    # routes to manual approval instead.
    adjustment = 0
    requires_manual_approval = bool(imminent_events)

    reasons = []
    if imminent_events:
        soonest = min((abs(float(e.get("minutes_until", 999))) for e in imminent_events), default=None)
        reasons.append(
            f"{len(imminent_events)} high-impact event(s) relevant to "
            f"{'/'.join(sorted(currencies)) or symbol} within the execution window"
            + (f" (nearest {soonest:.0f} min)" if soonest is not None else "")
            + ". Execution requires manual approval: spread widening, slippage and "
              "gapping risk are elevated regardless of setup quality."
        )
    elif high_impact_events:
        reasons.append(f"{len(high_impact_events)} relevant high-impact calendar event(s) detected; "
                       "release timing was not available.")
    if conflict:
        reasons.append(f"Headline bias is {news_bias}, which differs from the {direction} technical direction. "
                       "This is context only and does not change the technical score.")
    elif news_bias != "neutral":
        reasons.append(f"Headline bias is {news_bias} and is consistent with the {direction} direction.")
    if not relevant_headlines:
        reasons.append(f"No headlines mentioning {'/'.join(sorted(currencies)) or symbol} were found"
                       + (f" ({ignored_headlines} unrelated headline(s) filtered out)." if ignored_headlines else "."))
    return {
        "status": "ready" if relevant_headlines or high_impact_events else "unavailable",
        "score_adjustment": adjustment,
        "score_adjustment_policy": (
            "News never adjusts the technical score. Relevant imminent high-impact events "
            "route the trade to manual approval instead."
        ),
        "requires_manual_approval": requires_manual_approval,
        "relevant_assets": sorted(currencies),
        "filtered_out_headlines": ignored_headlines,
        "high_impact": bool(high_impact_events),
        "high_impact_imminent": bool(imminent_events),
        "data_quality": {
            "headlines": "available" if relevant_headlines else "unavailable",
            "calendar": "available" if calendar and not all(item.get("freshness") == "unavailable" for item in calendar) else "unavailable",
        },
        "directional_conflict": conflict,
        "bias": news_bias,
        "reason": " ".join(reasons) or "News context is neutral; SMC remains the primary decision framework.",
        "headlines": relevant_headlines[:5],
        "calendar": high_impact_events[:5],
    }