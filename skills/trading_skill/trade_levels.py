"""Trade level construction, validated against the broker's own constraints.

Two classes of problem are fixed here.

**Structural.** Stops and targets come from the strategy's own plan context
where it defines one (breakout measured move, mean-reversion mean, AMD
manipulation extreme, SMC zone invalidation). A strategy that says "my target
is the measured move" must not have a different target silently substituted by
a generic swing scan.

**Broker-mechanical.** Every price is rounded to ``tick_size`` and ``digits``,
and validated against ``stops_level`` and ``freeze_level`` relative to the
correct side of the book: a BUY stop is compared against Bid, a BUY entry
against Ask. Violating ``stops_level`` produces MT5 retcode 10016 "Invalid
Stops"; catching it here rather than at the server is the whole point.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .instruments import InstrumentProfile, build_profile

#: Extra safety margin applied on top of the broker's raw minimum distance.
#: Brokers can widen stops_level intra-session; sitting exactly on the limit
#: gets orders rejected. POLICY, configurable.
STOPS_LEVEL_BUFFER_MULTIPLE = 1.5


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Structural swing selection (unchanged public contract)
# --------------------------------------------------------------------------
def _swing_points(structure: dict[str, Any], name: str, point_type: str) -> list[dict[str, Any]]:
    points = structure.get(name, []) if isinstance(structure, dict) else []
    out: list[dict[str, Any]] = []
    for item in points or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                out.append({"index": int(item[0]), "price": float(item[1]), "timestamp": None,
                            "type": point_type, "valid": True, "strength": 2})
            except (TypeError, ValueError):
                continue
    structural_points = structure.get("structural_points", []) if isinstance(structure, dict) else []
    metadata = {
        (int(item.get("index")), item.get("type")): item
        for item in structural_points
        if isinstance(item, dict) and item.get("index") is not None
    }
    for row in out:
        item = metadata.get((row["index"], point_type))
        if item:
            row.update({"timestamp": item.get("timestamp"), "valid": item.get("valid", True),
                        "strength": item.get("strength", 2), "timeframe": item.get("timeframe")})
    return [row for row in out if row.get("valid", True)]


def _structure_for(analysis: dict[str, Any], timeframe: str) -> dict[str, Any]:
    smc = analysis.get("smc", {}) or {}
    row = smc.get(timeframe, {}) or {}
    return row.get("structure", {}) or row.get("market_structure", {}) or {}


def select_structural_swings(
    analysis: dict[str, Any],
    timeframe: str,
    direction: str,
    entry: float,
    strategy: str,
) -> dict[str, Any]:
    """Select validated swings from the canonical structure engine.

    Does not calculate new swings. Consumes the already-validated structure
    output and chooses the swing relevant to trade invalidation plus the next
    valid structural target (chronologically next, not nearest in price).
    """
    structure = _structure_for(analysis, timeframe)
    highs = _swing_points(structure, "swing_highs", "swing_high")
    lows = _swing_points(structure, "swing_lows", "swing_low")
    if not highs and not lows:
        return {"valid": False, "reason": f"No validated swings available on {timeframe}."}

    direction = direction.upper()
    if direction == "BUY":
        candidates = [(row["index"], row["price"], row) for row in lows if row["price"] < entry]
        if not candidates:
            return {"valid": False, "reason": f"No valid swing low below BUY entry on {timeframe}."}
        stop_idx, stop_price, stop_row = max(candidates, key=lambda item: item[0])
        target_candidates = [(row["index"], row["price"], row) for row in highs
                             if row["price"] > entry and row["index"] > stop_idx]
        if not target_candidates:
            return {"valid": False, "reason": f"No valid swing high above BUY entry on {timeframe}."}
        target_idx, target_price, target_row = min(target_candidates, key=lambda item: item[0])
    else:
        candidates = [(row["index"], row["price"], row) for row in highs if row["price"] > entry]
        if not candidates:
            return {"valid": False, "reason": f"No valid swing high above SELL entry on {timeframe}."}
        stop_idx, stop_price, stop_row = max(candidates, key=lambda item: item[0])
        target_candidates = [(row["index"], row["price"], row) for row in lows
                             if row["price"] < entry and row["index"] > stop_idx]
        if not target_candidates:
            return {"valid": False, "reason": f"No valid swing low below SELL entry on {timeframe}."}
        target_idx, target_price, target_row = min(target_candidates, key=lambda item: item[0])

    return {
        "valid": True, "direction": direction, "strategy": strategy, "timeframe": timeframe,
        "stop_swing": {
            "id": f"{timeframe}:SWING_{'LOW' if direction == 'BUY' else 'HIGH'}:{stop_idx}",
            "index": stop_idx, "price": stop_price, "timestamp": stop_row.get("timestamp"),
            "strength": stop_row.get("strength", 2), "timeframe": stop_row.get("timeframe") or timeframe,
        },
        "target_swing": {
            "id": f"{timeframe}:SWING_{'HIGH' if direction == 'BUY' else 'LOW'}:{target_idx}",
            "index": target_idx, "price": target_price, "timestamp": target_row.get("timestamp"),
            "strength": target_row.get("strength", 2), "timeframe": target_row.get("timeframe") or timeframe,
        },
    }


# --------------------------------------------------------------------------
# Broker constraint validation
# --------------------------------------------------------------------------
@dataclass
class LevelValidation:
    valid: bool
    entry: float
    stop_loss: float
    take_profit: float
    checks: list[str]
    violations: list[str]
    blocker: str | None
    detail: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_levels_against_broker(
    profile: InstrumentProfile,
    *,
    direction: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    bid: float | None = None,
    ask: float | None = None,
    buffer_multiple: float = STOPS_LEVEL_BUFFER_MULTIPLE,
    is_pending: bool = False,
) -> LevelValidation:
    """Round to the broker grid and enforce stops_level / freeze_level.

    Reference-price rules (MT5):
      * A BUY position's SL/TP are evaluated against **Bid** (the price that
        would close it); the entry of a market BUY executes at **Ask**.
      * A SELL position's SL/TP are evaluated against **Ask**; the entry of a
        market SELL executes at **Bid**.
    """
    direction = str(direction).upper()
    checks: list[str] = []
    violations: list[str] = []
    blocker: str | None = None

    if profile.tick_size <= 0 or profile.point <= 0:
        return LevelValidation(
            False, entry, stop_loss, take_profit, checks,
            ["Broker price grid (tick_size / point) is unavailable; levels cannot be validated."],
            "BROKER_METADATA_INCOMPLETE",
            {"missing_metadata": list(profile.missing_metadata)},
        )

    entry_r = profile.normalize_price(entry)
    stop_r = profile.normalize_price(stop_loss)
    target_r = profile.normalize_price(take_profit)
    for label, original, rounded in (("entry", entry, entry_r), ("stop_loss", stop_loss, stop_r),
                                     ("take_profit", take_profit, target_r)):
        if abs(original - rounded) > 1e-12:
            checks.append(f"{label} rounded {original:.10g} -> {rounded:.10g} onto the "
                          f"{profile.tick_size:.10g} tick grid ({profile.digits} digits).")

    # Reference prices.
    bid_value = _as_float(bid, 0.0) or None
    ask_value = _as_float(ask, 0.0) or None
    reference_assumed = False
    if bid_value is None or ask_value is None:
        # Planning context: fall back to the entry price and say so loudly.
        # Execution is separately gated in execution_preflight, which REQUIRES
        # live bid/ask and will not accept an assumed reference.
        reference_assumed = True
        sl_reference = tp_reference = entry_r
        checks.append(
            "WARNING: live bid/ask unavailable, so stops_level was validated against the entry price. "
            "Execution preflight requires real Bid/Ask and will re-run this check."
        )
    else:
        sl_reference = tp_reference = bid_value if direction == "BUY" else ask_value
        checks.append(
            f"{direction} SL/TP validated against {'Bid' if direction == 'BUY' else 'Ask'} "
            f"= {sl_reference:.10g}; entry executes at "
            f"{'Ask' if direction == 'BUY' else 'Bid'} = {(ask_value if direction == 'BUY' else bid_value):.10g}."
        )

    minimum = profile.stops_level_price * max(1.0, float(buffer_multiple))
    freeze = profile.freeze_level_price
    detail: dict[str, Any] = {
        "stops_level_points": profile.stops_level_points,
        "stops_level_price": profile.stops_level_price,
        "required_distance_with_buffer": minimum,
        "buffer_multiple": buffer_multiple,
        "freeze_level_points": profile.freeze_level_points,
        "freeze_level_price": freeze,
        "tick_size": profile.tick_size,
        "digits": profile.digits,
        "sl_reference_price": sl_reference,
        "sl_reference_side": "bid" if direction == "BUY" else "ask",
        "reference_price_assumed": reference_assumed,
    }

    # Directional sanity first -- an inverted stop is not a distance problem.
    if direction == "BUY":
        if stop_r >= entry_r:
            violations.append(f"BUY stop loss {stop_r:.10g} is not below the entry {entry_r:.10g}.")
        if target_r <= entry_r:
            violations.append(f"BUY take profit {target_r:.10g} is not above the entry {entry_r:.10g}.")
    else:
        if stop_r <= entry_r:
            violations.append(f"SELL stop loss {stop_r:.10g} is not above the entry {entry_r:.10g}.")
        if target_r >= entry_r:
            violations.append(f"SELL take profit {target_r:.10g} is not below the entry {entry_r:.10g}.")

    if minimum > 0 and not violations:
        sl_distance = abs(sl_reference - stop_r)
        tp_distance = abs(tp_reference - target_r)
        detail["stop_distance_from_reference"] = sl_distance
        detail["target_distance_from_reference"] = tp_distance
        if sl_distance < minimum:
            violations.append(
                f"Stop loss is {profile.format_distance(sl_distance)} from the reference price but the "
                f"broker requires at least {profile.format_distance(profile.stops_level_price)} "
                f"(using a {buffer_multiple}x safety buffer = {profile.format_distance(minimum)}). "
                "MT5 would reject this with retcode 10016 (Invalid Stops)."
            )
            blocker = blocker or "STOPS_LEVEL_VIOLATION"
        else:
            checks.append(f"Stop loss is {profile.format_distance(sl_distance)} from the reference price "
                          f"(minimum {profile.format_distance(minimum)}).")
        if tp_distance < minimum:
            violations.append(
                f"Take profit is {profile.format_distance(tp_distance)} from the reference price; the broker "
                f"minimum with buffer is {profile.format_distance(minimum)}."
            )
            blocker = blocker or "STOPS_LEVEL_VIOLATION"
        else:
            checks.append(f"Take profit is {profile.format_distance(tp_distance)} from the reference price.")
    elif minimum <= 0:
        checks.append("Broker reports stops_level = 0 (no minimum stop distance).")

    if is_pending and bid_value and ask_value and minimum > 0:
        pending_reference = bid_value if direction == "BUY" else ask_value
        pending_distance = abs(pending_reference - entry_r)
        detail["pending_entry_distance"] = pending_distance
        if pending_distance < minimum:
            violations.append(
                f"Pending order entry is only {profile.format_distance(pending_distance)} from the market; "
                f"the broker requires {profile.format_distance(minimum)}."
            )
            blocker = blocker or "STOPS_LEVEL_VIOLATION"

    if freeze > 0 and bid_value and ask_value:
        detail["freeze_zone"] = freeze
        if abs(sl_reference - stop_r) < freeze or abs(tp_reference - target_r) < freeze:
            checks.append(
                f"WARNING: SL/TP sit inside the {profile.format_distance(freeze)} freeze level; the broker "
                "will reject modification or removal while price stays this close."
            )

    return LevelValidation(
        valid=not violations, entry=entry_r, stop_loss=stop_r, take_profit=target_r,
        checks=checks, violations=violations,
        blocker=blocker if violations else None, detail=detail,
    )


# --------------------------------------------------------------------------
# Level construction
# --------------------------------------------------------------------------
def calculate_trade_levels(
    *,
    symbol: str,
    direction: str,
    strategy: str,
    analysis: dict[str, Any],
    timeframes: dict[str, list[dict[str, Any]]],
    specs: dict[str, Any],
    profile: Any,
    entry: float,
    bid: float | None = None,
    ask: float | None = None,
    plan_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build stop/target from strategy intent, then validate against the broker.

    ``plan_context`` is the selected strategy's own ``plan_context``. When it
    defines a target (breakout measured move, mean-reversion mean, SMC target
    liquidity) that level is used, so the executed plan matches the plan that
    was scored.
    """
    direction = direction.upper()
    strategy = str(strategy or "SMC").upper()
    _ = timeframes  # candles remain an input for traceability
    structure_tf = str(getattr(profile, "structure_timeframe", "M15"))
    instrument = build_profile(symbol, specs)
    plan_context = plan_context or {}

    selected = select_structural_swings(analysis, structure_tf, direction, entry, strategy)
    if not selected.get("valid"):
        return selected

    point = _as_float(specs.get("point"))
    tick_size = _as_float(specs.get("tick_size"))
    buffer = max(point * 2.0, tick_size) if max(point, tick_size) > 0 else 0.0
    stop_swing = selected["stop_swing"]
    target_swing = selected["target_swing"]

    # -- stop: strategy intent first, structural swing as the default --------
    strategy_stop = plan_context.get("stop_reference")
    if isinstance(strategy_stop, (int, float)) and strategy_stop:
        stop_loss = float(strategy_stop) - buffer if direction == "BUY" else float(strategy_stop) + buffer
        stop_basis = plan_context.get("stop_basis") or f"{strategy} strategy invalidation level + broker buffer"
    else:
        stop_loss = stop_swing["price"] - buffer if direction == "BUY" else stop_swing["price"] + buffer
        stop_basis = (f"Below {structure_tf} swing low + broker buffer" if direction == "BUY"
                      else f"Above {structure_tf} swing high + broker buffer")

    # -- target: strategy intent first ---------------------------------------
    strategy_target = plan_context.get("target")
    if isinstance(strategy_target, (int, float)) and strategy_target:
        take_profit = float(strategy_target)
        target_basis = plan_context.get("target_basis") or f"{strategy} strategy target"
    else:
        take_profit = target_swing["price"]
        target_basis = (f"Next valid {structure_tf} swing high / upside liquidity" if direction == "BUY"
                        else f"Next valid {structure_tf} swing low / downside liquidity")

    # -- direction sanity before any RR arithmetic ---------------------------
    if direction == "BUY" and not (stop_loss < entry < take_profit):
        return {"valid": False, "reason": f"BUY levels are not ordered stop < entry < target "
                                          f"({stop_loss:.10g} / {entry:.10g} / {take_profit:.10g}).",
                "stop_loss": stop_loss, "take_profit": take_profit,
                "stop_swing": stop_swing, "target_swing": target_swing}
    if direction == "SELL" and not (take_profit < entry < stop_loss):
        return {"valid": False, "reason": f"SELL levels are not ordered target < entry < stop "
                                          f"({take_profit:.10g} / {entry:.10g} / {stop_loss:.10g}).",
                "stop_loss": stop_loss, "take_profit": take_profit,
                "stop_swing": stop_swing, "target_swing": target_swing}

    validation = validate_levels_against_broker(
        instrument, direction=direction, entry=entry, stop_loss=stop_loss,
        take_profit=take_profit, bid=bid, ask=ask,
    )
    stop_loss, take_profit, entry = validation.stop_loss, validation.take_profit, validation.entry

    stop_distance = abs(entry - stop_loss)
    target_distance = abs(take_profit - entry)
    if stop_distance <= 0 or target_distance <= 0:
        return {"valid": False, "reason": "Structural stop/target produced a non-positive distance.",
                "broker_validation": validation.as_dict()}

    rr = target_distance / stop_distance
    minimum_rr = _as_float(getattr(profile, "minimum_rr", 2.5), 2.5)

    common = {
        "entry": entry, "stop_loss": stop_loss, "take_profit": take_profit,
        "stop_distance": stop_distance, "target_distance": target_distance,
        "rr": rr, "gross_rr": rr, "minimum_rr": minimum_rr,
        "stop_basis": stop_basis, "target_basis": target_basis,
        "stop_swing": stop_swing, "target_swing": target_swing,
        "stop_timeframe": structure_tf, "target_timeframe": structure_tf,
        "strategy": strategy, "symbol": symbol,
        "stop_distance_display": instrument.describe_distance(stop_distance),
        "target_distance_display": instrument.describe_distance(target_distance),
        "instrument_class": instrument.instrument_class,
        "broker_validation": validation.as_dict(),
    }

    if not validation.valid:
        return {**common, "valid": False,
                "reason": "; ".join(validation.violations),
                "blocker": validation.blocker}
    if rr + 1e-9 < minimum_rr:
        return {**common, "valid": False,
                "reason": f"{target_basis} only provides RR {rr:.2f}, below minimum {minimum_rr:.2f}. "
                          "Note: this is the GROSS RR; net RR after spread and commission is lower."}
    return {**common, "valid": True}
