def get_trading_status_state(account_mode, bridge_connected, bridge_error=None, mode_match=True):
    mode = "real" if str(account_mode).lower() in {"real", "live"} else "demo"
    if not bridge_connected:
        if mode == "demo":
            return {"label": "DEMO MODE ACTIVE", "tone": "warning", "color": "#f59e0b", "detail": bridge_error or ""}
        return {"label": "REAL MT5 OFFLINE", "tone": "danger", "color": "#dc2626", "detail": bridge_error or ""}
    if not mode_match:
        return {"label": "ACCOUNT MODE MISMATCH", "tone": "warning", "color": "#f59e0b", "detail": bridge_error or ""}
    return {"label": "REAL MT5 CONNECTED" if mode == "real" else "DEMO MODE ACTIVE", "tone": "success", "color": "#16a34a" if mode == "real" else "#0ea5e9", "detail": ""}


def get_bridge_status_label(bridge_connected: bool, bridge_error: str | None = None) -> str:
    if bridge_connected:
        return f"Bridge detail: {bridge_error}" if bridge_error else "Bridge connected and ready."
    if bridge_error:
        return f"Bridge detail: {bridge_error}"
    return "Bridge unavailable: MT5 connection is offline."


def get_mt5_data_badge_text(actual_mode: str | None, requested_mode: str | None, bridge_connected: bool, account_connected: bool, bridge_error: str | None = None, mode_match: bool = True) -> str:
    actual = str(actual_mode or "").lower()
    requested = str(requested_mode or "").lower()
    if not bridge_connected or not account_connected:
        return "MT5 unavailable"
    if not mode_match:
        actual_label = self_display(actual) if actual in {"real", "demo"} else "UNKNOWN"
        requested_label = self_display(requested) if requested in {"real", "demo"} else "UNKNOWN"
        return f"Mode mismatch: connected {actual_label}, requested {requested_label}"
    if actual == "real":
        return "Using real MT5 data"
    if actual == "demo":
        return "Using demo MT5 data"
    if bridge_error:
        return "MT5 unavailable"
    return ""


def self_display(mode: str | None) -> str:
    normalized = str(mode or "").lower()
    if normalized in {"real", "live"}:
        return "REAL"
    if normalized == "demo":
        return "DEMO"
    return normalized.upper() if normalized else "UNKNOWN"


def build_trading_status_banner(account_mode, bridge_connected, bridge_error=None, balance=0, mode_match=True):
    state = get_trading_status_state(account_mode, bridge_connected, bridge_error, mode_match)
    return f"{state['label']} | Balance: ${float(balance or 0):,.2f}" + (f" | {state['detail']}" if state.get("detail") else "")
