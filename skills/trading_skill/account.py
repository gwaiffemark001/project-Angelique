from __future__ import annotations

from .models import AccountSnapshot


def normalize_mode(value: str) -> str:
    value = str(value or "demo").strip().lower()
    if value in {"live", "real"}:
        return "real"
    return "demo"


def account_snapshot(payload: dict, requested_mode: str) -> AccountSnapshot:
    requested = normalize_mode(requested_mode)
    if not isinstance(payload, dict):
        return AccountSnapshot(requested, "unknown", False, None, error="MT5 returned an invalid account response.")

    raw_actual = str(payload.get("mode") or "").lower()
    actual = "real" if raw_actual in {"real", "live"} else "demo" if raw_actual == "demo" else requested
    mode_matches = payload.get("mode_match") is not False and (actual == requested or raw_actual == "")
    login = payload.get("login")
    if not login or payload.get("error") or not mode_matches:
        reason = payload.get("error") or f"MT5 account mode is {actual}; requested {requested}."
        if not mode_matches and "not connected" not in reason.lower():
            reason = f"MT5 account is not connected: {reason}"
        return AccountSnapshot(requested, actual, False, None, error=reason)

    daily_loss_value = payload.get("daily_loss_percent")
    weekly_loss_value = payload.get("weekly_loss_percent")
    if daily_loss_value is None or weekly_loss_value is None:
        return AccountSnapshot(requested, actual, False, None, error="MT5 daily/weekly realized-loss metrics are unavailable; trading is blocked.")

    return AccountSnapshot(
        requested_mode=requested,
        actual_mode=actual,
        connected=True,
        login=int(login),
        balance=float(payload.get("balance", 0) or 0),
        equity=float(payload.get("equity", 0) or 0),
        used_margin=float(payload.get("used_margin", payload.get("margin", 0)) or 0),
        free_margin=float(payload.get("free_margin", 0) or 0),
        margin_level=float(payload.get("margin_level", 0) or 0),
        leverage=int(payload.get("leverage", 0) or 0),
        currency=str(payload.get("currency", "USD")),
        broker=str(payload.get("broker", payload.get("company", "")) or ""),
        platform=str(payload.get("platform", "MT5") or "MT5"),
        daily_loss_percent=float(daily_loss_value),
        weekly_loss_percent=float(weekly_loss_value),
        drawdown_percent=float(payload.get("drawdown_percent", 0) or 0),
        consecutive_losses=int(payload.get("consecutive_losses", 0) or 0),
    )
