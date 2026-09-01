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
    specs: dict[str, Any] | None = None,
    net_rr: float | None = None,
    spread_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hard safety checks that gate trading decisions before execution.

    Spread is gated in the instrument's own unit, decided by the broker's
    metadata rather than by matching substrings in the symbol name. When
    ``net_rr`` is supplied it is enforced in addition to the gross RR, because
    only the net figure reflects the trade's real economics.

    ``spread_gate`` is the authoritative result produced by
    :mod:`spread_model.evaluate_spread_gate`. When present it replaces the
    legacy hard-coded profile ceilings: it is based on live raw bid/ask,
    instrument class, the observed rolling distribution and the actual
    spread-to-stop / spread-to-reward economics of this specific trade.
    """
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
        reasons.append(f"Gross reward-to-risk {rr:.2f}:1 is below the minimum required ({minimum_rr:.2f}:1).")
    else:
        checks.append(f"Gross risk-reward OK: {rr:.2f}:1")
    if net_rr is not None:
        if float(net_rr) < minimum_rr - tolerance:
            reasons.append(
                f"NET reward-to-risk after spread, commission and swap is {float(net_rr):.2f}:1, "
                f"below the minimum {minimum_rr:.2f}:1 (gross was {rr:.2f}:1)."
            )
        else:
            checks.append(f"Net risk-reward OK after costs: {float(net_rr):.2f}:1 (gross {rr:.2f}:1).")
    else:
        checks.append("NOTE: only the gross RR was verified; net RR after costs was not supplied.")

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

    # The instrument's spread unit comes from broker metadata (trade_calc_mode
    # and the currency fields), not from the symbol string. An FX pip ceiling is
    # never applied to gold, crypto or an index.
    uses_pips = True
    instrument_class = "UNKNOWN"
    try:
        from .instruments import FX_CLASSES, build_profile
        instrument_profile = build_profile(symbol or "", specs or {})
        instrument_class = instrument_profile.instrument_class
        uses_pips = instrument_class in FX_CLASSES and instrument_profile.pip_size is not None
    except Exception:
        instrument_profile = None
    if spread_gate is not None:
        gate_allowed = bool(spread_gate.get("allowed", False))
        gate_reasons = list(spread_gate.get("reasons", []) or [])
        gate_checks = list(spread_gate.get("checks", []) or [])
        measurement = spread_gate.get("measurement", {}) or {}
        if not gate_allowed:
            reasons.extend(gate_reasons or ["Instrument-aware spread gate rejected the trade."])
        else:
            checks.append("Instrument-aware spread gate passed.")
        checks.extend(f"Spread gate: {line}" for line in gate_checks)
        # Keep the display fields accurate regardless of which engine decided.
        if "spread_pips" in measurement:
            spread_pips = measurement.get("spread_pips")
        if "spread_points" in measurement:
            spread_points = measurement.get("spread_points")
        if "spread_percent_of_price" in measurement:
            checks.append(f"Spread {measurement.get('spread_percent_of_price'):.3f}% of price.")
    elif not uses_pips and spread_points is not None:
        max_points = float(maximum_spread_points or 0.0)
        if max_points > 0 and spread_points > max_points + 1e-9:
            reasons.append(f"Spread is too wide for {instrument_class}: {spread_points:.0f} MT5 points "
                           f"> maximum allowed {max_points:.0f} points.")
        else:
            checks.append(f"Spread OK: {spread_points:.0f} MT5 points (max {max_points:.0f}, {instrument_class}).")
    elif not uses_pips:
        reasons.append(f"{symbol} is classified as {instrument_class}, which has no pip definition, "
                       "but no MT5-point spread was supplied. Spread cannot be validated.")
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
    else:
        reasons.append("No spread was supplied; execution cost cannot be verified.")

    valid = not reasons
    return {
        "valid": valid,
        "instrument_class": instrument_class,
        "spread_unit": "pips" if uses_pips else "points",
        "gross_rr": rr,
        "net_rr": net_rr,
        "check_count": len(checks),
        "checks": checks,
        "reasons": reasons,
        "spread_gate": spread_gate,
        "summary": "Trade safety checks passed." if valid else "Trade safety checks failed.",
    }
