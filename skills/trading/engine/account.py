from skills.trading.engine.mt5_bridge import bridge

def get_account_summary() -> dict:
    """Fetches and formats account health for the Risk Manager."""
    info = bridge.get_account_info()
    if "error" in info: return info
    return {
        "balance": info.get("balance", 0),
        "equity": info.get("equity", 0),
        "free_margin": info.get("free_margin", 0),
        "margin_level": info.get("margin_level", 0),
        "leverage": info.get("leverage", 0),
        "currency": info.get("currency", "USD")
    }
