from __future__ import annotations

from typing import Any
from core import config
from .profiles import max_spread_for_symbol


def validate_trade_setup(
    *,
    symbol: str | None = None,
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
    projected_margin_level: float | None = None,
    current_margin_level: float | None = None,
    # `spread` is the raw price difference (ask - bid) in price units.
    # `spread_pips` is the normalized spread expressed in pips (preferred).
    spread: float | None = None,
    spread_pips: float | None = None,
    spread_points: float | None = None,
    minimum_rr: float = 2.0,
    maximum_spread_pips: float | None = None,
    maximum_spread_points: float | None = None,
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
    elif direction == "BUY" and stop_loss >= entry:
        reasons.append("BUY stop loss must be below the entry price.")
    elif direction == "SELL" and stop_loss <= entry:
        reasons.append("SELL stop loss must be above the entry price.")
    else:
        checks.append(f"Stop distance: {distance_to_sl:.6f}")

    rr = abs(take_profit - entry) / max(distance_to_sl, 1e-9)
    tolerance = 1e-9
    if rr < minimum_rr - tolerance:
        reasons.append(f"Reward-to-risk is below the minimum required ({minimum_rr:.2f}:1).")
    else:
        checks.append(f"Risk-reward OK: {rr:.2f}:1")

    if risk_percent <= 0:
        reasons.append("Risk percentage must be positive.")
    elif abs(float(risk_percent) - float(config.TRADING_RISK_PER_TRADE_PERCENT)) > 1e-9:
        reasons.append(f"Risk policy requires {config.TRADING_RISK_PER_TRADE_PERCENT:.2f}% per trade; received {float(risk_percent):.2f}%.")
    if risk_percent > config.TRADING_MAX_RISK_PERCENT:
        reasons.append(f"Risk percentage exceeds the configured maximum ({config.TRADING_MAX_RISK_PERCENT:.2f}%).")
    if risk_amount <= 0:
        reasons.append("Calculated risk amount must be positive.")
    if volume <= 0:
        reasons.append("Volume must be positive.")

    if free_margin_after < minimum_free_margin:
        reasons.append("Free margin after trade would violate the configured minimum margin.")
    else:
        checks.append("Free margin above minimum threshold.")

    margin_level = projected_margin_level if projected_margin_level is not None else current_margin_level
    if margin_level is not None and margin_level > 0 and margin_level < 100:
        reasons.append(f"Projected margin level is too low ({margin_level:.1f}%).")
    else:
        checks.append("Projected margin level remains acceptable.")

    # FX: enforce pips. Metals/other instruments: enforce MT5 points when
    # an explicit point threshold is provided. Never mix the units.
    is_metal = bool(symbol and any(token in str(symbol).upper() for token in ("XAU", "XAG", "XPT", "XPD", "GOLD", "SILVER")))
    if is_metal and spread_points is not None:
        max_points = float(maximum_spread_points or 0.0)
        if max_points > 0 and spread_points > max_points + 1e-9:
            reasons.append(f"Spread is too wide: {spread_points:.0f} MT5 points > maximum allowed {max_points:.0f} points.")
        else:
            checks.append(f"Spread OK: {spread_points:.0f} MT5 points (max {max_points:.0f}).")
    elif spread_pips is not None:
        try:
            max_allowed = float(
                maximum_spread_pips
                if maximum_spread_pips is not None
                else max_spread_for_symbol(symbol or "", None)
            )
        except Exception:
            max_allowed = 0.0
        if max_allowed > 0 and spread_pips > max_allowed + 1e-9:
            reasons.append(f"Spread is too wide: {spread_pips:.2f} pips > maximum allowed {max_allowed:.2f} pips.")
        else:
            checks.append(f"Spread OK: {spread_pips:.2f} pips (max {max_allowed:.2f}).")
    elif spread is not None and spread > 0:
        reasons.append("Spread could not be normalized into the unit required for this symbol.")

    valid = not reasons
    return {
        "valid": valid,
        "check_count": len(checks),
        "checks": checks,
        "reasons": reasons,
        "summary": "Trade safety checks passed." if valid else "Trade safety checks failed.",
    }
