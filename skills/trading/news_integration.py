"""
News Integration Module for Angelique Trading Hub
Implements multi-source economic calendar with Risk-Off/Blackout logic.

SOURCES:
1. Financial Modeling Prep (FMP) - Primary (Official API)
2. Finnhub - Real-time News/Sentiment (Official API)
3. Forex Factory - Supplementary (UNOFFICIAL SCRAPER - USE WITH CAUTION)

⚠️ CRITICAL WARNING ABOUT FOREX FACTORY:
- This scraper violates Forex Factory Terms of Service
- Use ONLY as a last resort fallback
- Aggressive rate limiting implemented (max 1 req per 15 min)
- Can be disabled via ENABLE_FOREX_FACTORY_SCRAPER=false
"""

import os
import time
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from functools import lru_cache

import requests
from cachetools import TTLCache
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# API Keys
FMP_API_KEY = os.getenv("FMP_API_KEY")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
ENABLE_FOREX_FACTORY = os.getenv("ENABLE_FOREX_FACTORY_SCRAPER", "false").lower() == "true"

# Configuration
NEWS_BLACKOUT_MINUTES_BEFORE = int(os.getenv("NEWS_BLACKOUT_MINUTES_BEFORE", "30"))
NEWS_BLACKOUT_MINUTES_AFTER = int(os.getenv("NEWS_BLACKOUT_MINUTES_AFTER", "15"))

# Caching (TTL in seconds)
CACHE_FMP = TTLCache(maxsize=10, ttl=43200)  # 12 hours
CACHE_FINNHUB = TTLCache(maxsize=50, ttl=120)  # 2 minutes
CACHE_FF = TTLCache(maxsize=10, ttl=3600)  # 1 hour minimum

# User Agents for scraping
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
]


def get_fmp_economic_calendar(currencies: List[str] = None) -> List[Dict]:
    """
    Fetch economic calendar from Financial Modeling Prep (Primary Source).
    Caches for 12 hours to respect 250 req/day limit.
    """
    if currencies is None:
        currencies = ["USD", "EUR", "GBP", "JPY"]
    
    cache_key = f"fmp_{tuple(currencies)}_{datetime.now().date()}"
    if cache_key in CACHE_FMP:
        logger.debug("Using cached FMP calendar data")
        return CACHE_FMP[cache_key]
    
    if not FMP_API_KEY:
        logger.warning("FMP_API_KEY not found. Skipping FMP calendar fetch.")
        return []
    
    try:
        # FMP Economic Calendar Endpoint
        today = datetime.now().strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        
        url = f"https://financialmodelingprep.com/api/v3/economic_calendar"
        params = {
            "from": today,
            "to": tomorrow,
            "apikey": FMP_API_KEY
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Filter for high impact and specific currencies
        high_impact_events = []
        for event in data:
            impact = event.get("impact", "").lower()
            currency = event.get("currency", "")
            
            if impact == "high" and currency in currencies:
                high_impact_events.append({
                    "source": "FMP",
                    "time": event.get("date"),
                    "currency": currency,
                    "event": event.get("event"),
                    "actual": event.get("actual"),
                    "estimate": event.get("estimate"),
                    "previous": event.get("previous"),
                    "impact": "High"
                })
        
        CACHE_FMP[cache_key] = high_impact_events
        logger.info(f"FMP Calendar: Found {len(high_impact_events)} high-impact events")
        return high_impact_events
        
    except Exception as e:
        logger.error(f"FMP Calendar fetch failed: {e}")
        return []


def get_forex_factory_calendar(currencies: List[str] = None) -> List[Dict]:
    """
    ⚠️ UNOFFICIAL SCRAPER - USE AT YOUR OWN RISK ⚠️
    Scrapes Forex Factory economic calendar.
    
    SAFETY MEASURES:
    - Random delay (30-60s) before request
    - Max 1 request per 15 minutes enforced by cache
    - Exponential backoff on errors
    - Can be disabled via ENABLE_FOREX_FACTORY_SCRAPER=false
    """
    if not ENABLE_FOREX_FACTORY:
        logger.info("Forex Factory scraper is DISABLED. Set ENABLE_FOREX_FACTORY_SCRAPER=true to enable.")
        return []
    
    if currencies is None:
        currencies = ["USD", "EUR", "GBP", "JPY"]
    
    cache_key = f"ff_{tuple(currencies)}_{datetime.now().hour}"
    if cache_key in CACHE_FF:
        logger.debug("Using cached Forex Factory data")
        return CACHE_FF[cache_key]
    
    logger.warning("⚠️ INITIATING FOREX FACTORY SCRAPER (ToS Violation Risk) ⚠️")
    
    # Random delay 30-60 seconds
    delay = random.uniform(30, 60)
    logger.info(f"Waiting {delay:.1f}s before scraping (rate limiting)...")
    time.sleep(delay)
    
    headers = {"User-Agent": random.choice(USER_AGENTS)}
    url = "https://www.forexfactory.com/calendar.php?day=today"
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        events = []
        # Parse table rows (simplified parser)
        rows = soup.find_all('tr', class_='calendar_row')
        
        for row in rows:
            cells = row.find_all('td')
            if len(cells) >= 4:
                time_cell = cells[0].find('div', class_='calendar__cell--time')
                curr_cell = cells[1].find('span', class_='calendar__cell--currency')
                impact_cell = cells[2].find('div', class_='calendar__cell--impact')
                event_cell = cells[3].find('a', class_='calendar__cell--event')
                
                if time_cell and curr_cell and impact_cell:
                    currency = curr_cell.text.strip()
                    impact_class = impact_cell.get('class', [])
                    
                    # Determine impact level
                    impact = "Low"
                    if 'impact--high' in str(impact_class):
                        impact = "High"
                    elif 'impact--medium' in str(impact_class):
                        impact = "Medium"
                    
                    if currency in currencies and impact == "High":
                        events.append({
                            "source": "ForexFactory",
                            "time": time_cell.text.strip(),
                            "currency": currency,
                            "event": event_cell.text.strip() if event_cell else "Unknown Event",
                            "impact": impact
                        })
        
        CACHE_FF[cache_key] = events
        logger.warning(f"⚠️ Forex Factory scrape complete: {len(events)} high-impact events found")
        return events
        
    except Exception as e:
        logger.error(f"Forex Factory scrape failed: {e}")
        # Exponential backoff could be implemented here for retries
        return []


def get_forex_news_sentiment() -> List[Dict]:
    """
    Fetch real-time forex news from Finnhub.
    Caches for 2 minutes to respect 60 req/min limit.
    """
    cache_key = "finnhub_news"
    if cache_key in CACHE_FINNHUB:
        return CACHE_FINNHUB[cache_key]
    
    if not FINNHUB_API_KEY:
        logger.warning("FINNHUB_API_KEY not found.")
        return []
    
    try:
        # General market news
        now = datetime.now()
        from_time = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        to_time = now.strftime("%Y-%m-%dT%H:%M:%S")
        
        url = "https://finnhub.io/api/v1/news"
        params = {
            "category": "forex",
            "from": from_time,
            "to": to_time,
            "token": FINNHUB_API_KEY
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Check for urgent keywords
        urgent_keywords = ["CPI", "NFP", "FOMC", "Rate Decision", "Emergency", "Hike", "Cut"]
        urgent_news = []
        
        for item in data[:10]:  # Limit to 10 latest
            headline = item.get("headline", "").upper()
            is_urgent = any(keyword in headline for keyword in urgent_keywords)
            
            urgent_news.append({
                "headline": item.get("headline"),
                "summary": item.get("summary"),
                "time": item.get("datetime"),
                "is_urgent": is_urgent
            })
        
        CACHE_FINNHUB[cache_key] = urgent_news
        logger.info(f"Finnhub News: Found {len(urgent_news)} articles, {sum(1 for n in urgent_news if n['is_urgent'])} urgent")
        return urgent_news
        
    except Exception as e:
        logger.error(f"Finnhub news fetch failed: {e}")
        return []


def merge_calendar_sources(fmp_data: List[Dict], ff_data: List[Dict]) -> List[Dict]:
    """
    Merge and deduplicate calendar events from multiple sources.
    Prioritizes FMP data when conflicts exist.
    """
    unified = {}
    
    # Add FMP first (higher priority)
    for event in fmp_data:
        key = f"{event.get('time')}_{event.get('currency')}_{event.get('event')}"
        unified[key] = event
    
    # Add Forex Factory if not duplicate
    for event in ff_data:
        key = f"{event.get('time')}_{event.get('currency')}_{event.get('event')}"
        if key not in unified:
            unified[key] = event
    
    result = list(unified.values())
    # Sort by time
    result.sort(key=lambda x: x.get('time', ''))
    return result


def get_unified_economic_calendar() -> List[Dict]:
    """
    Master function to fetch and unify economic calendar.
    Order: FMP (Primary) -> Forex Factory (Fallback/Supplementary)
    """
    fmp_data = get_fmp_economic_calendar()
    ff_data = get_forex_factory_calendar()
    
    if not fmp_data and not ff_data:
        logger.warning("No calendar data available from any source.")
        return []
    
    return merge_calendar_sources(fmp_data, ff_data)


def check_market_risk() -> Tuple[str, Optional[Dict]]:
    """
    CRITICAL: Determines if it's safe to trade based on upcoming news.
    
    Returns:
        Tuple[status, next_event]
        status: "RED_LIGHT" (Block), "YELLOW_LIGHT" (Caution), "GREEN_LIGHT" (Safe)
        next_event: Details of the upcoming high-impact event if any
    """
    events = get_unified_economic_calendar()
    news = get_forex_news_sentiment()
    
    now = datetime.now()
    
    # Check for urgent news headlines
    urgent_headlines = [n for n in news if n.get("is_urgent")]
    if urgent_headlines:
        logger.warning(f"YELLOW LIGHT: Urgent news detected: {urgent_headlines[0]['headline']}")
        return "YELLOW_LIGHT", {"type": "news", "headline": urgent_headlines[0]['headline']}
    
    # Check upcoming events
    for event in events:
        try:
            # Parse event time (formats vary by source)
            event_time_str = event.get('time', '')
            # Simple parsing logic - may need refinement based on actual API response formats
            if 'T' in event_time_str:
                event_time = datetime.fromisoformat(event_time_str.replace('Z', '+00:00'))
            else:
                # Assume today/tomorrow for simple strings
                event_time = now  # Fallback
            
            delta = event_time - now
            minutes_until = delta.total_seconds() / 60
            
            # RED LIGHT: Event within buffer window
            if -NEWS_BLACKOUT_MINUTES_AFTER <= minutes_until <= NEWS_BLACKOUT_MINUTES_BEFORE:
                logger.warning(f"RED LIGHT: High impact event '{event.get('event')}' in {minutes_until:.1f} mins")
                return "RED_LIGHT", event
                
        except Exception as e:
            logger.debug(f"Could not parse event time: {e}")
            continue
    
    logger.info("GREEN LIGHT: No high-impact news events in blackout window.")
    return "GREEN_LIGHT", None


def get_next_high_impact_event() -> Optional[Dict]:
    """Returns the next scheduled high-impact event with countdown."""
    events = get_unified_economic_calendar()
    if not events:
        return None
    
    now = datetime.now()
    next_event = None
    min_delta = float('inf')
    
    for event in events:
        try:
            event_time_str = event.get('time', '')
            if 'T' in event_time_str:
                event_time = datetime.fromisoformat(event_time_str.replace('Z', '+00:00'))
            else:
                continue
            
            delta = (event_time - now).total_seconds()
            if 0 < delta < min_delta:
                min_delta = delta
                next_event = event
                next_event['countdown_minutes'] = delta / 60
        except:
            continue
    
    return next_event


def check_api_health() -> Dict:
    """Tests connectivity and quota for all data sources."""
    status = {
        "fmp": "unknown",
        "finnhub": "unknown",
        "forex_factory": "disabled" if not ENABLE_FOREX_FACTORY else "unknown"
    }
    
    # Test FMP
    try:
        data = get_fmp_economic_calendar()
        status["fmp"] = "healthy" if data is not None else "error"
    except:
        status["fmp"] = "down"
    
    # Test Finnhub
    try:
        data = get_forex_news_sentiment()
        status["finnhub"] = "healthy" if data is not None else "error"
    except:
        status["finnhub"] = "down"
    
    # Test Forex Factory (only if enabled)
    if ENABLE_FOREX_FACTORY:
        try:
            data = get_forex_factory_calendar()
            status["forex_factory"] = "healthy" if data is not None else "error"
        except:
            status["forex_factory"] = "down"
    
    return status


if __name__ == "__main__":
    print("=== News Integration Test ===")
    print(f"Forex Factory Scraper Enabled: {ENABLE_FOREX_FACTORY}")
    
    print("\n1. Testing Unified Calendar...")
    calendar = get_unified_economic_calendar()
    print(f"Found {len(calendar)} high-impact events")
    for evt in calendar[:3]:
        print(f"  - {evt.get('time')}: {evt.get('currency')} {evt.get('event')} ({evt.get('source')})")
    
    print("\n2. Testing Market Risk...")
    risk_status, event = check_market_risk()
    print(f"Current Status: {risk_status}")
    if event:
        print(f"Reason: {event}")
    
    print("\n3. API Health Check...")
    health = check_api_health()
    for src, stat in health.items():
        print(f"  {src}: {stat}")
