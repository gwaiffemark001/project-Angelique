from __future__ import annotations

from typing import Any


def validate_trade_setup(
    *,
    direction: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    risk_amount: float,
    risk_percent: float,
    volume: float,
    margin_required: float,
    free_margin_after: float,
    minimum_free_margin: float,
    current_margin_level: float,
    spread: float | None = None,
    minimum_rr: float = 2.0,
) -> dict[str, Any]:
    """Hard safety checks that gate trading decisions before execution."""
    checks: list[str] = []
    reasons: list[str] = []

    if direction not in {"BUY", "SELL"}:
        reasons.append("Direction is invalid.")
    if not (entry > 0 and stop_loss > 0 and take_profit > 0):
        reasons.append("Entry, stop, and target must all be positive values.")

    distance_to_sl = abs(entry - stop_loss)
    if distance_to_sl <= 0:
        reasons.append("Stop loss is not distinct from entry.")
    else:
        checks.append(f"Stop distance: {distance_to_sl:.6f}")

    rr = abs(take_profit - entry) / max(distance_to_sl, 1e-9)
    if rr < minimum_rr:
        reasons.append(f"Reward-to-risk is below the minimum required ({minimum_rr:.2f}:1).")
    else:
        checks.append(f"Risk-reward OK: {rr:.2f}:1")

    if risk_percent <= 0:
        reasons.append("Risk percentage must be positive.")
    if risk_amount <= 0:
        reasons.append("Calculated risk amount must be positive.")
    if volume <= 0:
        reasons.append("Volume must be positive.")

    if free_margin_after < minimum_free_margin:
        reasons.append("Free margin after trade would violate the configured minimum margin.")
    else:
        checks.append("Free margin above minimum threshold.")

    if current_margin_level > 0 and current_margin_level < 100:
        reasons.append(f"Projected margin level is too low ({current_margin_level:.1f}%).")
    else:
        checks.append("Margin level remains acceptable.")

    if spread is not None and spread > 0:
        spread_ok = spread < (abs(take_profit - entry) * 0.8)
        if not spread_ok:
            reasons.append("Spread is too wide relative to the intended move.")
        else:
            checks.append(f"Spread is acceptable: {spread:.6f}.")

    valid = not reasons
    return {
        "valid": valid,
        "check_count": len(checks),
        "checks": checks,
        "reasons": reasons,
        "summary": "Trade safety checks passed." if valid else "Trade safety checks failed.",
    }
