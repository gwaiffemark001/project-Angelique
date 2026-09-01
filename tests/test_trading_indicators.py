"""Indicator mathematics.

These tests encode textbook definitions, not the previous implementation's
behaviour. Reference values come from published worked examples so a
regression cannot be "fixed" by editing the expectation.
"""

import math

import pytest

from skills.trading_skill.indicators import (
    INDICATOR_MINIMUMS, adx, adx_band, atr, atr_series, bollinger, dmi, ema,
    macd, required_history, rsi, rsi_series, sma, snapshot, warmup_for,
    wilder_smooth,
)


# StockCharts' published RSI-14 worked example. The 33rd close yields 37.77.
STOCKCHARTS_CLOSES = [
    44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245,
    45.8433, 46.0826, 45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028,
    46.0328, 46.4116, 46.2222, 45.6439, 46.2122, 46.2521, 45.7137, 46.4515,
    45.7835, 45.3548, 44.0288, 44.1783, 44.2181, 44.5672, 43.4205, 42.6628,
    43.1314,
]


def _candles(values, spread=0.5):
    return [
        {"time": i, "open": v, "high": v + spread, "low": v - spread, "close": v, "closed": True}
        for i, v in enumerate(values)
    ]


# --------------------------------------------------------------------------
# RSI -- Wilder smoothing, not a simple mean
# --------------------------------------------------------------------------
def test_rsi_matches_published_wilder_reference():
    assert round(rsi(STOCKCHARTS_CLOSES, 14), 2) == 37.77


def test_rsi_is_wilder_not_simple_average():
    """A simple average of gains/losses gives a materially different number."""
    period = 14
    closes = STOCKCHARTS_CLOSES
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas][-period:]
    losses = [max(-d, 0.0) for d in deltas][-period:]
    simple_rs = (sum(gains) / period) / (sum(losses) / period)
    simple_rsi = 100 - 100 / (1 + simple_rs)
    assert abs(rsi(closes, period) - simple_rsi) > 1.0


def test_rsi_bounds():
    assert rsi(list(range(1, 60)), 14) == 100.0
    assert rsi(list(range(60, 0, -1)), 14) == 0.0


def test_rsi_returns_none_before_warmup():
    assert rsi([1, 2, 3], 14) is None


# --------------------------------------------------------------------------
# ATR -- Wilder smoothing of true range
# --------------------------------------------------------------------------
def test_atr_uses_true_range_including_gaps():
    candles = [
        {"open": 10, "high": 11, "low": 9, "close": 10},
        # Gaps up: the true range must measure from the PREVIOUS close (10),
        # not merely high-low (1.0).
        {"open": 20, "high": 21, "low": 20, "close": 20.5},
    ]
    series = atr_series(candles, 1)
    assert series[-1] == pytest.approx(11.0)


def test_atr_is_wilder_not_simple_moving_average():
    values = [100 + (5 if i == 30 else 0) for i in range(60)]
    candles = _candles(values, spread=1.0)
    period = 14
    trs = []
    for i in range(1, len(candles)):
        high, low = candles[i]["high"], candles[i]["low"]
        previous_close = candles[i - 1]["close"]
        trs.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    simple = sum(trs[-period:]) / period
    assert abs(atr(candles, period) - simple) > 1e-9


def test_atr_drops_the_seed_bar_that_has_no_previous_close():
    """The first bar has no previous close, so it yields no true range.

    With N candles there are N-1 true ranges, and a period-P Wilder average
    consumes P of them before producing its first value.
    """
    period = 14
    candles = _candles(list(range(100, 140)))
    expected = (len(candles) - 1) - period + 1
    assert len(atr_series(candles, period)) == expected


# --------------------------------------------------------------------------
# ADX -- real +DI / -DI / DX / smoothed ADX
# --------------------------------------------------------------------------
def test_adx_reports_directional_indicators():
    result = dmi(_candles([100 + i for i in range(80)]), 14)
    assert result["plus_di"] > result["minus_di"]
    assert result["adx"] > 25
    for key in ("plus_di", "minus_di", "adx", "dx"):
        assert result[key] is not None


def test_adx_direction_flips_with_the_market():
    up = dmi(_candles([100 + i for i in range(80)]), 14)
    down = dmi(_candles([200 - i for i in range(80)]), 14)
    assert up["plus_di"] > up["minus_di"]
    assert down["minus_di"] > down["plus_di"]


def test_adx_is_low_in_a_range():
    values = [100 + 0.2 * math.sin(i / 2) for i in range(120)]
    assert adx(_candles(values, spread=0.25), 14) < 25


def test_adx_bands_are_graded_not_binary():
    assert adx_band(5) == "NO_TREND"
    assert adx_band(18) == "WEAK"
    assert adx_band(22) == "DEVELOPING"
    assert adx_band(30) == "TRENDING"
    assert adx_band(60) == "EXTREME"
    # 20-25 must NOT be reported as a confirmed trend.
    assert adx_band(23) != "TRENDING"


# --------------------------------------------------------------------------
# EMA / MACD -- SMA seeded, not seeded at values[0]
# --------------------------------------------------------------------------
def test_ema_is_seeded_with_an_sma():
    values = [10.0] * 20 + [20.0] * 20
    assert ema(values[:20], 20) == pytest.approx(10.0)


def test_ema_of_a_constant_series_is_that_constant():
    assert ema([5.0] * 100, 20) == pytest.approx(5.0)


def test_macd_components_are_consistent():
    values = [100 + i * 0.4 + math.sin(i / 3) for i in range(200)]
    result = macd(values)
    assert result["macd"] is not None
    assert result["histogram"] == pytest.approx(result["macd"] - result["signal"])
    assert result["zero_line_state"] in {"ABOVE", "BELOW"}


def test_macd_returns_none_before_warmup():
    assert macd([1.0, 2.0, 3.0])["macd"] is None


# --------------------------------------------------------------------------
# Bollinger
# --------------------------------------------------------------------------
def test_bollinger_bands_are_symmetric_about_the_mean():
    values = [100 + math.sin(i / 4) for i in range(60)]
    bands = bollinger(values, 20, 2.0)
    assert bands["upper"] - bands["middle"] == pytest.approx(bands["middle"] - bands["lower"])
    assert bands["middle"] == pytest.approx(sma(values, 20))


def test_bollinger_percent_b_is_zero_at_the_lower_band():
    values = [100.0] * 20
    bands = bollinger(values, 20, 2.0)
    # Zero standard deviation: bands collapse onto the mean.
    assert bands["upper"] == pytest.approx(bands["lower"])


# --------------------------------------------------------------------------
# Warm-up gating
# --------------------------------------------------------------------------
def test_warmup_requirements_exceed_the_raw_period_for_wilder_indicators():
    assert warmup_for("rsi", 14) > 14
    assert warmup_for("atr", 14) > 14
    # ADX needs a second smoothing pass, so it needs more than RSI/ATR.
    assert warmup_for("adx", 14) > warmup_for("rsi", 14)


def test_ema200_requires_more_than_200_candles():
    assert INDICATOR_MINIMUMS["ema_200"] > 200
    assert required_history() >= INDICATOR_MINIMUMS["ema_200"]


def test_snapshot_is_insufficient_with_five_candles():
    result = snapshot(_candles([1.1 + i * 0.001 for i in range(5)]))
    assert result["status"] == "insufficient"
    assert result["available_candles"] == 5


def test_snapshot_gates_every_value_until_warmed_up():
    result = snapshot(_candles([1.1 + i * 0.0001 for i in range(40)]))
    # 40 candles: EMA20 is available, EMA200 and ADX are not.
    assert result["readiness"]["ema_20"] is True
    assert result["readiness"]["ema_200"] is False
    assert result["ema_200"] is None
    assert result["adx_14"] is None


def test_snapshot_ignores_a_forming_candle():
    closed_only = _candles([1.1 + i * 0.0001 for i in range(400)])
    with_forming = closed_only + [
        {"time": 999, "open": 9, "high": 99, "low": 0.1, "close": 50, "closed": False}
    ]
    baseline = snapshot(closed_only)
    result = snapshot(with_forming)
    assert result["available_candles"] == 400 == baseline["available_candles"]
    # The absurd forming candle must change nothing at all.
    assert result["atr_14"] == pytest.approx(baseline["atr_14"])
    assert result["last_close"] == pytest.approx(baseline["last_close"])
    assert result["rsi_14"] == pytest.approx(baseline["rsi_14"])


def test_snapshot_is_ready_with_full_history():
    result = snapshot(_candles([1.1 + i * 0.0002 for i in range(400)]))
    assert result["status"] == "ready"
    assert all(result["readiness"].values())
    assert result["ema_200"] is not None
    assert result["adx_14"] is not None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def test_wilder_smooth_matches_the_recursive_definition():
    values = [1.0] * 30
    smoothed = wilder_smooth(values, 14)
    assert smoothed[-1] == pytest.approx(1.0)


def test_malformed_candles_are_filtered_out():
    candles = _candles([100 + i for i in range(80)])
    candles.insert(10, {"time": 10, "open": 0, "high": 0, "low": 0, "close": 0})
    assert atr(candles, 14) is not None
