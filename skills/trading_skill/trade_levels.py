from __future__ import annotations

from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _swing_points(structure: dict[str, Any], name: str, point_type: str) -> list[dict[str, Any]]:
    points = structure.get(name, []) if isinstance(structure, dict) else []
    out: list[dict[str, Any]] = []
    for item in points or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                out.append({"index": int(item[0]), "price": float(item[1]), "timestamp": None, "type": point_type, "valid": True, "strength": 2})
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
            row.update({"timestamp": item.get("timestamp"), "valid": item.get("valid", True), "strength": item.get("strength", 2), "timeframe": item.get("timeframe")})
    return [row for row in out if row.get("valid", True)]


def _structure_for(analysis: dict[str, Any], timeframe: str) -> dict[str, Any]:
    smc = analysis.get("smc", {}) or {}
    row = smc.get(timeframe, {}) or {}
    return row.get("structure", {}) or {}


def select_structural_swings(
    analysis: dict[str, Any],
    timeframe: str,
    direction: str,
    entry: float,
    strategy: str,
) -> dict[str, Any]:
    """Select validated swings from the canonical structure engine.

    The function deliberately does not calculate new swing points. It consumes
    the already-validated structure output and chooses the swing relevant to
    trade invalidation plus the next valid structural target.
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
        # Most recent confirmed swing low below the entry is the structural
        # invalidation reference. Prefer the latest point in time, not the
        # numerically lowest low.
        stop_idx, stop_price, stop_row = max(candidates, key=lambda item: item[0])
        target_candidates = [(row["index"], row["price"], row) for row in highs if row["price"] > entry and row["index"] > stop_idx]
        if not target_candidates:
            return {"valid": False, "reason": f"No valid swing high above BUY entry on {timeframe}."}
        # The target is the FIRST valid structural swing high after the
        # selected invalidation swing. "Next swing" is chronological market
        # structure, not the numerically closest higher price.
        target_idx, target_price, target_row = min(target_candidates, key=lambda item: item[0])
    else:
        candidates = [(row["index"], row["price"], row) for row in highs if row["price"] > entry]
        if not candidates:
            return {"valid": False, "reason": f"No valid swing high above SELL entry on {timeframe}."}
        stop_idx, stop_price, stop_row = max(candidates, key=lambda item: item[0])
        target_candidates = [(row["index"], row["price"], row) for row in lows if row["price"] < entry and row["index"] > stop_idx]
        if not target_candidates:
            return {"valid": False, "reason": f"No valid swing low below SELL entry on {timeframe}."}
        # The target is the FIRST valid structural swing low after the
        # selected invalidation swing. "Next swing" is chronological market
        # structure, not the numerically closest lower price.
        target_idx, target_price, target_row = min(target_candidates, key=lambda item: item[0])

    return {
        "valid": True,
        "direction": direction,
        "strategy": strategy,
        "timeframe": timeframe,
        "stop_swing": {"id": f"{timeframe}:SWING_{'LOW' if direction == 'BUY' else 'HIGH'}:{stop_idx}", "index": stop_idx, "price": stop_price, "timestamp": stop_row.get("timestamp"), "strength": stop_row.get("strength", 2), "timeframe": stop_row.get("timeframe") or timeframe},
        "target_swing": {"id": f"{timeframe}:SWING_{'HIGH' if direction == 'BUY' else 'LOW'}:{target_idx}", "index": target_idx, "price": target_price, "timestamp": target_row.get("timestamp"), "strength": target_row.get("strength", 2), "timeframe": target_row.get("timeframe") or timeframe},
    }


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
) -> dict[str, Any]:
    direction = direction.upper()
    strategy = str(strategy or "SMC").upper()
    _ = timeframes  # Structure is read from the canonical analysis object; candles remain an API input for traceability.

    setup_assessment = analysis.get("setup_assessment", {}) if isinstance(analysis.get("setup_assessment"), dict) else {}
    playbook = setup_assessment.get("supporting_evidence", {}).get("fvg_playbook", {}) if isinstance(setup_assessment.get("supporting_evidence"), dict) else {}
    selected_zone = setup_assessment.get("zone") if isinstance(setup_assessment.get("zone"), dict) else None
    setup_model = str(setup_assessment.get("model") or analysis.get("strategy_name") or strategy).upper()
    point = _as_float(specs.get("point"))
    tick_size = _as_float(specs.get("tick_size"))
    buffer = max(point * 2.0, tick_size) if max(point, tick_size) > 0 else 0.0

    # Exact guide execution models use the retest candle/sweep as the
    # invalidation reference and the next marked level as the target.
    if setup_model in {"FVG_RETRACEMENT", "IFVG_REVERSAL"} and selected_zone:
        low = _as_float(selected_zone.get("low")); high = _as_float(selected_zone.get("high"))
        retest = selected_zone.get("retest", {}) if isinstance(selected_zone.get("retest"), dict) else {}
        rc = retest.get("retest_candle") if isinstance(retest.get("retest_candle"), dict) else None
        if rc:
            if direction == "BUY":
                stop_loss = _as_float(rc.get("low")) - buffer
            else:
                stop_loss = _as_float(rc.get("high")) + buffer
        else:
            stop_loss = low - buffer if direction == "BUY" else high + buffer
        levels = []
        for key in ("target_liquidity",):
            target = analysis.get(key)
            if isinstance(target, dict) and target.get("price") is not None:
                levels.append(_as_float(target.get("price")))
        if isinstance(playbook, dict):
            cont = playbook.get("continuation") if isinstance(playbook.get("continuation"), dict) else None
            if cont and cont.get("target_reference") is not None:
                levels.append(_as_float(cont.get("target_reference")))
        # Prefer the first structurally valid target on the correct side.
        if direction == "BUY":
            candidate_targets = [x for x in levels if x > entry]
        else:
            candidate_targets = [x for x in levels if x < entry]
        if not candidate_targets:
            return {"valid": False, "reason": "FVG/IFVG setup has no marked target on the correct side of entry."}
        take_profit = candidate_targets[0]
        stop_distance = abs(entry - stop_loss); target_distance = abs(take_profit - entry)
        if stop_distance <= 0 or target_distance <= 0:
            return {"valid": False, "reason": "FVG/IFVG stop or target distance is non-positive."}
        rr = target_distance / stop_distance
        minimum_rr = max(2.0, _as_float(getattr(profile, "minimum_rr", 2.5), 2.5))
        if rr + 1e-9 < minimum_rr:
            return {"valid": False, "reason": f"FVG/IFVG target only provides RR {rr:.2f}, below minimum {minimum_rr:.2f}.", "rr": rr, "minimum_rr": minimum_rr}
        entry_plan = {"levels": selected_zone.get("entry_levels", {"edge": high if direction == "BUY" else low, "midpoint": (low+high)/2}), "allocation": [0.5, 0.5], "preferred": "midpoint"}
        return {
            "valid": True, "entry": entry, "stop_loss": stop_loss, "take_profit": take_profit,
            "stop_distance": stop_distance, "target_distance": target_distance, "rr": rr,
            "minimum_rr": minimum_rr, "stop_basis": "Beyond FVG/IFVG retest candle",
            "target_basis": "Next marked liquidity level", "stop_swing": {}, "target_swing": {},
            "stop_timeframe": getattr(profile, "entry_timeframe", "M5"), "target_timeframe": getattr(profile, "structure_timeframe", "M15"),
            "strategy": setup_model, "symbol": symbol, "entry_plan": entry_plan,
        }

    if setup_model == "SWEEP_CONTINUATION":
        cont = playbook.get("continuation") if isinstance(playbook, dict) else None
        if not cont:
            cont = analysis.get("continuation_playbook")
        if not isinstance(cont, dict):
            return {"valid": False, "reason": "Continuation setup has no sweep continuation evidence."}
        stop_ref = _as_float(cont.get("stop_reference"))
        target = _as_float(cont.get("target_reference"))
        stop_loss = stop_ref + buffer if direction == "SELL" else stop_ref - buffer
        if direction == "BUY" and target <= entry: return {"valid": False, "reason": "Continuation target is not above BUY entry."}
        if direction == "SELL" and target >= entry: return {"valid": False, "reason": "Continuation target is not below SELL entry."}
        stop_distance = abs(entry - stop_loss); target_distance = abs(target-entry)
        if stop_distance <= 0 or target_distance <= 0: return {"valid": False, "reason": "Continuation stop/target distance is non-positive."}
        rr = target_distance/stop_distance; minimum_rr=max(2.0,_as_float(getattr(profile,"minimum_rr",2.5),2.5))
        if rr + 1e-9 < minimum_rr: return {"valid": False, "reason": f"Continuation target only provides RR {rr:.2f}, below minimum {minimum_rr:.2f}."}
        return {"valid": True, "entry": entry, "stop_loss": stop_loss, "take_profit": target, "stop_distance": stop_distance, "target_distance": target_distance, "rr": rr, "minimum_rr": minimum_rr, "stop_basis": "Beyond sweep", "target_basis": "Next marked level", "stop_swing": {}, "target_swing": {}, "stop_timeframe": getattr(profile,"entry_timeframe","M5"), "target_timeframe": getattr(profile,"setup_timeframe","M15"), "strategy": setup_model, "symbol": symbol}

    selected_candidate = {}
    strategy_result = analysis.get("strategy", {}) if isinstance(analysis.get("strategy"), dict) else {}
    if isinstance(strategy_result.get("selected"), dict):
        selected_candidate = strategy_result.get("selected") or {}
    selected_meta = selected_candidate.get("metadata") if isinstance(selected_candidate.get("metadata"), dict) else {}

    # Strategy-specific levels for deterministic non-SMC playbooks. These are
    # still passed through the same RR and broker-safety gates below.
    if strategy == "BREAKOUT" and selected_meta.get("break_level") is not None and selected_candidate.get("target") is not None:
        break_level = _as_float(selected_meta.get("break_level"))
        take_profit = _as_float(selected_candidate.get("target"))
        stop_loss = break_level - buffer if direction == "BUY" else break_level + buffer
        if direction == "BUY" and take_profit <= entry:
            return {"valid": False, "reason": "Breakout target is not above BUY entry."}
        if direction == "SELL" and take_profit >= entry:
            return {"valid": False, "reason": "Breakout target is not below SELL entry."}
        stop_distance = abs(entry - stop_loss); target_distance = abs(take_profit - entry)
        if stop_distance <= 0 or target_distance <= 0:
            return {"valid": False, "reason": "Breakout stop/target distance is non-positive."}
        rr = target_distance / stop_distance
        minimum_rr = _as_float(getattr(profile, "minimum_rr", 2.5), 2.5)
        if rr + 1e-9 < minimum_rr:
            return {"valid": False, "reason": f"Breakout target only provides RR {rr:.2f}, below minimum {minimum_rr:.2f}."}
        return {"valid": True, "entry": entry, "stop_loss": stop_loss, "take_profit": take_profit, "stop_distance": stop_distance, "target_distance": target_distance, "rr": rr, "minimum_rr": minimum_rr, "stop_basis": "Back inside breakout range", "target_basis": "ATR-derived breakout target", "stop_swing": {}, "target_swing": {}, "stop_timeframe": getattr(profile, "entry_timeframe", "M5"), "target_timeframe": getattr(profile, "entry_timeframe", "M5"), "strategy": strategy, "symbol": symbol}

    if strategy == "MEAN_REVERSION" and selected_candidate.get("target") is not None:
        take_profit = _as_float(selected_candidate.get("target"))
        zone = selected_candidate.get("zone") if isinstance(selected_candidate.get("zone"), dict) else {}
        edge = _as_float(zone.get("low" if direction == "BUY" else "high"))
        stop_loss = edge - buffer if direction == "BUY" else edge + buffer
        if direction == "BUY" and take_profit <= entry:
            return {"valid": False, "reason": "Mean-reversion target is not above BUY entry."}
        if direction == "SELL" and take_profit >= entry:
            return {"valid": False, "reason": "Mean-reversion target is not below SELL entry."}
        stop_distance = abs(entry - stop_loss); target_distance = abs(take_profit - entry)
        if stop_distance <= 0 or target_distance <= 0:
            return {"valid": False, "reason": "Mean-reversion stop/target distance is non-positive."}
        rr = target_distance / stop_distance
        minimum_rr = _as_float(getattr(profile, "minimum_rr", 2.5), 2.5)
        if rr + 1e-9 < minimum_rr:
            return {"valid": False, "reason": f"Mean-reversion target only provides RR {rr:.2f}, below minimum {minimum_rr:.2f}."}
        return {"valid": True, "entry": entry, "stop_loss": stop_loss, "take_profit": take_profit, "stop_distance": stop_distance, "target_distance": target_distance, "rr": rr, "minimum_rr": minimum_rr, "stop_basis": "Beyond Bollinger extreme", "target_basis": "Bollinger mean target", "stop_swing": {}, "target_swing": {}, "stop_timeframe": getattr(profile, "entry_timeframe", "M5"), "target_timeframe": getattr(profile, "entry_timeframe", "M5"), "strategy": strategy, "symbol": symbol}

    structure_tf = str(getattr(profile, "structure_timeframe", "M15"))
    selected = select_structural_swings(analysis, structure_tf, direction, entry, strategy)
    if not selected.get("valid"):
        return selected

    stop_swing = selected["stop_swing"]
    target_swing = selected["target_swing"]

    if direction == "BUY":
        stop_loss = stop_swing["price"] - buffer
        take_profit = target_swing["price"]
    else:
        stop_loss = stop_swing["price"] + buffer
        take_profit = target_swing["price"]

    stop_distance = abs(entry - stop_loss)
    target_distance = abs(take_profit - entry)
    if stop_distance <= 0 or target_distance <= 0:
        return {"valid": False, "reason": "Structural stop/target produced a non-positive distance."}

    rr = target_distance / stop_distance
    minimum_rr = _as_float(getattr(profile, "minimum_rr", 2.5), 2.5)
    if rr + 1e-9 < minimum_rr:
        return {
            "valid": False,
            "reason": f"Next valid structural target only provides RR {rr:.2f}, below minimum {minimum_rr:.2f}.",
            "rr": rr,
            "minimum_rr": minimum_rr,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "stop_basis": f"Below {structure_tf} swing low" if direction == "BUY" else f"Above {structure_tf} swing high",
            "target_basis": f"Next valid {structure_tf} swing high" if direction == "BUY" else f"Next valid {structure_tf} swing low",
            "stop_swing": stop_swing,
            "target_swing": target_swing,
        }

    return {
        "valid": True,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "stop_distance": stop_distance,
        "target_distance": target_distance,
        "rr": rr,
        "minimum_rr": minimum_rr,
        "stop_basis": f"Below {structure_tf} swing low + broker buffer" if direction == "BUY" else f"Above {structure_tf} swing high + broker buffer",
        "target_basis": f"Next valid {structure_tf} swing high / upside liquidity" if direction == "BUY" else f"Next valid {structure_tf} swing low / downside liquidity",
        "stop_swing": stop_swing,
        "target_swing": target_swing,
        "stop_timeframe": structure_tf,
        "target_timeframe": structure_tf,
        "strategy": strategy,
        "symbol": symbol,
    }
