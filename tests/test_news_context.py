from skills.trading_skill import news_context


def test_conflicting_news_reduces_score(monkeypatch):
    monkeypatch.setattr(news_context, "get_forex_news", lambda symbol: [{"title": "USD weak growth misses expectations", "body": ""}])
    monkeypatch.setattr(news_context, "get_market_calendar", lambda **kwargs: [])
    result = news_context.assess_news("EURUSDm", "BUY")
    assert result["directional_conflict"] is True
    assert result["score_adjustment"] == -1


def test_high_impact_calendar_adds_risk_penalty(monkeypatch):
    monkeypatch.setattr(news_context, "get_forex_news", lambda symbol: [{"title": "EUR outlook", "body": ""}])
    monkeypatch.setattr(news_context, "get_market_calendar", lambda **kwargs: [{"event": "ECB interest rate decision", "impact": "high"}])
    result = news_context.assess_news("EURUSD", "BUY")
    assert result["high_impact"] is True
    assert result["score_adjustment"] <= -1


def test_news_never_decides_direction_alone(monkeypatch):
    monkeypatch.setattr(news_context, "get_forex_news", lambda symbol: [{"title": "USD surges", "body": ""}])
    monkeypatch.setattr(news_context, "get_market_calendar", lambda **kwargs: [])
    result = news_context.assess_news("EURUSD", "SELL")
    assert result["bias"] == "bullish"
    assert result["directional_conflict"] is True


def test_unavailable_news_does_not_reduce_score(monkeypatch):
    def unavailable_news(_symbol):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(news_context, "get_forex_news", unavailable_news)
    result = news_context.assess_news("NZDUSDm", "BUY")
    assert result["status"] == "unavailable"
    assert result["score_adjustment"] == 0


def test_imminent_high_impact_event_is_marked_for_execution_block(monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(news_context, "get_forex_news", lambda symbol: [])
    event_time = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    monkeypatch.setattr(
        news_context,
        "get_market_calendar",
        lambda **kwargs: [{"event": "US CPI", "impact": "high", "scheduled_at": event_time}],
    )
    result = news_context.assess_news("NZDUSD", "BUY")
    assert result["high_impact"] is True
    assert result["high_impact_imminent"] is True