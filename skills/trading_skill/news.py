import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from core import config

CACHE_TTL_SECONDS = 300
MAX_HEADLINE_AGE_SECONDS = 24 * 60 * 60
NEWS_CACHE_DIR = getattr(config, "NEWS_CACHE_DIR", Path.home() / ".config" / "angelique" / "news_cache")
NEWS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_NEWS_SOURCES = [
    *config.FOREX_FACTORY_URLS,
    "https://finance.yahoo.com/",
    "https://www.investing.com/news/forex-news",
    "https://www.marketwatch.com/latest-news",
    "https://www.reuters.com/markets/",
    "https://www.tradingview.com/economic-calendar/",
    "https://www.fxstreet.com/economic-calendar/",
    "https://www.federalreserve.gov/newsevents/pressreleases/",
    "https://www.bbc.com/news",
    "https://www.aljazeera.com",
    "https://www.reuters.com/world/",
    "https://www.cnbc.com/world/",
    "https://www.wsj.com/news/markets",
]

HEADLINE_BLACKLIST = {
    "newsletter",
    "sponsored",
    "advertisement",
    "subscribe",
    "log in",
    "sign in",
    "privacy",
    "cookie",
    "feedback",
    "terms",
    "copyright",
    "contact",
}


def _cache_key(prefix: str, identifier: str) -> Path:
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()
    return NEWS_CACHE_DIR / f"{prefix}_{digest}.json"


def _load_cache(cache_path: Path) -> Any | None:
    try:
        if cache_path.exists() and time.time() - cache_path.stat().st_mtime < CACHE_TTL_SECONDS:
            return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


def _save_cache(cache_path: Path, value: Any) -> None:
    try:
        cache_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _normalize_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _safe_fetch(url: str) -> str:
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Angelique/1.0",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=12,
        )
        if response.status_code == 200:
            return response.text
    except Exception:
        pass
    return ""


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_url(base_url: str, link: str) -> str:
    link = link.strip()
    if not link:
        return ""
    if link.startswith("//"):
        parsed = urlparse(base_url)
        return f"{parsed.scheme}:{link}"
    if link.startswith("/"):
        return urljoin(base_url, link)
    if not urlparse(link).scheme:
        return urljoin(base_url, link)
    return link


def _extract_headlines(html: str, source_url: str, retrieved_at: str | None = None) -> list[dict[str, str]]:
    headlines: list[dict[str, str]] = []
    found_titles: set[str] = set()

    # Gather linked text from anchor tags and heading tags.
    for match in re.findall(r"<a[^>]+href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", html, flags=re.S | re.I):
        url, text = match
        title = _normalize_text(text)
        if len(title) < 40:
            continue
        lower = title.lower()
        if any(blk in lower for blk in HEADLINE_BLACKLIST):
            continue
        if lower in found_titles:
            continue
        found_titles.add(lower)
        headlines.append({
            "title": title,
            "body": "",
            "source": source_url,
            "url": _normalize_url(source_url, url),
            "retrieved_at": retrieved_at or _retrieved_at(),
            "freshness": "fresh",
        })
        if len(headlines) >= 20:
            break

    # If anchor text is scarce, also look for heading text.
    if len(headlines) < 6:
        for match in re.findall(r"<(?:h1|h2|h3|h4)[^>]*>(.*?)</(?:h1|h2|h3|h4)>", html, flags=re.S | re.I):
            title = _normalize_text(match)
            if len(title) < 40:
                continue
            lower = title.lower()
            if any(blk in lower for blk in HEADLINE_BLACKLIST):
                continue
            if lower in found_titles:
                continue
            found_titles.add(lower)
            headlines.append({
                "title": title,
                "body": "",
                "source": source_url,
                "url": source_url,
                "retrieved_at": retrieved_at or _retrieved_at(),
                "freshness": "fresh",
            })
            if len(headlines) >= 20:
                break

    return headlines[:12]


def _extract_forex_factory_calendar(html: str, retrieved_at: str | None = None) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for match in re.findall(
        r"<tr[^>]*>.*?<td[^>]*class=[\"']calendar__time[^\"']*[\"'][^>]*>(.*?)</td>.*?<td[^>]*class=[\"']calendar__event[^\"']*[\"'][^>]*>(.*?)</td>.*?<td[^>]*class=[\"']calendar__impact[^\"']*[\"'][^>]*>(.*?)</td>",
        html,
        flags=re.S | re.I,
    ):
        time_text = _normalize_text(match[0])
        event_text = _normalize_text(match[1])
        impact_text = _normalize_text(match[2])
        if not event_text:
            continue
        events.append({
            "time": time_text or "TBD",
            "event": event_text,
            "impact": impact_text or "unknown",
            "retrieved_at": retrieved_at or _retrieved_at(),
            "freshness": "fresh",
        })
        if len(events) >= 20:
            break
    return events


def get_forex_news(symbol: str | None = None) -> list[dict[str, str]]:
    sources = DEFAULT_NEWS_SOURCES
    if symbol:
        symbol = symbol.strip().upper()
        sources = [url for url in sources if symbol.lower() in url.lower()] + sources

    aggregated: list[dict[str, str]] = []
    seen_titles: set[str] = set()

    for source in sources:
        cache_path = _cache_key("news", source)
        cached = _load_cache(cache_path)
        html = cached if isinstance(cached, str) else _safe_fetch(source)
        if not html:
            continue

        if not isinstance(cached, str):
            _save_cache(cache_path, html)

        retrieved_at = datetime.fromtimestamp(cache_path.stat().st_mtime, timezone.utc).isoformat() if isinstance(cached, str) else _retrieved_at()
        freshness = "cached" if isinstance(cached, str) else "fresh"
        headlines = _extract_headlines(html, source, retrieved_at)
        for headline in headlines:
            headline["freshness"] = freshness
            title_key = headline["title"].lower()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            # Do not require the literal broker symbol (e.g. EURUSD.VX) to
            # appear in a headline. Symbol relevance is resolved later by
            # currency/asset context; requiring the exact symbol silently
            # dropped almost all legitimate market headlines.
            aggregated.append(headline)
            if len(aggregated) >= 24:
                break
        if len(aggregated) >= 24:
            break

    if not aggregated:
        return [{"title": "News unavailable", "body": "Angelique could not retrieve market news at this time.", "source": "internal", "url": "", "freshness": "unavailable"}]

    return aggregated


def get_market_calendar(*args: Any, **kwargs: Any) -> list[dict[str, str]]:
    symbol = str(kwargs.get("symbol") or "").upper()
    currencies = {symbol[:3], symbol[3:6]} if len(symbol) >= 6 else set()
    events: list[dict[str, str]] = []
    for source in config.FOREX_FACTORY_URLS:
        cache_path = _cache_key("calendar", source)
        cached = _load_cache(cache_path)
        html = cached if isinstance(cached, str) else _safe_fetch(source)
        if not html:
            continue

        if not isinstance(cached, str):
            _save_cache(cache_path, html)

        retrieved_at = datetime.fromtimestamp(cache_path.stat().st_mtime, timezone.utc).isoformat() if isinstance(cached, str) else _retrieved_at()
        events = _extract_forex_factory_calendar(html, retrieved_at)
        for event in events:
            event["freshness"] = "cached" if isinstance(cached, str) else "fresh"
        if currencies:
            filtered = []
            for event in events:
                text = f"{event.get('event', '')} {event.get('currency', '')}".upper()
                if not event.get("currency") and not any(currency in text for currency in currencies):
                    continue
                if any(currency in text for currency in currencies):
                    filtered.append(event)
            events = filtered
        if events:
            break

    if not events:
        return [{"time": "N/A", "event": "Market calendar data unavailable.", "impact": "unknown", "freshness": "unavailable"}]

    return events[:20]
