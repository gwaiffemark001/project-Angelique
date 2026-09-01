from skills.trading_skill.news import get_forex_news
from skills.trading_skill.data_quality import assess_candles
from skills.trading_skill.profiles import DAY_PROFILE


def test_news_symbol_filter_does_not_drop_general_headlines(monkeypatch):
    import skills.trading_skill.news as news
    monkeypatch.setattr(news, "DEFAULT_NEWS_SOURCES", ["https://example.test/news"])
    monkeypatch.setattr(news, "_safe_fetch", lambda url: '<a href="/x">EUR and USD markets react to central bank outlook and growth data today</a>')
    monkeypatch.setattr(news, "_load_cache", lambda _: None)
    monkeypatch.setattr(news, "_save_cache", lambda *_: None)
    items = get_forex_news("EURUSD.VX")
    assert items and items[0]["title"] != "News unavailable"


def test_required_timeframe_health_can_distinguish_stale_history():
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    candles = []
    for i in range(DAY_PROFILE.minimum_analysis_candles("M5")):
        t = now - timedelta(minutes=5*(len(range(DAY_PROFILE.minimum_analysis_candles("M5")))-i) + 120*60)
        candles.append({"time": t.isoformat(), "open": 100+i*0.01, "high": 100.02+i*0.01, "low": 99.98+i*0.01, "close": 100.01+i*0.01, "closed": True})
    result = assess_candles(candles, "M5", minimum_candles=DAY_PROFILE.minimum_analysis_candles("M5"))
    assert result["status"] == "stale"
