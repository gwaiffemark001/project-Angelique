from __future__ import annotations

from typing import Any
from core import config



def account_risk_percent(equity: float) -> float:
    """Return the maximum allowed risk per trade for the current account equity.

    Policy is intentionally simple and hard-capped:
      - below $50 equity: 0.50%
      - $50 or more: 1.00%
    """
    try:
        equity_value = float(equity)
    except (TypeError, ValueError):
        raise ValueError("Account equity must be numeric to determine risk tier.")
    if equity_value <= 0:
        raise ValueError("Account equity must be positive to determine risk tier.")
    tier = (
        config.TRADING_LOW_ACCOUNT_RISK_PERCENT
        if equity_value < config.TRADING_RISK_TIER_THRESHOLD_EQUITY
        else config.TRADING_HIGH_ACCOUNT_RISK_PERCENT
    )
    return min(max(tier, 0.0), config.TRADING_MAX_RISK_PERCENT)


def effective_risk_percent(equity: float, requested_risk_percent: float | None = None) -> float:
    """Resolve requested risk without ever exceeding the account's tier or 1% ceiling.

    A caller may request a lower risk, but never a higher risk than policy allows.
    """
    allowed = account_risk_percent(equity)
    if requested_risk_percent is None:
        return allowed
    try:
        requested = float(requested_risk_percent)
    except (TypeError, ValueError):
        raise ValueError("Risk percentage must be numeric.")
    if requested <= 0:
        raise ValueError("Risk percentage must be greater than 0.")
    return min(requested, allowed, config.TRADING_MAX_RISK_PERCENT)

def _canonical_symbol(symbol: Any) -> str:
    return "".join(character for character in str(symbol or "").upper() if character.isalnum())


def _same_symbol(left: Any, right: Any) -> bool:
    left_key = _canonical_symbol(left)
    right_key = _canonical_symbol(right)
    return bool(left_key and right_key and (left_key == right_key or left_key.startswith(right_key) or right_key.startswith(left_key)))


def validate_profile_limits(account: dict[str, Any], positions: list[dict[str, Any]], profile, new_risk_percent: float | None = None, symbol: str | None = None) -> dict[str, Any]:
    """Return hard portfolio-limit checks before a new plan is created."""
    reasons: list[str] = []
    position_count = len(positions)
    equity = float(account.get("equity", 0) or 0)
    planned_risk = effective_risk_percent(equity, new_risk_percent) if equity > 0 else profile.risk_per_trade
    if position_count >= profile.max_positions:
        reasons.append(f"Maximum positions reached ({position_count}/{profile.max_positions}).")

    same_symbol_positions = [
        position for position in positions
        if symbol and _same_symbol(position.get("symbol"), symbol)
    ]
    if same_symbol_positions:
        reasons.append(
            f"An open position already exists for {symbol}; another position for the same symbol is blocked until it is closed."
        )

    open_risk = sum(float(position.get("risk_percent", 0) or 0) for position in positions)
    if open_risk + planned_risk > profile.max_open_risk + 1e-9:
        reasons.append(
            f"Open risk would exceed {profile.max_open_risk:.2f}% "
            f"({open_risk:.2f}% existing + {planned_risk:.2f}% new)."
        )

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
        "position_count": position_count,
        "same_symbol_position_count": len(same_symbol_positions),
        "open_risk_percent": open_risk,
        "daily_loss_percent": daily_loss,
        "weekly_loss_percent": weekly_loss,
    }


def build_risk(entry: float, stop_loss: float, equity: float, risk_percent: float, symbol_specs: dict, free_margin: float = 0.0, used_margin: float = 0.0, minimum_free_margin: float = 0.0, current_margin_level: float = 0.0) -> dict:
    distance = abs(entry - stop_loss)
    if distance <= 0:
        raise ValueError("Stop loss must be based on a distinct invalidation price.")
    if equity <= 0:
        raise ValueError("Account equity is unavailable.")
    allowed_risk = effective_risk_percent(equity, risk_percent)
    if risk_percent <= 0 or risk_percent > allowed_risk + 1e-9:
        raise ValueError(
            f"Risk percentage {risk_percent:.2f}% exceeds the account risk policy of "
            f"{allowed_risk:.2f}% for equity ${equity:,.2f}."
        )
    tick_size = float(symbol_specs.get("tick_size", 0) or 0)
    tick_value = float(symbol_specs.get("tick_value", 0) or 0)
    step = float(symbol_specs.get("volume_step", 0) or 0)
    minimum = float(symbol_specs.get("volume_min", 0) or 0)
    maximum = float(symbol_specs.get("volume_max", 0) or 0)
    if min(tick_size, tick_value, step, minimum, maximum) <= 0:
        raise ValueError("MT5 symbol specifications are incomplete; volume cannot be calculated.")
    risk_amount = equity * risk_percent / 100
    raw_volume = risk_amount / ((distance / tick_size) * tick_value)
    if config.TRADING_MINIMUM_LOT_PROTECTION and raw_volume < minimum:
        raise ValueError(
            f"Broker minimum volume would exceed configured account risk (calculated {raw_volume:.8f}, minimum {minimum:.8f})."
        )
    volume = min(maximum, max(minimum, (raw_volume // step) * step))
    volume = round(volume, 8)
    actual_risk = (distance / tick_size) * tick_value * volume
    if actual_risk > risk_amount * (1 + 1e-8):
        raise ValueError(
            f"Volume step would exceed configured risk (${actual_risk:.2f} > ${risk_amount:.2f})."
        )
    margin_per_volume = float(symbol_specs.get("margin_per_volume", 0) or 0)
    if config.TRADING_MARGIN_PROTECTION and margin_per_volume <= 0:
        raise ValueError("MT5 margin requirement is unavailable; position safety cannot be verified.")
    margin_required = margin_per_volume * volume
    free_margin_after = free_margin - margin_required
    configured_minimum = max(
        float(minimum_free_margin or 0),
        equity * config.TRADING_MIN_FREE_MARGIN_PERCENT / 100,
    )
    if free_margin_after < configured_minimum:
        raise ValueError(f"Free margin after trade would be ${free_margin_after:,.2f}, below the configured minimum of ${configured_minimum:,.2f}.")
    projected_margin = used_margin + margin_required
    projected_margin_level = (equity / projected_margin * 100) if projected_margin > 0 else float("inf")
    if current_margin_level > 0 and projected_margin_level < 100:
        raise ValueError(f"Projected margin level would be {projected_margin_level:.1f}%, which is unsafe.")
    return {
        "distance": distance,
        "risk_amount": risk_amount,
        "calculated_volume": raw_volume,
        "volume": round(volume, 8),
        "actual_risk_amount": actual_risk,
        "minimum_free_margin": configured_minimum,
        "margin_required": margin_required,
        "free_margin_after": free_margin_after,
        "projected_margin_level": projected_margin_level,
    }
