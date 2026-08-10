def get_trading_status_state(account_mode, bridge_connected, bridge_error=None, mode_match=True):
    mode = "real" if str(account_mode).lower() in {"real", "live"} else "demo"
    if not bridge_connected:
        if mode == "demo":
            return {"label": "DEMO MODE ACTIVE", "tone": "warning", "color": "#f59e0b", "detail": bridge_error or ""}
        return {"label": "REAL MT5 OFFLINE", "tone": "danger", "color": "#dc2626", "detail": bridge_error or ""}
    if not mode_match:
        return {"label": "ACCOUNT MODE MISMATCH", "tone": "warning", "color": "#f59e0b", "detail": bridge_error or ""}
    return {"label": "REAL MT5 CONNECTED" if mode == "real" else "DEMO MODE ACTIVE", "tone": "success", "color": "#16a34a" if mode == "real" else "#0ea5e9", "detail": ""}


def build_trading_status_banner(account_mode, bridge_connected, bridge_error=None, balance=0, mode_match=True):
    state = get_trading_status_state(account_mode, bridge_connected, bridge_error, mode_match)
    return f"{state['label']} | Balance: ${float(balance or 0):,.2f}" + (f" | {state['detail']}" if state.get("detail") else "")
