from __future__ import annotations


def build_risk(entry: float, stop_loss: float, equity: float, risk_percent: float, symbol_specs: dict, free_margin: float = 0.0, used_margin: float = 0.0, minimum_free_margin: float = 0.0, current_margin_level: float = 0.0) -> dict:
    distance = abs(entry - stop_loss)
    if distance <= 0:
        raise ValueError("Stop loss must be based on a distinct invalidation price.")
    if equity <= 0:
        raise ValueError("Account equity is unavailable.")
    tick_size = float(symbol_specs.get("tick_size", 0) or 0)
    tick_value = float(symbol_specs.get("tick_value", 0) or 0)
    step = float(symbol_specs.get("volume_step", 0) or 0)
    minimum = float(symbol_specs.get("volume_min", 0) or 0)
    maximum = float(symbol_specs.get("volume_max", 0) or 0)
    if min(tick_size, tick_value, step, minimum, maximum) <= 0:
        raise ValueError("MT5 symbol specifications are incomplete; volume cannot be calculated.")
    risk_amount = equity * risk_percent / 100
    raw_volume = risk_amount / ((distance / tick_size) * tick_value)
    volume = min(maximum, max(minimum, (raw_volume // step) * step))
    margin_per_volume = float(symbol_specs.get("margin_per_volume", 0) or 0)
    if margin_per_volume <= 0:
        raise ValueError("MT5 margin requirement is unavailable; position safety cannot be verified.")
    margin_required = margin_per_volume * volume
    free_margin_after = free_margin - margin_required
    if free_margin_after < minimum_free_margin:
        raise ValueError(f"Free margin after trade would be ${free_margin_after:,.2f}, below the configured minimum.")
    projected_margin = used_margin + margin_required
    projected_margin_level = (equity / projected_margin * 100) if projected_margin > 0 else float("inf")
    if current_margin_level > 0 and projected_margin_level < 100:
        raise ValueError(f"Projected margin level would be {projected_margin_level:.1f}%, which is unsafe.")
    return {"distance": distance, "risk_amount": risk_amount, "volume": round(volume, 8), "margin_required": margin_required, "free_margin_after": free_margin_after, "projected_margin_level": projected_margin_level}
