"""Deterministic Fair Value Gap playbook.

Implements the guide's execution flow:

break/sweep -> displacement + swing-breaking FVG -> retest/hold -> entry,
with 50% consequent encroachment, stale pending expiry, IFVG inversion,
and a continuation fallback when no reaction/FVG forms.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, time
from typing import Any
from zoneinfo import ZoneInfo


NY = ZoneInfo("America/New_York")


def _f(c: dict[str, Any], k: str) -> float:
    try:
        return float(c.get(k, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _ts(c: dict[str, Any]) -> datetime | None:
    raw = c.get("time") or c.get("timestamp")
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _closed(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return candles[:-1] if candles and candles[-1].get("closed") is False else list(candles)


def _swings(candles: list[dict[str, Any]], strength: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for i in range(strength, len(candles) - strength):
        w = candles[i-strength:i+strength+1]
        h, l = _f(candles[i], "high"), _f(candles[i], "low")
        if h >= max(_f(x, "high") for x in w):
            highs.append((i, h))
        if l <= min(_f(x, "low") for x in w):
            lows.append((i, l))
    return highs, lows


def _atr(candles: list[dict[str, Any]], period: int = 14) -> float:
    values = []
    for c in candles[-max(period, 2):]:
        values.append(max(0.0, _f(c, "high") - _f(c, "low")))
    return sum(values) / max(1, len(values))


def _chop_status(candles: list[dict[str, Any]], lookback: int = 12) -> dict[str, Any]:
    vals = candles[-lookback:]
    if len(vals) < 6:
        return {"is_chop": True, "efficiency": 0.0, "reason": "insufficient_context"}
    closes = [_f(c, "close") for c in vals]
    net = abs(closes[-1] - closes[0])
    path = sum(abs(closes[i] - closes[i-1]) for i in range(1, len(closes)))
    efficiency = net / path if path > 0 else 0.0
    avg_range = sum(max(0.0, _f(c, "high") - _f(c, "low")) for c in vals) / len(vals)
    atr = _atr(candles, min(14, len(candles)))
    is_chop = efficiency < 0.22 or avg_range < max(atr * 0.35, 1e-12)
    return {"is_chop": bool(is_chop), "efficiency": efficiency, "avg_range": avg_range, "atr": atr, "reason": "low_directional_efficiency" if is_chop else "directional"}


def _find_break(candles: list[dict[str, Any]], formation_index: int, direction: str) -> dict[str, Any] | None:
    highs, lows = _swings(candles[:formation_index], 2)
    if direction == "bullish":
        candidates = [(i, p) for i, p in highs if i < formation_index]
        if not candidates:
            return None
        idx, level = candidates[-1]
        return {"index": idx, "price": level, "broken": _f(candles[formation_index], "close") > level}
    candidates = [(i, p) for i, p in lows if i < formation_index]
    if not candidates:
        return None
    idx, level = candidates[-1]
    return {"index": idx, "price": level, "broken": _f(candles[formation_index], "close") < level}


def _retest_state(candles: list[dict[str, Any]], start: int, low: float, high: float, direction: str, expiry: int = 8) -> dict[str, Any]:
    future = candles[start + 1:]
    if not future:
        return {"state": "AWAITING_RETEST", "touch": False, "midpoint_touch": False, "holds": False, "retest_index": None, "confirmation_index": None, "retest_candle": None, "confirmation_candle": None, "pending_expired": False}
    midpoint = (low + high) / 2.0
    touch_idx = None
    midpoint_idx = None
    retest_candle = None
    confirmation_idx = None
    confirmation_candle = None
    holds = False
    for j, c in enumerate(future):
        lo, hi, close = _f(c, "low"), _f(c, "high"), _f(c, "close")
        if not (lo <= high and hi >= low):
            continue
        touch_idx = start + 1 + j
        retest_candle = c
        midpoint_idx = touch_idx if lo <= midpoint <= hi else None
        # A valid hold is a rejection from the zone followed by a close that
        # preserves the intended side. A second candle is preferred, but the
        # touch candle itself can confirm when it decisively closes outside.
        if direction == "bullish":
            direct_hold = close > high and close >= _f(c, "open")
            next_c = future[j + 1] if j + 1 < len(future) else None
            next_hold = next_c is not None and _f(next_c, "close") > high and _f(next_c, "close") >= _f(next_c, "open")
        else:
            direct_hold = close < low and close <= _f(c, "open")
            next_c = future[j + 1] if j + 1 < len(future) else None
            next_hold = next_c is not None and _f(next_c, "close") < low and _f(next_c, "close") <= _f(next_c, "open")
        if direct_hold:
            holds, confirmation_idx, confirmation_candle = True, touch_idx, c
        elif next_hold:
            holds, confirmation_idx, confirmation_candle = True, touch_idx + 1, next_c
        break
    expired = touch_idx is None and len(future) > expiry
    if holds:
        state = "RETEST_HELD"
    elif touch_idx is not None:
        state = "RETEST_FAILED" if ((direction == "bullish" and _f(retest_candle, "close") < low) or (direction == "bearish" and _f(retest_candle, "close") > high)) else "RETEST_TOUCHED"
    elif expired:
        state = "PENDING_EXPIRED"
    else:
        state = "AWAITING_RETEST"
    return {
        "state": state, "touch": touch_idx is not None, "midpoint_touch": midpoint_idx is not None,
        "holds": holds, "retest_index": touch_idx, "confirmation_index": confirmation_idx,
        "retest_candle": retest_candle, "confirmation_candle": confirmation_candle,
        "pending_expired": expired, "midpoint": midpoint,
    }


def detect_fvg_playbook(candles: list[dict[str, Any]], *, max_retest_candles: int = 8) -> dict[str, Any]:
    values = _closed(candles)
    if len(values) < 20:
        return {"status": "insufficient", "zones": [], "tradeable": [], "ifvg": [], "continuation": None}

    zones: list[dict[str, Any]] = []
    chop = _chop_status(values)
    highs, lows = _swings(values, 2)
    swing_high_map = {i: p for i, p in highs}
    swing_low_map = {i: p for i, p in lows}

    for i in range(2, len(values)):
        first, middle, third = values[i-2], values[i-1], values[i]
        bull = _f(first, "high") < _f(third, "low")
        bear = _f(first, "low") > _f(third, "high")
        if not bull and not bear:
            continue
        direction = "bullish" if bull else "bearish"
        low, high = (_f(first, "high"), _f(third, "low")) if bull else (_f(third, "high"), _f(first, "low"))
        body = abs(_f(middle, "close") - _f(middle, "open"))
        baseline = sum(abs(_f(c, "close") - _f(c, "open")) for c in values[max(0, i-16):i-1]) / max(1, len(values[max(0, i-16):i-1]))
        atr = _atr(values[:i], min(14, i))
        displacement = body >= max(baseline * 1.20, atr * 0.80)
        break_info = _find_break(values, i-1, direction)
        swing_broken = bool(break_info and break_info.get("broken"))
        clear_direction = direction == ("bullish" if _f(middle, "close") > _f(middle, "open") else "bearish")
        qualified = bool(displacement and swing_broken and clear_direction and not chop["is_chop"])
        future = values[i+1:]
        invalidation_offset = next((j for j, c in enumerate(future) if (_f(c, "close") < low if bull else _f(c, "close") > high)), None)
        fully_through = invalidation_offset is not None
        touched = any(_f(c, "low") <= high and _f(c, "high") >= low for c in future)
        retest = _retest_state(values, i, low, high, direction, max_retest_candles)
        status = "INVALIDATED" if fully_through else "RETEST_HELD" if retest["holds"] else "RETEST_TOUCHED" if touched else "UNTOUCHED"
        zone = {
            "zone_id": f"FVG:{i}:{direction}:{low:.12g}:{high:.12g}",
            "type": direction,
            "low": low,
            "high": high,
            "midpoint": (low + high) / 2.0,
            "formation_index": i,
            "formation_timestamp": _ts(middle).isoformat() if _ts(middle) else None,
            "displacement_index": i - 1,
            "displacement": displacement,
            "swing_break": break_info,
            "breaks_swing": swing_broken,
            "clear_direction": clear_direction,
            "chop": chop,
            "qualified": qualified,
            "classification": "TRADEABLE_FVG" if qualified and status != "INVALIDATED" else "QUALIFIED_FVG" if qualified else "TECHNICAL_FVG",
            "status": status,
            "touched": touched,
            "fully_through": fully_through,
            "invalidation_index": (i + 1 + invalidation_offset) if invalidation_offset is not None else None,
            "retest": retest,
            "entry_mode": "SPLIT_EDGE_AND_50_PERCENT",
            "entry_levels": {"edge": high if bull else low, "midpoint": (low + high) / 2.0},
            "pending_order_expiry_candles": max_retest_candles,
            "inversion": "AVAILABLE" if fully_through else "NOT_ACTIVE",
        }
        zones.append(zone)

    tradeable = [z for z in zones if z["qualified"] and z["status"] in {"UNTOUCHED", "RETEST_TOUCHED", "RETEST_HELD"}]
    latest_valid = tradeable[-1] if tradeable else None

    ifvg: list[dict[str, Any]] = []
    for z in zones:
        if not z.get("fully_through"):
            continue
        direction = "bearish" if z["type"] == "bullish" else "bullish"
        invalidation_index = z.get("invalidation_index")
        retest_start = int(invalidation_index) if invalidation_index is not None else int(z["formation_index"]) + 1
        retest = _retest_state(values, retest_start, z["low"], z["high"], direction, max_retest_candles)
        ifvg.append({
            "zone_id": f"IFVG:{z['zone_id']}",
            "type": direction,
            "low": z["low"],
            "high": z["high"],
            "midpoint": z["midpoint"],
            "source_fvg": z["zone_id"],
            "status": "TRADEABLE_IFVG" if retest["holds"] else "CONFIRMED_IFVG" if retest["touch"] else "IFVG_CANDIDATE",
            "retest": retest,
            "entry_confirmation": retest["holds"],
            "tradeable": bool(retest["holds"] and not z["chop"]["is_chop"]),
            "stop_rule": "beyond_ifvg_retest_candle",
            "target_rule": "next_marked_liquidity_level",
        })

    continuation = detect_sweep_continuation(values, max_wait_candles=4)
    return {
        "status": "ready",
        "chop_filter": chop,
        "zones": zones,
        "tradeable": tradeable,
        "latest_tradeable": latest_valid,
        "ifvg": ifvg,
        "tradeable_ifvg": [x for x in ifvg if x["tradeable"]],
        "continuation": continuation,
    }


def detect_session_levels(candles: list[dict[str, Any]], reference: datetime | None = None) -> dict[str, Any]:
    """Mark previous-day and prior-session high/low levels in New York time."""
    values = _closed(candles)
    parsed = [(c, _ts(c)) for c in values]
    parsed = [(c, ts.astimezone(NY)) for c, ts in parsed if ts]
    if not parsed:
        return {"status": "insufficient"}
    ref = (reference or parsed[-1][1]).astimezone(NY)
    day = ref.date()
    prev = [c for c, ts in parsed if ts.date() < day]
    today = [c for c, ts in parsed if ts.date() == day]
    london = [c for c, ts in parsed if ts.date() == day and time(3, 0) <= ts.time() < time(8, 0)]
    return {
        "status": "ready",
        "previous_day_high": max((_f(c, "high") for c in prev), default=None),
        "previous_day_low": min((_f(c, "low") for c in prev), default=None),
        "last_session_high": max((_f(c, "high") for c in london), default=None),
        "last_session_low": min((_f(c, "low") for c in london), default=None),
        "reference_ny_date": day.isoformat(),
    }


def _ny_open(ts: datetime) -> datetime:
    local = ts.astimezone(NY)
    return datetime.combine(local.date(), time(9, 30), tzinfo=NY)


def detect_sweep_continuation(candles: list[dict[str, Any]], max_wait_candles: int = 4) -> dict[str, Any] | None:
    values = _closed(candles)
    levels = detect_session_levels(values)
    if levels.get("status") != "ready":
        return None
    candidates = [("previous_day_high", levels.get("previous_day_high"), "SELL"), ("previous_day_low", levels.get("previous_day_low"), "BUY"), ("last_session_high", levels.get("last_session_high"), "SELL"), ("last_session_low", levels.get("last_session_low"), "BUY")]
    for idx, c in enumerate(values):
        ts = _ts(c)
        if not ts or ts.astimezone(NY) < _ny_open(ts):
            continue
        for name, level, direction in candidates:
            if level is None:
                continue
            swept = _f(c, "high") > level if direction == "SELL" else _f(c, "low") < level
            closes_back = _f(c, "close") < level if direction == "SELL" else _f(c, "close") > level
            if not swept or not closes_back:
                continue
            window = values[idx+1:idx+1+max_wait_candles]
            gap_exists = any((_f(window[j-2], "high") < _f(window[j], "low") if _f(window[j-2], "high") < _f(window[j], "low") else _f(window[j-2], "low") > _f(window[j], "high")) for j in range(2, len(window))) if len(window) >= 3 else False
            reaction = any(abs(_f(x, "close") - _f(x, "open")) >= _atr(values[max(0, idx-14):idx+1]) * 0.8 for x in window)
            if gap_exists or reaction:
                return {"status": "WAIT_FOR_RETEST", "level_name": name, "sweep_price": _f(c, "high") if direction == "SELL" else _f(c, "low"), "direction": direction, "sweep_index": idx, "has_gap_or_reaction": True, "tradeable": False}
            return {"status": "CONTINUATION", "level_name": name, "direction": direction, "sweep_index": idx, "entry": _f(c, "close"), "stop_reference": _f(c, "high") if direction == "SELL" else _f(c, "low"), "target_reference": levels.get("previous_day_low") if direction == "SELL" else levels.get("previous_day_high"), "tradeable": True}
    return None


def build_entry_plan(zone: dict[str, Any], direction: str, *, split: bool = True) -> dict[str, Any]:
    direction = direction.upper()
    low, high = float(zone["low"]), float(zone["high"])
    midpoint = (low + high) / 2.0
    edge = high if direction == "BUY" else low
    levels = [edge, midpoint] if split else [midpoint]
    return {
        "direction": direction,
        "entry_levels": levels,
        "allocation": [0.5, 0.5] if split else [1.0],
        "midpoint": midpoint,
        "zone_low": low,
        "zone_high": high,
        "stop_rule": "beyond_retest_candle",
        "target_rule": "minimum_2R_or_next_marked_level",
        "pending_expiry_candles": int(zone.get("pending_order_expiry_candles", 8)),
    }
