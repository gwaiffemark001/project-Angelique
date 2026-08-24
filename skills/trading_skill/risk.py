from __future__ import annotations

from typing import Any
from core import config


def validate_profile_limits(account: dict[str, Any], positions: list[dict[str, Any]], profile) -> dict[str, Any]:
    """Return hard portfolio-limit checks before a new plan is created."""
    reasons: list[str] = []
    position_count = len(positions)
    if position_count >= profile.max_positions:
        reasons.append(f"Maximum positions reached ({position_count}/{profile.max_positions}).")

    open_risk = sum(float(position.get("risk_percent", 0) or 0) for position in positions)
    if open_risk + profile.risk_per_trade > profile.max_open_risk + 1e-9:
        reasons.append(
            f"Open risk would exceed {profile.max_open_risk:.2f}% "
            f"({open_risk:.2f}% existing + {profile.risk_per_trade:.2f}% new)."
        )

    daily_loss = float(account.get("daily_loss_percent", 0) or 0)
    weekly_loss = float(account.get("weekly_loss_percent", 0) or 0)
    if daily_loss >= profile.max_daily_loss:
        reasons.append(f"Daily loss limit reached ({daily_loss:.2f}%/{profile.max_daily_loss:.2f}%).")
    if weekly_loss >= profile.max_weekly_loss:
        reasons.append(f"Weekly loss limit reached ({weekly_loss:.2f}%/{profile.max_weekly_loss:.2f}%).")

    return {
        "valid": not reasons,
        "reasons": reasons,
        "position_count": position_count,
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
    if risk_percent <= 0 or risk_percent > config.TRADING_MAX_RISK_PERCENT:
        raise ValueError(
            f"Risk percentage must be between 0 and {config.TRADING_MAX_RISK_PERCENT:.2f}%."
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
