from __future__ import annotations

from typing import Any
from core import config
from core.price_units import spread_policy, instrument_class


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
    spread_ticks: float | None = None,
    symbol_specs: dict[str, Any] | None = None,
    minimum_rr: float = 2.0,
    maximum_spread_pips: float | None = None,
    maximum_spread_points: float | None = None,
    maximum_spread_price: float | None = None,
    maximum_spread_unit: str | None = None,
    countertrend: bool = False,
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

    expected_risk = float(config.TRADING_RISK_PER_TRADE_PERCENT) * (0.5 if countertrend else 1.0)
    if risk_percent <= 0:
        reasons.append("Risk percentage must be positive.")
    elif abs(float(risk_percent) - expected_risk) > 1e-9:
        reasons.append(f"Risk policy requires {expected_risk:.2f}% for this setup; received {float(risk_percent):.2f}%.")
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

    # Spread is always gated in raw executable price units using the symbol's
    # broker metadata. Display units (pips, ticks, %) are informational.
    specs = dict(symbol_specs or {})
    policy = spread_policy(symbol or "", specs, specs.get("trading_mode", "DAY_TRADING"))
    current_price_spread = None
    if spread is not None:
        try:
            current_price_spread = abs(float(spread))
        except (TypeError, ValueError):
            current_price_spread = None
    max_price = None
    if maximum_spread_price is not None:
        try:
            max_price = float(maximum_spread_price)
        except (TypeError, ValueError):
            max_price = None
    if max_price is None:
        # Backward-compatible explicit unit limits used by tests/legacy callers.
        klass = instrument_class(symbol or "", specs)
        if maximum_spread_pips is not None and klass in {"FX_MAJOR", "FX_CROSS"}:
            from core.price_units import pip_size_from_specs
            pip = pip_size_from_specs(symbol or "", specs)
            if pip <= 0:
                pair = str(symbol or "").upper().replace("/", "")
                pip = 0.01 if pair.endswith("JPY") else 0.0001
            max_price = float(maximum_spread_pips) * pip
        elif maximum_spread_points is not None:
            point = float(specs.get("point", 0) or 0)
            if point > 0:
                max_price = float(maximum_spread_points) * point
        if max_price is None:
            max_price = float(policy.get("max_price", 0.0) or 0.0)

    if current_price_spread is None or current_price_spread <= 0:
        # Legacy callers may provide only a normalized spread value. Keep that
        # path valid for tests/manual validation, while production workflow
        # supplies the raw broker spread as the authoritative value.
        klass = instrument_class(symbol or "", specs)
        if klass in {"FX_MAJOR", "FX_CROSS"} and spread_pips is not None and maximum_spread_pips is not None:
            if float(spread_pips) > float(maximum_spread_pips) + 1e-9:
                reasons.append(f"Spread is too wide: {float(spread_pips):.2f} pips > maximum {float(maximum_spread_pips):.2f} pips.")
            else:
                checks.append(f"Spread OK: {float(spread_pips):.2f} pips (max {float(maximum_spread_pips):.2f}).")
        elif spread_points is not None and maximum_spread_points is not None:
            if float(spread_points) > float(maximum_spread_points) + 1e-9:
                reasons.append(f"Spread is too wide: {float(spread_points):.2f} points > maximum {float(maximum_spread_points):.2f} points.")
            else:
                checks.append(f"Spread OK: {float(spread_points):.2f} points (max {float(maximum_spread_points):.2f}).")
        else:
            reasons.append("Live spread is unavailable or invalid.")
    elif max_price <= 0:
        reasons.append("No valid symbol-specific maximum spread policy is available.")
    elif current_price_spread > max_price + 1e-12:
        shown_current = spread_pips if policy["max_unit"] == "pips" else spread_ticks if policy["max_unit"] == "ticks" else (current_price_spread / max((float(specs.get("bid", 0) or 0) + float(specs.get("ask", 0) or 0)) / 2.0, 1e-12) * 100 if policy["max_unit"] == "%" else current_price_spread)
        reasons.append(f"Spread is too wide: {float(shown_current):.2f} {policy['max_unit']} > maximum {float(policy['max_value']):.2f} {policy['max_unit']}.")
    else:
        shown_current = spread_pips if policy["max_unit"] == "pips" else spread_ticks if policy["max_unit"] == "ticks" else (current_price_spread / max((float(specs.get("bid", 0) or 0) + float(specs.get("ask", 0) or 0)) / 2.0, 1e-12) * 100 if policy["max_unit"] == "%" else current_price_spread)
        checks.append(f"Spread OK: {float(shown_current):.2f} {policy['max_unit']} (max {float(policy['max_value']):.2f}).")
    valid = not reasons
    return {
        "valid": valid,
        "check_count": len(checks),
        "checks": checks,
        "reasons": reasons,
        "summary": "Trade safety checks passed." if valid else "Trade safety checks failed.",
    }
