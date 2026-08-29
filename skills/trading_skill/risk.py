from __future__ import annotations

from typing import Any, Callable
from core import config
from .correlation_manager import evaluate_portfolio


def account_risk_percent(equity: float) -> float:
    """Return the canonical 1% target risk for any positive account equity."""
    try:
        equity_value = float(equity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Account equity must be numeric to determine risk budget.") from exc
    if equity_value <= 0:
        raise ValueError("Account equity must be positive to determine risk budget.")
    return float(config.TRADING_RISK_PER_TRADE_PERCENT)


def effective_risk_percent(equity: float, requested_risk_percent: float | None = None) -> float:
    """Enforce the single 1% target; never silently downgrade or upgrade it."""
    allowed = account_risk_percent(equity)
    if requested_risk_percent is None:
        return allowed
    try:
        requested = float(requested_risk_percent)
    except (TypeError, ValueError) as exc:
        raise ValueError("Risk percentage must be numeric.") from exc
    if abs(requested - allowed) > 1e-9:
        raise ValueError(f"Risk policy requires exactly {allowed:.2f}% target risk; requested {requested:.2f}% is not permitted.")
    return allowed


def _canonical_symbol(symbol: Any) -> str:
    return "".join(character for character in str(symbol or "").upper() if character.isalnum())


def _same_symbol(left: Any, right: Any) -> bool:
    left_key = _canonical_symbol(left)
    right_key = _canonical_symbol(right)
    return bool(left_key and right_key and (left_key == right_key or left_key.startswith(right_key) or right_key.startswith(left_key)))


def validate_profile_limits(
    account: dict[str, Any],
    positions: list[dict[str, Any]],
    profile,
    new_risk_percent: float | None = None,
    symbol: str | None = None,
    direction: str = "BUY",
) -> dict[str, Any]:
    """Validate position count, 1% risk policy, loss limits and portfolio exposure."""
    reasons: list[str] = []
    try:
        equity = float(account.get("equity", 0) or 0)
        planned_risk = effective_risk_percent(equity, config.TRADING_RISK_PER_TRADE_PERCENT if new_risk_percent is None else new_risk_percent) if equity > 0 else None
    except ValueError as exc:
        return {"valid": False, "reasons": [str(exc)], "position_count": len(positions), "same_symbol_position_count": 0, "open_risk_percent": 0.0}

    if len(positions) >= profile.max_positions:
        reasons.append(f"Maximum positions reached ({len(positions)}/{profile.max_positions}).")

    same_symbol_positions = [p for p in positions if symbol and _same_symbol(p.get("symbol"), symbol)]
    if same_symbol_positions:
        reasons.append(f"An open position already exists for {symbol}; another position for the same symbol is blocked until it is closed.")

    portfolio = evaluate_portfolio(
        symbol or "",
        direction,
        planned_risk or config.TRADING_RISK_PER_TRADE_PERCENT,
        positions,
        max_positions=profile.max_positions,
        max_open_risk=profile.max_open_risk,
        strict_shared_currency=getattr(config, "TRADING_STRICT_SHARED_CURRENCY_BLOCK", True),
    )
    for reason in portfolio["reasons"]:
        if reason not in reasons:
            reasons.append(reason)

    daily_raw = account.get("daily_loss_percent")
    weekly_raw = account.get("weekly_loss_percent")
    if daily_raw is None or weekly_raw is None:
        reasons.append("Daily/weekly realized-loss metrics are unavailable; risk checks cannot be completed.")
    daily_loss = float(daily_raw) if daily_raw is not None else float("inf")
    weekly_loss = float(weekly_raw) if weekly_raw is not None else float("inf")
    if daily_loss >= profile.max_daily_loss:
        reasons.append(f"Daily loss limit reached ({daily_loss:.2f}%/{profile.max_daily_loss:.2f}%).")
    if weekly_loss >= profile.max_weekly_loss:
        reasons.append(f"Weekly loss limit reached ({weekly_loss:.2f}%/{profile.max_weekly_loss:.2f}%).")

    return {
        "valid": not reasons,
        "reasons": reasons,
        "position_count": len(positions),
        "same_symbol_position_count": len(same_symbol_positions),
        "open_risk_percent": portfolio["known_open_risk_percent"],
        "unknown_risk_positions": portfolio["unknown_risk_positions"],
        "candidate_risk_percent": planned_risk,
        "daily_loss_percent": daily_loss,
        "weekly_loss_percent": weekly_loss,
        "correlation": portfolio,
    }


def build_risk(
    entry: float,
    stop_loss: float,
    equity: float,
    risk_percent: float,
    symbol_specs: dict,
    free_margin: float = 0.0,
    used_margin: float = 0.0,
    minimum_free_margin: float = 0.0,
    current_margin_level: float = 0.0,
    *,
    loss_per_lot: float | None = None,
    profit_per_lot_at_tp: float | None = None,
) -> dict:
    distance = abs(entry - stop_loss)
    if distance <= 0:
        raise ValueError("Stop loss must be based on a distinct invalidation price.")
    if equity <= 0:
        raise ValueError("Account equity is unavailable.")
    risk_percent = effective_risk_percent(equity, risk_percent)

    tick_size = float(symbol_specs.get("tick_size", 0) or 0)
    tick_value = float(symbol_specs.get("tick_value", 0) or 0)
    step = float(symbol_specs.get("volume_step", 0) or 0)
    minimum = float(symbol_specs.get("volume_min", 0) or 0)
    maximum = float(symbol_specs.get("volume_max", 0) or 0)
    if min(step, minimum, maximum) <= 0:
        raise ValueError("MT5 volume specifications are incomplete; volume cannot be calculated.")
    if loss_per_lot is None:
        if min(tick_size, tick_value) <= 0:
            raise ValueError("Broker-calculated P/L is unavailable and tick specifications are incomplete.")
        loss_per_lot = (distance / tick_size) * tick_value
    loss_per_lot = abs(float(loss_per_lot))
    if loss_per_lot <= 0:
        raise ValueError("Unable to calculate monetary loss at stop loss.")

    risk_amount = equity * config.TRADING_RISK_PER_TRADE_PERCENT / 100
    raw_volume = risk_amount / loss_per_lot
    if config.TRADING_MINIMUM_LOT_PROTECTION and raw_volume < minimum:
        raise ValueError(f"Broker minimum volume would exceed the 1% risk ceiling (ideal volume {raw_volume:.8f}, minimum {minimum:.8f}).")

    # Always round DOWN to the broker's step to protect the risk ceiling.
    steps = int(raw_volume / step + 1e-12)
    volume = min(maximum, steps * step)
    volume = round(volume, 8)
    if volume < minimum:
        raise ValueError("Normalized volume is below the broker minimum; trade rejected to protect the 1% risk ceiling.")

    actual_risk = loss_per_lot * volume
    actual_risk_percent = actual_risk / equity * 100
    if actual_risk_percent > config.TRADING_MAX_RISK_PERCENT + 1e-9:
        raise ValueError(f"Normalized volume would exceed the 1% risk ceiling ({actual_risk_percent:.4f}%).")

    margin_per_volume = float(symbol_specs.get("margin_per_volume", 0) or 0)
    if config.TRADING_MARGIN_PROTECTION and margin_per_volume <= 0:
        raise ValueError("MT5 margin requirement is unavailable; position safety cannot be verified.")
    margin_required = margin_per_volume * volume
    free_margin_after = free_margin - margin_required
    configured_minimum = max(float(minimum_free_margin or 0), equity * config.TRADING_MIN_FREE_MARGIN_PERCENT / 100)
    if free_margin_after < configured_minimum:
        raise ValueError(f"Free margin after trade would be ${free_margin_after:,.2f}, below the configured minimum of ${configured_minimum:,.2f}.")
    projected_margin = used_margin + margin_required
    projected_margin_level = equity / projected_margin * 100 if projected_margin > 0 else float("inf")
    if current_margin_level > 0 and projected_margin_level < 100:
        raise ValueError(f"Projected margin level would be {projected_margin_level:.1f}%, which is unsafe.")

    return {
        "distance": distance,
        "risk_amount": risk_amount,
        "calculated_volume": raw_volume,
        "volume": volume,
        "actual_risk_amount": actual_risk,
        "actual_risk_percent": actual_risk_percent,
        "loss_per_lot": loss_per_lot,
        "expected_profit_at_tp": (abs(float(profit_per_lot_at_tp)) * volume if profit_per_lot_at_tp is not None else None),
        "minimum_free_margin": configured_minimum,
        "margin_required": margin_required,
        "free_margin_after": free_margin_after,
        "projected_margin_level": projected_margin_level,
    }
