def get_forex_news(*args, **kwargs):
    return {"status": "unavailable", "events": [], "message": "News provider is not configured."}


def get_market_calendar(*args, **kwargs):
    return get_forex_news(*args, **kwargs)
