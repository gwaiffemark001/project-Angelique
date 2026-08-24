from skills.trading_skill.account import account_snapshot
from .mt5_bridge import bridge


def get_account_summary(account_mode="demo"):
    raw = bridge.get_account_info(account_mode)
    snapshot = account_snapshot(raw, account_mode)
    display_mode = "real" if snapshot.requested_mode in {"live", "real"} else "demo"
    mode = "live" if snapshot.actual_mode == "real" else snapshot.actual_mode
    requested_mode = "live" if snapshot.requested_mode in {"live", "real"} else "demo"
    mode_match = raw.get("mode_match", snapshot.connected)
    if raw.get("status") == "error" and raw.get("error"):
        mode_match = True
    return {
        "login": snapshot.login,
        "balance": snapshot.balance,
        "equity": snapshot.equity,
        "used_margin": snapshot.used_margin,
        "margin": snapshot.used_margin,
        "free_margin": snapshot.free_margin,
        "margin_level": snapshot.margin_level,
        "leverage": snapshot.leverage,
        "currency": snapshot.currency,
        "mode": mode,
        "display_mode": display_mode,
        "requested_mode": requested_mode,
        "mode_match": mode_match,
        "status": "connected" if snapshot.connected else "unavailable",
        "daily_loss_percent": raw.get("daily_loss_percent", 0),
        "weekly_loss_percent": raw.get("weekly_loss_percent", 0),
        **({"error": snapshot.error or raw.get("error")} if snapshot.error or raw.get("error") else {}),
    }
