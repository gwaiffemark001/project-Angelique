from skills.trading.engine.mt5_bridge import bridge

def get_symbol_info(symbol: str) -> dict:
    """Fetches contract specs for a specific symbol."""
    # In a full implementation, this would query the bridge for symbol specs
    # For now, we return a standardized structure
    return {
        "symbol": symbol,
        "point": 0.00001 if "JPY" not in symbol else 0.001,
        "digits": 5 if "JPY" not in symbol else 3,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01
    }
