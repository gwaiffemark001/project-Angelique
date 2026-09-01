"""Standard technical-indicator mathematics.

Every function in this module implements the *textbook* formulation. Where a
reference implementation exists (Wilder's RSI/ATR/ADX, Appel's MACD, Bollinger
bands) that formulation is used, not an approximation.

Key corrections relative to the previous implementation
-------------------------------------------------------
* ``rsi``  -- was a simple mean of the last N gains/losses. Now Wilder smoothing
              (first average = simple mean of the first ``period`` changes,
              then ``avg = (avg * (period - 1) + current) / period``).
* ``atr``  -- was a simple mean of the last N true ranges. Now Wilder smoothing
              of the true range.
* ``adx``  -- was ``mean(|+DM - -DM|) / mean(TR)``, which is not ADX at all.
              Now the full Wilder pipeline: +DM/-DM -> smoothed -> +DI/-DI ->
              DX -> smoothed ADX. ``+DI``/``-DI`` are exposed so strategies can
              use directional strength rather than an undirected number.
* ``macd`` -- proper seeded EMAs plus zero-line state and cross state.
* Warm-up  -- indicators report ``None`` (not a number) until enough closed
              candles exist, and ``readiness`` reflects the *actual* warm-up
              requirement of each calculation rather than an arbitrary constant.

All functions operate on **closed** candles only; a candle flagged
``closed=False`` is discarded before any calculation.
"""

from __future__ import annotations

from typing import Any, Sequence

# --------------------------------------------------------------------------
# Warm-up policy
# --------------------------------------------------------------------------
#: Wilder-smoothed indicators converge asymptotically. Feeding exactly `period`
#: values produces a mathematically defined but unstable value, so we require a
#: convergence multiple before declaring the indicator usable.
WILDER_CONVERGENCE_MULTIPLE = 5
#: EMAs are seeded with an SMA of the first `period` values; the same idea
#: applies but EMAs converge faster than Wilder smoothing.
EMA_CONVERGENCE_MULTIPLE = 3


def warmup_for(kind: str, period: int) -> int:
    """Minimum number of closed candles for a *stable* indicator value."""
    period = max(1, int(period))
    if kind in {"rsi", "atr", "adx"}:
        # ADX needs a second smoothing pass over DX values.
        extra = period if kind == "adx" else 0
        return period * WILDER_CONVERGENCE_MULTIPLE + extra + 1
    if kind == "ema":
        # An SMA-seeded EMA is defined at `period` values; the seed's influence
        # decays geometrically. Half a period of extra data reduces it to a few
        # percent, which is the practical convergence point.
        return period + max(10, period // 2)
    if kind == "macd":
        return 26 * EMA_CONVERGENCE_MULTIPLE + 9
    if kind == "bollinger":
        return period
    return period


INDICATOR_MINIMUMS: dict[str, int] = {
    "ema_20": warmup_for("ema", 20),
    "ema_50": warmup_for("ema", 50),
    "ema_200": warmup_for("ema", 200),
    "rsi_14": warmup_for("rsi", 14),
    "atr_14": warmup_for("atr", 14),
    "bollinger_middle": warmup_for("bollinger", 20),
    "bollinger_upper": warmup_for("bollinger", 20),
    "bollinger_lower": warmup_for("bollinger", 20),
    "macd": warmup_for("macd", 26),
    "macd_signal": warmup_for("macd", 26),
    "macd_histogram": warmup_for("macd", 26),
    "adx_14": warmup_for("adx", 14),
    "plus_di_14": warmup_for("adx", 14),
    "minus_di_14": warmup_for("adx", 14),
}
PREFERRED_EMA200_WARMUP = warmup_for("ema", 200)


def required_history(keys: Sequence[str] | None = None) -> int:
    """Closed candles needed for every requested indicator to be trustworthy."""
    selected = list(keys) if keys else list(INDICATOR_MINIMUMS)
    return max((INDICATOR_MINIMUMS.get(key, 0) for key in selected), default=0)



# --------------------------------------------------------------------------
# Candle helpers
# --------------------------------------------------------------------------
def _closed(candles: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop an explicitly forming candle. Feeds without the flag pass through."""
    rows = list(candles or [])
    while rows and rows[-1].get("closed") is False:
        rows.pop()
    return rows


def _num(candle: dict[str, Any], key: str) -> float:
    try:
        return float(candle.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _valid_ohlc(candle: dict[str, Any]) -> bool:
    o, h, l, c = (_num(candle, k) for k in ("open", "high", "low", "close"))
    return min(o, h, l, c) > 0 and h >= max(o, c) and l <= min(o, c) and h >= l


def _closes(candles: Sequence[dict[str, Any]]) -> list[float]:
    return [_num(c, "close") for c in _closed(candles) if _num(c, "close") > 0]


# --------------------------------------------------------------------------
# Moving averages
# --------------------------------------------------------------------------
def sma(values: Sequence[float], period: int) -> float | None:
    period = max(1, int(period))
    if len(values) < period:
        return None
    window = list(values)[-period:]
    return sum(window) / period


def ema_series(values: Sequence[float], period: int) -> list[float]:
    """EMA seeded with the SMA of the first ``period`` values (standard practice).

    Returns one EMA value per input value from index ``period - 1`` onwards.
    """
    period = max(1, int(period))
    data = list(values)
    if len(data) < period:
        return []
    alpha = 2.0 / (period + 1.0)
    seed = sum(data[:period]) / period
    out = [seed]
    for value in data[period:]:
        seed = alpha * value + (1 - alpha) * seed
        out.append(seed)
    return out


def ema(values: Sequence[float], period: int) -> float | None:
    series = ema_series(values, period)
    return series[-1] if series else None


def wilder_smooth(values: Sequence[float], period: int) -> list[float]:
    """Wilder's smoothing (a.k.a. RMA / Modified Moving Average).

    ``first = mean(values[:period])`` then
    ``next = (previous * (period - 1) + value) / period``.
    """
    period = max(1, int(period))
    data = list(values)
    if len(data) < period:
        return []
    current = sum(data[:period]) / period
    out = [current]
    for value in data[period:]:
        current = (current * (period - 1) + value) / period
        out.append(current)
    return out


# --------------------------------------------------------------------------
# RSI (Wilder, 1978)
# --------------------------------------------------------------------------
def rsi_series(values: Sequence[float], period: int = 14) -> list[float]:
    period = max(1, int(period))
    data = [float(v) for v in values]
    if len(data) < period + 1:
        return []
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(data, data[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = wilder_smooth(gains, period)
    avg_loss = wilder_smooth(losses, period)
    out: list[float] = []
    for gain, loss in zip(avg_gain, avg_loss):
        if loss <= 0:
            out.append(100.0 if gain > 0 else 50.0)
        elif gain <= 0:
            out.append(0.0)
        else:
            out.append(100.0 - (100.0 / (1.0 + gain / loss)))
    return out


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    """Standard Wilder RSI. Returns ``None`` before the calculation is defined."""
    series = rsi_series(values, period)
    return series[-1] if series else None


# --------------------------------------------------------------------------
# True range / ATR (Wilder)
# --------------------------------------------------------------------------
def true_ranges(candles: Sequence[dict[str, Any]]) -> list[float]:
    rows = [c for c in _closed(candles) if _valid_ohlc(c)]
    out: list[float] = []
    previous_close: float | None = None
    for candle in rows:
        high, low, close = (_num(candle, k) for k in ("high", "low", "close"))
        if previous_close is None:
            out.append(high - low)
        else:
            out.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = close
    return out


def atr_series(candles: Sequence[dict[str, Any]], period: int = 14) -> list[float]:
    # The first TR has no previous close; Wilder's original series starts from
    # the first *complete* true range, so drop the seed bar.
    ranges = true_ranges(candles)[1:]
    return wilder_smooth(ranges, period)


def atr(candles: Sequence[dict[str, Any]], period: int = 14) -> float | None:
    """Standard Wilder ATR (not a simple mean of recent ranges)."""
    series = atr_series(candles, period)
    return series[-1] if series else None


# --------------------------------------------------------------------------
# ADX / DMI (Wilder)
# --------------------------------------------------------------------------
def dmi(candles: Sequence[dict[str, Any]], period: int = 14) -> dict[str, Any]:
    """Full Wilder directional-movement system.

    Returns ``plus_di``, ``minus_di``, ``adx``, ``dx`` and the underlying series.
    Any value that is not yet mathematically defined is ``None``.
    """
    period = max(1, int(period))
    rows = [c for c in _closed(candles) if _valid_ohlc(c)]
    empty = {"plus_di": None, "minus_di": None, "adx": None, "dx": None,
             "plus_di_series": [], "minus_di_series": [], "adx_series": [], "period": period}
    if len(rows) < period + 2:
        return empty

    plus_dm: list[float] = []
    minus_dm: list[float] = []
    tr: list[float] = []
    for previous, current in zip(rows, rows[1:]):
        high, low = _num(current, "high"), _num(current, "low")
        previous_high, previous_low = _num(previous, "high"), _num(previous, "low")
        previous_close = _num(previous, "close")
        up_move = high - previous_high
        down_move = previous_low - low
        plus_dm.append(up_move if (up_move > down_move and up_move > 0) else 0.0)
        minus_dm.append(down_move if (down_move > up_move and down_move > 0) else 0.0)
        tr.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))

    smooth_tr = wilder_smooth(tr, period)
    smooth_plus = wilder_smooth(plus_dm, period)
    smooth_minus = wilder_smooth(minus_dm, period)
    if not smooth_tr:
        return empty

    plus_di: list[float] = []
    minus_di: list[float] = []
    dx: list[float] = []
    for total_range, up, down in zip(smooth_tr, smooth_plus, smooth_minus):
        if total_range <= 0:
            plus_di.append(0.0)
            minus_di.append(0.0)
            dx.append(0.0)
            continue
        pdi = 100.0 * up / total_range
        mdi = 100.0 * down / total_range
        plus_di.append(pdi)
        minus_di.append(mdi)
        denominator = pdi + mdi
        dx.append(100.0 * abs(pdi - mdi) / denominator if denominator > 0 else 0.0)

    adx_series = wilder_smooth(dx, period)
    return {
        "plus_di": plus_di[-1] if plus_di else None,
        "minus_di": minus_di[-1] if minus_di else None,
        "dx": dx[-1] if dx else None,
        "adx": adx_series[-1] if adx_series else None,
        "plus_di_series": plus_di,
        "minus_di_series": minus_di,
        "adx_series": adx_series,
        "period": period,
    }


def adx(candles: Sequence[dict[str, Any]], period: int = 14) -> float | None:
    """Standard Wilder ADX."""
    return dmi(candles, period).get("adx")


#: Graded ADX interpretation. 20-25 is transitional, not "confirmed trend".
ADX_BANDS = (
    (0.0, 15.0, "NO_TREND"),
    (15.0, 20.0, "WEAK"),
    (20.0, 25.0, "DEVELOPING"),
    (25.0, 40.0, "TRENDING"),
    (40.0, 60.0, "STRONG_TREND"),
    (60.0, 1e9, "EXTREME"),
)


def adx_band(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    for low, high, label in ADX_BANDS:
        if low <= value < high:
            return label
    return "UNKNOWN"


# --------------------------------------------------------------------------
# MACD
# --------------------------------------------------------------------------
def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> dict[str, Any]:
    """Standard MACD with explicit state, not just a histogram sign."""
    data = [float(v) for v in values]
    empty = {
        "macd": None, "signal": None, "histogram": None,
        "zero_line_state": None, "cross": None, "histogram_slope": None,
        "fast": fast, "slow": slow, "signal_period": signal,
    }
    fast_series = ema_series(data, fast)
    slow_series = ema_series(data, slow)
    if not fast_series or not slow_series:
        return empty
    # Align: the slow EMA starts later, so trim the fast EMA from the front.
    offset = len(fast_series) - len(slow_series)
    fast_series = fast_series[offset:]
    macd_line = [f - s for f, s in zip(fast_series, slow_series)]
    signal_series = ema_series(macd_line, signal)
    if not signal_series:
        return {**empty, "macd": macd_line[-1]}
    aligned_macd = macd_line[len(macd_line) - len(signal_series):]
    histogram = [m - s for m, s in zip(aligned_macd, signal_series)]

    cross = None
    if len(histogram) >= 2:
        if histogram[-2] <= 0 < histogram[-1]:
            cross = "BULLISH_CROSS"
        elif histogram[-2] >= 0 > histogram[-1]:
            cross = "BEARISH_CROSS"
        else:
            cross = "NO_CROSS"
    slope = None
    if len(histogram) >= 2:
        slope = histogram[-1] - histogram[-2]
    return {
        "macd": aligned_macd[-1],
        "signal": signal_series[-1],
        "histogram": histogram[-1],
        "zero_line_state": "ABOVE" if aligned_macd[-1] > 0 else "BELOW" if aligned_macd[-1] < 0 else "AT",
        "cross": cross,
        "histogram_slope": slope,
        "histogram_series": histogram,
        "fast": fast,
        "slow": slow,
        "signal_period": signal,
    }


# --------------------------------------------------------------------------
# Bollinger bands
# --------------------------------------------------------------------------
def bollinger(values: Sequence[float], period: int = 20, deviations: float = 2.0) -> dict[str, Any]:
    period = max(2, int(period))
    data = [float(v) for v in values]
    if len(data) < period:
        return {"middle": None, "upper": None, "lower": None, "width": None,
                "percent_b": None, "period": period, "deviations": deviations}
    window = data[-period:]
    middle = sum(window) / period
    variance = sum((value - middle) ** 2 for value in window) / period
    deviation = variance ** 0.5
    upper = middle + deviations * deviation
    lower = middle - deviations * deviation
    span = upper - lower
    return {
        "middle": middle,
        "upper": upper,
        "lower": lower,
        "stddev": deviation,
        "width": (span / middle) if middle else None,
        "percent_b": ((data[-1] - lower) / span) if span > 0 else None,
        "period": period,
        "deviations": deviations,
    }


# --------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------
def snapshot(candles: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Compute every indicator the engine uses from one closed-candle series.

    A value is ``None`` whenever the underlying calculation is not yet defined
    or not yet warmed up -- never a placeholder number.
    """
    rows = _closed(candles)
    values = _closes(rows)
    available = len(values)
    readiness = {key: available >= minimum for key, minimum in INDICATOR_MINIMUMS.items()}

    if available < 2:
        return {
            "status": "insufficient",
            "available_candles": available,
            "readiness": {key: False for key in INDICATOR_MINIMUMS},
            "minimums": dict(INDICATOR_MINIMUMS),
        }

    def gated(key: str, value: Any) -> Any:
        return value if readiness.get(key) else None

    macd_state = macd(values)
    bands = bollinger(values, 20, 2.0)
    directional = dmi(rows, 14)
    atr_value = atr(rows, 14)
    rsi_value = rsi(values, 14)

    result: dict[str, Any] = {
        "status": "ready" if all(readiness.values()) else "insufficient",
        "available_candles": available,
        "preferred_warmup_complete": available >= PREFERRED_EMA200_WARMUP,
        "readiness": readiness,
        "minimums": dict(INDICATOR_MINIMUMS),
        "ema_20": gated("ema_20", ema(values, 20)),
        "ema_50": gated("ema_50", ema(values, 50)),
        "ema_200": gated("ema_200", ema(values, 200)),
        "rsi_14": gated("rsi_14", rsi_value),
        "atr_14": gated("atr_14", atr_value),
        "bollinger_middle": gated("bollinger_middle", bands["middle"]),
        "bollinger_upper": gated("bollinger_upper", bands["upper"]),
        "bollinger_lower": gated("bollinger_lower", bands["lower"]),
        "bollinger_width": gated("bollinger_middle", bands.get("width")),
        "bollinger_percent_b": gated("bollinger_middle", bands.get("percent_b")),
        "macd": gated("macd", macd_state["macd"]),
        "macd_signal": gated("macd_signal", macd_state["signal"]),
        "macd_histogram": gated("macd_histogram", macd_state["histogram"]),
        "macd_zero_line": gated("macd", macd_state["zero_line_state"]),
        "macd_cross": gated("macd", macd_state["cross"]),
        "macd_histogram_slope": gated("macd_histogram", macd_state["histogram_slope"]),
        "adx_14": gated("adx_14", directional["adx"]),
        "plus_di_14": gated("plus_di_14", directional["plus_di"]),
        "minus_di_14": gated("minus_di_14", directional["minus_di"]),
        "adx_band": adx_band(directional["adx"]) if readiness.get("adx_14") else "UNKNOWN",
        "last_close": values[-1],
        "indicator_standard": {
            "rsi": "Wilder (1978) smoothed RSI",
            "atr": "Wilder (1978) smoothed ATR of true range",
            "adx": "Wilder (1978) +DM/-DM -> +DI/-DI -> DX -> smoothed ADX",
            "macd": "EMA(12) - EMA(26), signal EMA(9), SMA-seeded EMAs",
            "bollinger": "SMA(20) +/- 2 population standard deviations",
        },
    }
    return result
