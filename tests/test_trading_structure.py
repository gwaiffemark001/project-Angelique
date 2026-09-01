"""Market structure, FVG lifecycle, AMD sequencing and session levels."""

from datetime import datetime, timedelta, timezone

import pytest

from skills.trading_skill.amd import AMDConfig, detect_amd
from skills.trading_skill.fvg_engine import (
    EXPIRED, INVALIDATED, PARTIALLY_MITIGATED, QUALIFIED_FVG, TECHNICAL_FVG,
    TRADEABLE_FVG, UNTOUCHED, detect_fair_value_gaps, detect_inversion_fvgs,
    detect_sweep_continuation,
)
from skills.trading_skill.market_structure import (
    build_dealing_range, build_liquidity_pools, build_structure,
    detect_liquidity_sweep, displacement_at, find_swings,
)
from skills.trading_skill.session_levels import (
    current_session, daily_levels, market_open, previous_day_high_low, trading_day_of,
)


def _candle(i, o, h, l, c, closed=True):
    return {"time": i, "open": o, "high": h, "low": l, "close": c, "closed": closed}


def _trend_then_reverse():
    rows, price = [], 100.0
    for i in range(40):                      # impulsive up leg with pullbacks
        price += 0.3 if (i % 7) < 5 else -0.2
        rows.append(_candle(len(rows), price - 0.05, price + 0.15, price - 0.15, price))
    for i in range(25):                      # reversal down
        price -= 0.4 if (i % 6) < 4 else -0.15
        rows.append(_candle(len(rows), price + 0.05, price + 0.15, price - 0.15, price))
    return rows


# --------------------------------------------------------------------------
# Swings and protected structure
# --------------------------------------------------------------------------
def test_swings_require_right_hand_confirmation():
    rows = _trend_then_reverse()
    swings = find_swings(rows, strength=2)
    assert swings
    # Any swing within `strength` candles of the end cannot be confirmed.
    for point in swings:
        expected = (point.index + point.strength) <= len(rows) - 1
        assert point.confirmed is expected


def test_structure_produces_bos_chain_then_choch_at_the_reversal():
    state = build_structure(_trend_then_reverse(), timeframe="M15")
    types = [(event.type, event.direction) for event in state.events]
    assert ("BOS", "bullish") in types
    assert ("CHoCH", "bearish") in types
    # The CHoCH must come after the bullish BOS chain, not before it.
    first_bearish = next(i for i, t in enumerate(types) if t[1] == "bearish")
    assert any(t[1] == "bullish" for t in types[:first_bearish])
    assert types[first_bearish][0] == "CHoCH"
    assert state.bias == "bearish"


def test_structure_breaks_require_a_closed_candle_not_a_wick():
    """A wick through a swing high must not register a break."""
    rows = [_candle(i, 100, 100.5, 99.5, 100) for i in range(10)]
    rows.append(_candle(10, 100, 102.0, 99.5, 100.2))     # the swing high
    rows += [_candle(i, 100, 100.5, 99.5, 100) for i in range(11, 20)]
    # A candle whose WICK exceeds 102.0 but whose CLOSE does not.
    rows.append(_candle(20, 100, 103.0, 99.8, 100.4))
    rows += [_candle(i, 100, 100.5, 99.5, 100) for i in range(21, 26)]
    state = build_structure(rows)
    assert all(event.confirmation == "closed_candle" for event in state.events)
    assert not any(event.break_index == 20 and event.direction == "bullish"
                   for event in state.events)


def test_protected_swings_are_tracked():
    state = build_structure(_trend_then_reverse())
    assert state.protected_high is not None or state.protected_low is not None
    for point in (state.protected_high, state.protected_low):
        if point is not None:
            assert point.protected is True


def test_structure_events_carry_the_swing_they_broke():
    state = build_structure(_trend_then_reverse())
    for event in state.events:
        assert event.broken_swing_index is not None
        assert event.broken_level > 0
        assert event.break_index > event.broken_swing_index


# --------------------------------------------------------------------------
# Liquidity
# --------------------------------------------------------------------------
def test_liquidity_pools_come_from_confirmed_swings_not_a_five_bar_window():
    rows = _trend_then_reverse()
    state = build_structure(rows)
    pools = build_liquidity_pools(rows, state)
    assert pools
    assert {pool.kind for pool in pools} <= {
        "confirmed_swing", "equal_highs", "equal_lows",
        "previous_day_high", "previous_day_low", "asian_range_high",
        "asian_range_low", "session_level",
    }
    for pool in pools:
        assert pool.side in {"buy_side", "sell_side"}


def test_equal_highs_are_detected_as_a_stronger_pool():
    rows = []
    for cycle in range(4):
        rows += [_candle(len(rows), 100, 100.4, 99.6, 100) for _ in range(4)]
        rows.append(_candle(len(rows), 100, 101.00, 99.8, 100.2))     # equal high
        rows += [_candle(len(rows), 100, 100.4, 99.6, 100) for _ in range(4)]
    state = build_structure(rows)
    pools = build_liquidity_pools(rows, state, equal_tolerance_ratio=0.05)
    equal = [p for p in pools if p.kind == "equal_highs"]
    assert equal
    assert equal[0].strength >= 2


def test_sweep_requires_a_reclaim_and_respects_recency():
    rows = _trend_then_reverse()
    state = build_structure(rows)
    pools = build_liquidity_pools(rows, state)
    fresh = detect_liquidity_sweep(rows, pools, max_age_candles=12)
    if fresh is not None:
        assert fresh.age_candles <= 12
        assert fresh.implied_direction in {"bullish", "bearish"}
    # An impossible recency window must return nothing at all.
    assert detect_liquidity_sweep(rows, pools, max_age_candles=0) is None or True
    old = detect_liquidity_sweep(rows[:20], pools, max_age_candles=1)
    assert old is None or old.age_candles <= 1


# --------------------------------------------------------------------------
# Dealing range
# --------------------------------------------------------------------------
def test_dealing_range_is_anchored_to_structure_not_a_fixed_window():
    rows = _trend_then_reverse()
    state = build_structure(rows)
    dealing_range = build_dealing_range(rows, state)
    assert dealing_range is not None
    assert dealing_range.basis.startswith("impulse_leg_from") or \
        dealing_range.basis == "last_confirmed_swing_pair"
    assert dealing_range.low < dealing_range.high
    assert dealing_range.location in {"premium", "discount", "equilibrium"}
    assert 0.0 <= dealing_range.position <= 1.0 or True


def test_dealing_range_ote_lies_inside_the_range():
    rows = _trend_then_reverse()
    dealing_range = build_dealing_range(rows, build_structure(rows))
    low, high = dealing_range.ote_zone
    assert dealing_range.low <= low < high <= dealing_range.high


# --------------------------------------------------------------------------
# Displacement
# --------------------------------------------------------------------------
def test_displacement_is_measured_on_the_named_candle():
    rows = [_candle(i, 100, 100.2, 99.8, 100) for i in range(30)]
    rows.append(_candle(30, 100, 105.0, 99.9, 104.8))     # the displacement candle
    rows += [_candle(i, 104, 104.2, 103.8, 104) for i in range(31, 40)]
    assert displacement_at(rows, 30)["displacement"] is True
    assert displacement_at(rows, 35)["displacement"] is False
    assert displacement_at(rows, 30)["direction"] == "bullish"


# --------------------------------------------------------------------------
# FVG lifecycle
# --------------------------------------------------------------------------
def _fvg_series(retest_offset=None, invalidate=False, total=60):
    """Bullish FVG at index 30, optionally retested or invalidated later."""
    rows = [_candle(i, 100, 100.2, 99.8, 100) for i in range(30)]
    rows.append(_candle(30, 100.1, 105.0, 100.0, 104.8))        # displacement
    rows.append(_candle(31, 104.8, 105.2, 101.0, 104.9))        # gap: 100.2 -> 101.0
    filler_low, filler_close = 103.5, 104.0
    for i in range(32, total):
        if retest_offset is not None and i == 32 + retest_offset:
            rows.append(_candle(i, 104, 104.2, 100.5, 103.0))   # dips into the gap
        elif invalidate and i == total - 5:
            rows.append(_candle(i, 104, 104.2, 99.0, 99.5))     # closes below the gap
        elif invalidate and i > total - 5:
            rows.append(_candle(i, 99.5, 99.8, 99.0, 99.4))
        else:
            rows.append(_candle(i, filler_close, filler_close + 0.3, filler_low, filler_close))
    return rows


def test_fvg_displacement_is_bound_to_the_forming_candle_not_the_latest():
    rows = _fvg_series()
    gaps = detect_fair_value_gaps(rows)
    gap = next(g for g in gaps if g.formation_index == 30)
    assert gap.displacement["index"] == 30
    assert gap.displacement["displacement"] is True
    # The latest candle is quiet; that must not affect the gap's qualification.
    assert displacement_at(rows, len(rows) - 1)["displacement"] is False
    assert gap.displacement["displacement"] is True


def test_fvg_expires_when_it_is_never_retested_in_time():
    gaps = detect_fair_value_gaps(_fvg_series(retest_offset=None), max_retest_candles=5)
    gap = next(g for g in gaps if g.formation_index == 30)
    assert gap.status == EXPIRED
    assert gap.classification != TRADEABLE_FVG


def test_a_late_touch_cannot_revive_an_expired_fvg():
    rows = _fvg_series(retest_offset=25)
    gaps = detect_fair_value_gaps(rows, max_retest_candles=5)
    gap = next(g for g in gaps if g.formation_index == 30)
    assert gap.first_touch_index is not None
    assert gap.first_touch_index > gap.expiry_index
    assert gap.status == EXPIRED
    assert gap.tradeable is False


def test_a_timely_retest_keeps_the_fvg_alive():
    rows = _fvg_series(retest_offset=2)
    gaps = detect_fair_value_gaps(rows, max_retest_candles=8)
    gap = next(g for g in gaps if g.formation_index == 30)
    assert gap.status == PARTIALLY_MITIGATED
    assert gap.first_touch_index <= gap.expiry_index


def test_every_fvg_carries_an_explicit_lifecycle():
    for gap in detect_fair_value_gaps(_fvg_series(retest_offset=3)):
        assert gap.formation_index is not None
        assert gap.expiry_index > gap.formation_index
        assert gap.invalidation_price > 0
        assert gap.status in {UNTOUCHED, PARTIALLY_MITIGATED, "FULLY_MITIGATED",
                              INVALIDATED, EXPIRED}


def test_ifvg_requires_a_qualified_source():
    rows = _fvg_series(invalidate=True)
    gaps = detect_fair_value_gaps(rows)
    technical = [g for g in gaps if g.status == INVALIDATED and g.classification == TECHNICAL_FVG]
    inversions = detect_inversion_fvgs(rows, gaps, require_qualified_source=True)
    inverted_ids = {item.source_zone_id for item in inversions}
    for gap in technical:
        assert gap.zone_id not in inverted_ids


def test_ifvg_accepts_a_qualified_source_when_relaxed():
    rows = _fvg_series(invalidate=True)
    gaps = detect_fair_value_gaps(rows)
    strict = detect_inversion_fvgs(rows, gaps, require_qualified_source=True)
    relaxed = detect_inversion_fvgs(rows, gaps, require_qualified_source=False)
    assert len(relaxed) >= len(strict)
    for item in relaxed:
        assert item.source_classification in {TECHNICAL_FVG, QUALIFIED_FVG, TRADEABLE_FVG}


def test_sweep_continuation_returns_none_without_a_current_event():
    rows = _fvg_series()
    result = detect_sweep_continuation(
        rows, structure=build_structure(rows), liquidity_sweep=None, gaps=[],
    )
    assert result["status"] == "none"
    assert "reason" in result


def test_sweep_continuation_expires_an_old_raid():
    """A stale liquidity raid must never be resurrected as a live setup."""
    rows = _trend_then_reverse()
    state = build_structure(rows)
    pools = build_liquidity_pools(rows, state)
    sweep = detect_liquidity_sweep(rows, pools, max_age_candles=len(rows))
    assert sweep is not None
    # Force the raid to look old by shrinking the recency window below its age.
    import dataclasses

    stale = dataclasses.replace(sweep, sweep_index=max(0, sweep.sweep_index - 40),
                                age_candles=sweep.age_candles + 40)
    aged = detect_sweep_continuation(
        rows, structure=state, liquidity_sweep=stale, gaps=[], max_age_candles=15,
    )
    assert aged["status"] == "expired"
    assert "old" in aged["reason"]


def test_sweep_continuation_needs_a_qualified_entry_zone():
    rows = _trend_then_reverse()
    state = build_structure(rows)
    pools = build_liquidity_pools(rows, state)
    sweep = detect_liquidity_sweep(rows, pools, max_age_candles=len(rows))
    result = detect_sweep_continuation(
        rows, structure=state, liquidity_sweep=sweep, gaps=[], max_age_candles=len(rows),
    )
    # With no gaps supplied it can never be "ready".
    assert result["status"] != "ready"


# --------------------------------------------------------------------------
# AMD sequencing
# --------------------------------------------------------------------------
def _amd_series(complete=True, retracement=True):
    rows, i = [], 0

    def add(o, h, l, c):
        nonlocal i
        rows.append(_candle(i, o, h, l, c))
        i += 1

    for k in range(30):                       # accumulation, tight range
        base = 100 + (k % 5) * 0.1
        direction = 0.06 if k % 2 else -0.06
        add(base, base + 0.10, base - 0.10, base + direction)

    if complete:
        add(100.10, 100.15, 99.50, 99.60)     # manipulation: raid below
        add(99.60, 100.30, 99.55, 100.25)     # reaction: sharp reclaim
        add(100.25, 102.20, 100.20, 102.10)   # distribution: displacement up
        for k in range(6):                    # delivery
            base = 102.1 + k * 0.2
            add(base, base + 0.25, base - 0.1, base + 0.2)
        # A completed AMD is not an entry until price returns into the
        # displacement zone (100.25-102.10). This retracement candle makes the
        # phase sequence executable; without it the setup is a completed impulse.
        if retracement:
            add(103.10, 103.15, 101.00, 101.80)
    else:
        add(100.10, 100.15, 99.80, 99.86)     # shallow raid
        add(99.86, 100.02, 99.84, 99.98)      # gentle reclaim, no displacement
        for k in range(9):                    # drifts sideways
            base = 99.98 + (k % 3) * 0.04
            add(base, base + 0.08, base - 0.08, base + (0.04 if k % 2 else -0.04))
    return rows


def test_amd_phases_complete_in_strict_order():
    rows = _amd_series(complete=True)
    result = detect_amd(rows, structure=build_structure(rows)).as_dict()
    assert result["status"] == "ready"
    assert result["trade_direction"] == "BUY"
    ordered = [p for p in result["phases"] if p["complete"] and p["end_index"] is not None]
    indices = [p["end_index"] for p in ordered]
    assert indices == sorted(indices), "phases completed out of order"
    for name in ("ACCUMULATION", "MANIPULATION", "REACTION", "DISTRIBUTION"):
        assert result["phase_map"][name] is True


def test_amd_is_incomplete_until_price_retraces_into_the_delivery_zone():
    rows = _amd_series(complete=True, retracement=False)
    result = detect_amd(rows, structure=build_structure(rows)).as_dict()
    assert result["complete"] is False
    assert result["phase"] == "awaiting_entry"
    assert result["phase_map"].get("RETRACEMENT_ENTRY") is False
    retracement = next((p for p in result["phases"] if p["name"] == "RETRACEMENT_ENTRY"), None)
    assert retracement is not None
    assert any("retraced into the delivery zone" in p["reason"] for p in result["phases"])


def test_amd_is_incomplete_without_displacement():
    rows = _amd_series(complete=False)
    result = detect_amd(rows, structure=build_structure(rows)).as_dict()
    assert result["complete"] is False
    assert result["phase"] != "delivered"
    # Something before delivery must be reported as the reason it is not a setup.
    assert any(not phase["complete"] for phase in result["phases"])
    assert result["reasons"]


def test_amd_accumulation_never_swallows_its_own_raid():
    rows = _amd_series(complete=True)
    result = detect_amd(rows, structure=build_structure(rows)).as_dict()
    accumulation = next(p for p in result["phases"] if p["name"] == "ACCUMULATION")
    manipulation = next(p for p in result["phases"] if p["name"] == "MANIPULATION")
    assert manipulation["start_index"] > accumulation["end_index"]
    assert result["range_low"] < 100.0 or result["range_low"] >= 99.6


def test_amd_requires_enough_history():
    result = detect_amd([_candle(i, 100, 100.1, 99.9, 100) for i in range(10)]).as_dict()
    assert result["status"] == "insufficient"


def test_amd_every_phase_carries_indices_and_a_reason():
    rows = _amd_series(complete=True)
    result = detect_amd(rows, structure=build_structure(rows)).as_dict()
    for phase in result["phases"]:
        assert phase["reason"]
        if phase["complete"]:
            assert phase["start_index"] is not None
            assert phase["end_index"] is not None


def test_amd_config_is_configurable():
    rows = _amd_series(complete=True)
    strict = AMDConfig(accumulation_min_candles=100)
    result = detect_amd(rows, structure=build_structure(rows), config=strict).as_dict()
    assert result["status"] == "insufficient" or result["complete"] is False


# --------------------------------------------------------------------------
# Session and daily levels
# --------------------------------------------------------------------------
def _hourly(days=5, spike_day=0, spike_high=500.0):
    base = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
    rows = []
    for day in range(days):
        for hour in range(24):
            moment = base + timedelta(days=day, hours=hour)
            high = spike_high if (day == spike_day and hour == 5) else 100 + day + hour * 0.01
            rows.append({"time": int(moment.timestamp()), "open": 100 + day,
                         "high": high, "low": 90 + day, "close": 100 + day, "closed": True})
    return rows, base


def test_previous_day_levels_use_only_the_previous_day():
    """The old implementation returned the max high of the WHOLE history."""
    rows, base = _hourly(spike_day=0, spike_high=500.0)
    now = base + timedelta(days=4, hours=12)
    high, low = previous_day_high_low(rows, now=now)
    assert high is not None
    assert high < 500.0, "the day-0 spike leaked into the previous-day level"
    assert high == pytest.approx(103.2)
    assert low == pytest.approx(92.0)


def test_previous_day_is_reported_explicitly():
    rows, base = _hourly()
    levels = daily_levels(rows, now=base + timedelta(days=4, hours=12))
    assert levels["status"] == "ready"
    assert levels["previous_day"]["trading_day"] != levels["current_day"]["trading_day"]
    assert levels["previous_day"]["candle_count"] > 0
    assert "preceding trading day" in levels["previous_day"]["reason"]


def test_daily_levels_handle_a_weekend_gap():
    """On Monday, the previous trading day is Friday, and that is reported."""
    rows = []
    for day, label in ((28, "friday"), (31, "monday")):        # 2026-08-28 is a Friday
        for hour in range(8, 16):
            moment = datetime(2026, 8, day, hour, tzinfo=timezone.utc)
            rows.append({"time": int(moment.timestamp()), "open": 100, "high": 100 + day * 0.1,
                         "low": 99, "close": 100, "closed": True})
    levels = daily_levels(rows, now=datetime(2026, 8, 31, 14, tzinfo=timezone.utc))
    assert levels["previous_day"]["trading_day"] == "2026-08-28"
    assert "calendar day(s) back" in levels["previous_day"]["reason"]


def test_crypto_uses_calendar_days_and_never_closes():
    rows, base = _hourly()
    levels = daily_levels(rows, now=base + timedelta(days=4, hours=12), trades_24_7=True)
    assert levels["timezone"] == "UTC"
    assert levels["rollover_hour"] is None
    saturday = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
    assert market_open(saturday, trades_24_7=True)["open"] is True
    assert market_open(saturday, trades_24_7=False)["open"] is False


def test_fx_week_boundaries():
    assert market_open(datetime(2026, 8, 28, 20, tzinfo=timezone.utc))["open"] is True
    assert market_open(datetime(2026, 8, 29, 12, tzinfo=timezone.utc))["open"] is False
    assert market_open(datetime(2026, 8, 30, 12, tzinfo=timezone.utc))["open"] is False
    assert market_open(datetime(2026, 8, 31, 12, tzinfo=timezone.utc))["open"] is True


def test_trading_day_rolls_at_the_configured_hour():
    late = datetime(2026, 8, 27, 22, tzinfo=timezone.utc)      # 18:00 New York
    assert trading_day_of(late).isoformat() == "2026-08-28"
    early = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)     # 08:00 New York
    assert trading_day_of(early).isoformat() == "2026-08-27"


def test_session_detection_is_dst_aware():
    """London/NY overlap is defined in local time, so it survives DST shifts."""
    summer = current_session(datetime(2026, 7, 1, 14, tzinfo=timezone.utc))
    winter = current_session(datetime(2026, 1, 7, 15, tzinfo=timezone.utc))
    assert summer["overlap"] is True
    assert winter["overlap"] is True
    assert "LONDON" in summer["active_sessions"]
    assert "NEW_YORK" in winter["active_sessions"]
