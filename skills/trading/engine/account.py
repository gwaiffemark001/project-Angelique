from skills.trading_skill.account import account_snapshot
from .mt5_bridge import bridge


def get_account_summary(account_mode="demo"):
    raw = bridge.get_account_info(account_mode)
    snapshot = account_snapshot(raw, account_mode)
    return {"login": snapshot.login, "balance": snapshot.balance, "equity": snapshot.equity, "used_margin": snapshot.used_margin, "margin": snapshot.used_margin, "free_margin": snapshot.free_margin, "margin_level": snapshot.margin_level, "leverage": snapshot.leverage, "currency": snapshot.currency, "mode": snapshot.requested_mode, "display_mode": "real" if snapshot.requested_mode == "live" else "demo", "requested_mode": snapshot.requested_mode, "mode_match": snapshot.connected, "status": "connected" if snapshot.connected else "unavailable", **({"error": snapshot.error} if snapshot.error else {})}
