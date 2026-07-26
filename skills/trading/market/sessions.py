from datetime import datetime

def get_current_session() -> str:
    """Determines the current forex trading session (UTC)."""
    hour = datetime.utcnow().hour
    if 0 <= hour < 7: return "Sydney/Tokyo (Asian)"
    elif 7 <= hour < 12: return "London (European)"
    elif 12 <= hour < 16: return "London/New York (Overlap - High Volatility)"
    elif 16 <= hour < 21: return "New York (American)"
    else: return "Post-New York (Low Volatility)"
