from datetime import datetime, timezone

import pandas as pd

from skills.trading.ict_core import calculate_ote, get_current_session, is_kill_zone, identify_ote_zone
from skills.trading_skill.smc import detect_choch


def candles(n=50, base=1.1000):
    rows = []
    for i in range(n):
        close = base + i * 0.0005
        rows.append({"time": datetime(2026, 8, 30, 0, i % 60, tzinfo=timezone.utc).isoformat(), "open": close - 0.0002, "high": close + 0.0004, "low": close - 0.0004, "close": close, "closed": True})
    return rows


def test_ote_is_direction_aware():
    levels = calculate_ote(120.0, 100.0)
    assert levels["bullish_lower"] == 104.28
    assert levels["bullish_upper"] == 107.64
    assert levels["bearish_lower"] == 112.36
    assert levels["bearish_upper"] == 115.72


def test_ote_zone_detection():
    rows = candles(50, 1.0)
    df = pd.DataFrame(rows)
    result = identify_ote_zone(df, lookback=40)
    assert result and "in_bullish_ote" in result and "in_bearish_ote" in result


def test_kill_zone_is_boundary_safe():
    london = datetime(2026, 8, 30, 7, 0, tzinfo=timezone.utc)
    london_end = datetime(2026, 8, 30, 10, 0, tzinfo=timezone.utc)
    assert is_kill_zone(london)
    assert not is_kill_zone(london_end)
    assert get_current_session(london).name == "London Open"


def test_strict_choch_requires_sweep_and_strong_body():
    rows = []
    for i in range(20):
        price = 1.1000 + i * 0.001
        rows.append({"open": price, "high": price + .0005, "low": price - .0005, "close": price + .0002, "closed": True})
    weak = {"open": 1.1195, "high": 1.1210, "low": 1.1185, "close": 1.1201, "closed": True}
    rows.append(weak)
    assert not detect_choch(rows, liquidity_swept=False)["valid"]

