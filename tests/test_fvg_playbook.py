from datetime import datetime, timedelta, timezone

from skills.trading_skill.fvg_engine import build_entry_plan, detect_fvg_playbook, detect_session_levels


def candle(i, o, h, l, c):
    return {
        "time": (datetime(2026, 8, 29, tzinfo=timezone.utc) + timedelta(minutes=i)).isoformat(),
        "open": o, "high": h, "low": l, "close": c, "closed": True,
    }


def make_fvg_series(invalidate=False):
    rows = []
    for i in range(10):
        p = 100 + i * 0.15
        rows.append(candle(i, p, p + 0.2, p - 0.2, p + 0.1))
    pre = [
        (101.5, 102.2, 101.0, 102.0), (102.0, 103.0, 101.5, 102.8),
        (102.8, 104.5, 102.4, 104.0), (104.0, 104.6, 103.0, 103.3),
        (103.3, 103.5, 102.2, 102.7), (102.7, 102.9, 101.4, 101.9),
        (101.9, 102.1, 100.7, 101.2), (101.2, 101.4, 99.8, 100.5),
        (100.5, 100.7, 99.0, 99.6), (99.6, 99.9, 98.4, 99.0),
    ]
    for j, item in enumerate(pre, 10):
        rows.append(candle(j, *item))
    rows += [
        candle(20, 99.0, 100.0, 98.5, 99.5),
        candle(21, 99.5, 105.8, 99.0, 105.2),
        candle(22, 105.2, 106.5, 104.7, 106.0),
    ]
    if invalidate:
        rows += [
            candle(23, 106.0, 106.2, 99.0, 99.5),
            candle(24, 99.5, 101.0, 99.2, 99.7),
            candle(25, 99.7, 100.0, 98.8, 99.1),
        ]
    else:
        rows += [
            candle(23, 106.0, 106.2, 102.0, 105.0),
            candle(24, 105.0, 106.0, 104.9, 105.8),
            candle(25, 105.8, 106.5, 105.5, 106.3),
        ]
    return rows


def test_fvg_requires_displacement_and_exact_swing_break():
    result = detect_fvg_playbook(make_fvg_series())
    zone = next(z for z in result["zones"] if z["formation_index"] == 22)
    assert zone["displacement"]
    assert zone["breaks_swing"]
    assert zone["classification"] == "TRADEABLE_FVG"
    assert zone["midpoint"] == (zone["low"] + zone["high"]) / 2
    assert zone["entry_mode"] == "SPLIT_EDGE_AND_50_PERCENT"


def test_fvg_retest_hold_is_confirmed():
    result = detect_fvg_playbook(make_fvg_series())
    zone = next(z for z in result["zones"] if z["formation_index"] == 22)
    assert zone["retest"]["touch"]
    assert zone["retest"]["holds"]
    assert zone["retest"]["midpoint_touch"]


def test_ifvg_is_created_after_full_close_through_and_retest():
    result = detect_fvg_playbook(make_fvg_series(invalidate=True))
    ifvgs = [x for x in result["ifvg"] if x["source_fvg"] == "FVG:22:bullish:100:104.7"]
    assert ifvgs
    assert ifvgs[0]["type"] == "bearish"
    assert ifvgs[0]["entry_confirmation"]
    assert ifvgs[0]["status"] == "TRADEABLE_IFVG"


def test_split_entry_plan_has_edge_and_consequent_encroachment():
    plan = build_entry_plan({"low": 100.0, "high": 104.0, "pending_order_expiry_candles": 6}, "BUY")
    assert plan["entry_levels"] == [104.0, 102.0]
    assert plan["allocation"] == [0.5, 0.5]
    assert plan["pending_expiry_candles"] == 6


def test_previous_day_and_last_session_levels_are_marked():
    rows = []
    # Previous day, all inside UTC/NY conversion-compatible evening.
    base = datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)
    for i, p in enumerate((100.0, 101.0, 99.0, 100.5)):
        rows.append({"time": (base + timedelta(hours=i)).isoformat(), "open": p, "high": p + 0.5, "low": p - 0.5, "close": p, "closed": True})
    # Current day London session in New York time, plus NY-open data.
    base2 = datetime(2026, 8, 29, 7, 0, tzinfo=timezone.utc)
    for i, p in enumerate((102.0, 103.0, 101.5, 102.5)):
        rows.append({"time": (base2 + timedelta(hours=i)).isoformat(), "open": p, "high": p + 0.4, "low": p - 0.4, "close": p, "closed": True})
    levels = detect_session_levels(rows, datetime(2026, 8, 29, 14, 0, tzinfo=timezone.utc))
    assert levels["previous_day_high"] is not None
    assert levels["previous_day_low"] is not None
    assert levels["last_session_high"] is not None
    assert levels["last_session_low"] is not None
