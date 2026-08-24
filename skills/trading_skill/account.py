from __future__ import annotations

from .models import AccountSnapshot


def normalize_mode(value: str) -> str:
    return "real" if str(value or "demo").lower() in {"live", "real"} else "demo"


def account_snapshot(payload: dict, requested_mode: str) -> AccountSnapshot:
    requested = str(requested_mode or "demo").lower()
    internal_mode = normalize_mode(requested)
    actual = normalize_mode(str(payload.get("mode") or internal_mode)) if isinstance(payload, dict) else internal_mode
    if (
        not isinstance(payload, dict)
        or not payload.get("login")
        or payload.get("mode_match") is False
        or payload.get("error")
    ):
        return AccountSnapshot(
            requested_mode=requested,
            actual_mode=actual,
            connected=False,
            login=None,
            error=(payload or {}).get("error", "The selected MT5 account is not connected."),
        )
    return AccountSnapshot(
        requested_mode=requested,
        actual_mode=actual,
        connected=True,
        login=int(payload["login"]),
        balance=float(payload.get("balance", 0) or 0),
        equity=float(payload.get("equity", 0) or 0),
        used_margin=float(payload.get("used_margin", payload.get("margin", 0)) or 0),
        free_margin=float(payload.get("free_margin", 0) or 0),
        margin_level=float(payload.get("margin_level", 0) or 0),
        leverage=int(payload.get("leverage", 0) or 0),
        currency=str(payload.get("currency", "USD")),
    )
