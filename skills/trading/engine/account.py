from skills.trading.engine.mt5_bridge import bridge


def _normalize_account_mode(mode: str | None) -> str:
    mode = str(mode or "demo").strip().lower()
    if mode in {"real", "live"}:
        return "live"
    return "demo"


def get_account_summary(account_mode: str = "demo") -> dict:
    """Fetches and formats account health for the Risk Manager."""
    account_mode = _normalize_account_mode(account_mode)

    info = bridge.get_account_info(account_mode=account_mode)
    requested_mode = account_mode
    actual_mode = _normalize_account_mode(info.get("mode", requested_mode))
    mode_match = requested_mode == actual_mode

    if "error" in info and not info.get("login") and mode_match:
        display_mode = "real" if actual_mode == "live" else actual_mode
        return {
            "login": None,
            "balance": 0,
            "equity": 0,
            "free_margin": 0,
            "margin_level": 0,
            "leverage": 0,
            "currency": info.get("currency", "USD"),
            "mode": actual_mode,
            "display_mode": display_mode,
            "requested_mode": requested_mode,
            "mode_match": mode_match,
            "status": info.get("status", "error"),
            "error": info.get("error"),
        }

    if not mode_match:
        # When the requested mode does not match the connected MT5 account,
        # show the requested account summary as unavailable while preserving
        # the connected account mode for mismatch diagnostics.
        display_mode = "real" if requested_mode == "live" else requested_mode
        return {
            "login": None,
            "balance": 0,
            "equity": 0,
            "free_margin": 0,
            "margin_level": 0,
            "leverage": 0,
            "currency": info.get("currency", "USD"),
            "mode": actual_mode,
            "display_mode": display_mode,
            "requested_mode": requested_mode,
            "mode_match": False,
            "status": info.get("status", "connected"),
            "error": info.get("error"),
        }
    if "error" in info:
        display_mode = "real" if requested_mode == "live" else requested_mode
        return {
            "login": None,
            "balance": 0,
            "equity": 0,
            "free_margin": 0,
            "margin_level": 0,
            "leverage": 0,
            "currency": info.get("currency", "USD"),
            "mode": actual_mode,
            "display_mode": display_mode,
            "requested_mode": requested_mode,
            "mode_match": mode_match,
            "status": info.get("status", "error"),
            "error": info.get("error"),
        }

    display_mode = "real" if actual_mode == "live" else actual_mode
    return {
        "login": info.get("login"),
        "balance": info.get("balance", 0),
        "equity": info.get("equity", 0),
        "free_margin": info.get("free_margin", 0),
        "margin_level": info.get("margin_level", 0),
        "leverage": info.get("leverage", 0),
        "currency": info.get("currency", "USD"),
        "mode": actual_mode,
        "display_mode": display_mode,
        "requested_mode": requested_mode,
        "mode_match": mode_match,
        "status": info.get("status", "connected"),
    }
