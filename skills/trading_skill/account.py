from __future__ import annotations

from .models import AccountSnapshot


def normalize_mode(value: str) -> str:
    return "live" if str(value or "demo").lower() in {"live", "real"} else "demo"


def account_snapshot(payload: dict, requested_mode: str) -> AccountSnapshot:
    mode = normalize_mode(requested_mode)
    if not isinstance(payload, dict) or not payload.get("login") or payload.get("mode_match") is False or payload.get("error"):
        return AccountSnapshot(mode, False, None, error=(payload or {}).get("error", "The selected MT5 account is not connected."))
    return AccountSnapshot(
        mode,
        True,
        int(payload["login"]),
        float(payload.get("balance", 0) or 0),
        float(payload.get("equity", 0) or 0),
        float(payload.get("used_margin", payload.get("margin", 0)) or 0),
        float(payload.get("free_margin", 0) or 0),
        float(payload.get("margin_level", 0) or 0),
        int(payload.get("leverage", 0) or 0),
        str(payload.get("currency", "USD")),
    )
