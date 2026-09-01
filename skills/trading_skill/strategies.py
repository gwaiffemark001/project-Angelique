"""Strategy evidence models.

Each strategy defines:
  * its own **hard requirements** (binary gates that cannot be out-scored), and
  * its own **evidence families** (graded quality inside a family, so that
    correlated observations cannot each award full points).

Every strategy reads its timeframes from the ``TradingProfile`` -- nothing is
hard-coded to H1/M15/M5 any more, so switching DAY -> SWING genuinely changes
which data the strategy evaluates.
"""

from __future__ import annotations

from typing import Any, Sequence

from .indicators import adx_band
from .market_structure import BULLISH, BEARISH
from .strategy_evaluation import (
    CONTEXT, DERIVED, HARD, SOFT, StrategyEvaluation, DEFAULT_MINIMUM_QUALITY,
)

__all__ = [
    "evaluate_trend_following", "evaluate_momentum", "evaluate_breakout",
    "evaluate_mean_reversion", "evaluate_smc", "evaluate_amd",
    "evaluate_all", "STRATEGY_NAMES",
]

STRATEGY_NAMES = ("SMC", "AMD", "TREND_FOLLOWING", "MOMENTUM", "BREAKOUT", "MEAN_REVERSION")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _tf(profile: Any) -> dict[str, str]:
    return {
        "context": str(getattr(profile, "context_timeframe", "H4")),
        "trend": str(getattr(profile, "trend_timeframe", "H1")),
        "structure": str(getattr(profile, "structure_timeframe", "M15")),
        "setup": str(getattr(profile, "setup_timeframe", "M15")),
        "entry": str(getattr(profile, "entry_timeframe", "M5")),
    }


def _ind(indicators: dict[str, dict[str, Any]], timeframe: str) -> dict[str, Any]:
    return indicators.get(timeframe, {}) or {}


def _num(values: dict[str, Any], key: str) -> float | None:
    value = values.get(key)
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def _ready(values: dict[str, Any], keys: Sequence[str]) -> tuple[bool, list[str]]:
    """A key is ready when its warm-up is satisfied and it has a real value.

    Keys that are not warm-up gated (``last_close``, ``macd_zero_line`` ...)
    only need a value; requiring a readiness flag for them would block every
    strategy on a key that never appears in the readiness map.
    """
    readiness = values.get("readiness", {}) or {}
    missing: list[str] = []
    for key in keys:
        if values.get(key) is None:
            missing.append(key)
        elif key in readiness and not readiness[key]:
            missing.append(key)
    return not missing, missing


def _minimum(profile: Any) -> int:
    return int(getattr(profile, "minimum_quality_score", getattr(profile, "minimum_score", 0)) or 0) \
        or DEFAULT_MINIMUM_QUALITY


def _directional(value: Any, direction: str) -> bool:
    expected = BULLISH if direction == "BUY" else BEARISH
    return str(value or "").lower() == expected


def _blocked(name: str, profile: Any, timeframes: dict[str, str], missing: Sequence[str], why: str) -> StrategyEvaluation:
    evaluation = StrategyEvaluation(
        strategy_name=name, direction=None, data_status="insufficient",
        timeframe_context=timeframes, minimum_quality=_minimum(profile),
    )
    evaluation.note(why)
    if missing:
        evaluation.note(f"Missing inputs: {', '.join(missing)}.")
    return evaluation


def _graded(value: float | None, low: float, high: float) -> float:
    """Linear 0..1 grading between ``low`` (0) and ``high`` (1)."""
    if value is None:
        return 0.0
    if high <= low:
        return 1.0 if value >= high else 0.0
    return max(0.0, min(1.0, (value - low) / (high - low)))


# ==========================================================================
# TREND FOLLOWING
# ==========================================================================
def evaluate_trend_following(
    *, profile: Any, indicators: dict[str, dict[str, Any]], trends: dict[str, str],
    structure: dict[str, Any] | None = None, **_: Any,
) -> StrategyEvaluation:
    """Hard: EMA regime, trend strength, HTF agreement, pullback, not overextended."""
    timeframes = _tf(profile)
    trend_tf, setup_tf, entry_tf, context_tf = (
        timeframes["trend"], timeframes["setup"], timeframes["entry"], timeframes["context"],
    )
    values = _ind(indicators, trend_tf)
    ok, missing = _ready(values, ("ema_20", "ema_50", "ema_200", "adx_14", "plus_di_14", "minus_di_14", "atr_14", "last_close"))
    if not ok:
        return _blocked("TREND_FOLLOWING", profile, timeframes, missing,
                        f"{trend_tf} indicator history is not warmed up for trend following.")

    close = _num(values, "last_close") or 0.0
    ema20, ema50, ema200 = (_num(values, key) or 0.0 for key in ("ema_20", "ema_50", "ema_200"))
    adx = _num(values, "adx_14") or 0.0
    plus_di = _num(values, "plus_di_14") or 0.0
    minus_di = _num(values, "minus_di_14") or 0.0
    atr = _num(values, "atr_14") or 0.0

    bull = close > ema20 > ema50 > ema200
    bear = close < ema20 < ema50 < ema200
    direction = "BUY" if bull else "SELL" if bear else None

    evaluation = StrategyEvaluation(
        strategy_name="TREND_FOLLOWING", direction=direction,
        timeframe_context=timeframes, minimum_quality=_minimum(profile),
    )
    if direction is None:
        evaluation.require("ema_regime", "Directional EMA20/50/200 stack", False,
                           f"{trend_tf} EMAs are not stacked in either direction.")
        evaluation.note(f"{trend_tf} EMA structure is mixed; there is no trend to follow.")
        return evaluation

    directional_di = (plus_di > minus_di) if direction == "BUY" else (minus_di > plus_di)
    band = adx_band(adx)
    strong_enough = adx >= 25.0 and directional_di
    # Distance from the anchor EMA measured in ATR -- the extension test.
    extension_atr = abs(close - ema20) / atr if atr > 0 else float("inf")
    pullback = extension_atr <= 1.0
    htf_ok = _directional(trends.get(context_tf), direction) or _directional(trends.get(trend_tf), direction)

    # -- hard requirements --------------------------------------------------
    evaluation.require("ema_regime", "Directional EMA20/50/200 stack", True,
                       f"{trend_tf} EMA20={ema20:.6g} EMA50={ema50:.6g} EMA200={ema200:.6g}.")
    evaluation.require("trend_strength", "ADX >= 25 with agreeing DI", strong_enough,
                       f"ADX={adx:.1f} ({band}), +DI={plus_di:.1f}, -DI={minus_di:.1f}. "
                       "20-25 is transitional and is deliberately not accepted as a confirmed trend.")
    evaluation.require("htf_agreement", "Higher-timeframe agreement", htf_ok,
                       f"{context_tf}={trends.get(context_tf)}, {trend_tf}={trends.get(trend_tf)}.")
    evaluation.require("continuation_entry", "Fresh pullback / continuation entry", pullback,
                       f"Price is {extension_atr:.2f} ATR from EMA20; a trend that exists is not "
                       "the same thing as a low-risk entry.")
    evaluation.require("not_overextended", "Not excessively extended", extension_atr <= 3.0,
                       f"Extension {extension_atr:.2f} ATR from EMA20.")

    # -- graded evidence ----------------------------------------------------
    evaluation.observe("ema_separation", "trend_structure", "EMA separation quality",
                       _graded(abs(ema20 - ema50) / atr if atr > 0 else 0, 0.1, 1.0), 20,
                       SOFT, "Well-separated EMAs indicate an established trend.")
    evaluation.observe("adx_strength", "trend_strength", "Graded ADX strength",
                       _graded(adx, 20.0, 45.0), 20, SOFT, f"ADX={adx:.1f} ({band}).")
    evaluation.observe("di_spread", "trend_strength", "Directional index spread",
                       _graded(abs(plus_di - minus_di), 5.0, 30.0), 20, SOFT,
                       f"|+DI - -DI| = {abs(plus_di - minus_di):.1f}.")
    evaluation.observe("htf_context", "higher_timeframe", "Context timeframe alignment",
                       1.0 if _directional(trends.get(context_tf), direction) else 0.0, 15,
                       CONTEXT, f"{context_tf} trend = {trends.get(context_tf)}.")
    evaluation.observe("pullback_depth", "entry_timing", "Pullback proximity to anchor EMA",
                       1.0 - _graded(extension_atr, 0.0, 2.0), 25, SOFT,
                       f"{extension_atr:.2f} ATR from EMA20.")
    evaluation.observe("entry_alignment", "entry_timing", "Entry timeframe agreement",
                       1.0 if _directional(trends.get(entry_tf), direction) else 0.0, 25,
                       SOFT, f"{entry_tf} trend = {trends.get(entry_tf)}.")
    evaluation.observe("setup_alignment", "entry_timing", "Setup timeframe agreement",
                       1.0 if _directional(trends.get(setup_tf), direction) else 0.0, 25,
                       SOFT, f"{setup_tf} trend = {trends.get(setup_tf)}.")

    evaluation.plan_context.update({
        "anchor": ema20, "atr": atr, "extension_atr": extension_atr,
        "adx": adx, "adx_band": band, "plus_di": plus_di, "minus_di": minus_di,
        "stop_reference": ema50, "timeframe": trend_tf,
    })
    evaluation.note(f"{trend_tf} {'bullish' if direction == 'BUY' else 'bearish'} EMA regime with ADX {adx:.1f} ({band}).")
    return evaluation


# ==========================================================================
# MOMENTUM
# ==========================================================================
def evaluate_momentum(
    *, profile: Any, indicators: dict[str, dict[str, Any]], trends: dict[str, str], **_: Any,
) -> StrategyEvaluation:
    """Hard: directional momentum regime, RSI position, MACD confirmation, HTF context.

    Fixes the P0 bug where READY depended mainly on MACD + entry alignment while
    RSI and HTF failures were listed but ignored. All four are now hard gates.
    """
    timeframes = _tf(profile)
    setup_tf, entry_tf, trend_tf = timeframes["setup"], timeframes["entry"], timeframes["trend"]
    values = _ind(indicators, setup_tf)
    ok, missing = _ready(values, ("rsi_14", "macd", "macd_signal", "macd_histogram", "last_close"))
    if not ok:
        return _blocked("MOMENTUM", profile, timeframes, missing,
                        f"{setup_tf} momentum indicators are not warmed up.")

    rsi = _num(values, "rsi_14")
    macd_line = _num(values, "macd") or 0.0
    signal = _num(values, "macd_signal") or 0.0
    histogram = _num(values, "macd_histogram") or 0.0
    slope = _num(values, "macd_histogram_slope")
    zero_state = str(values.get("macd_zero_line") or "")

    bullish_macd = macd_line > signal and histogram > 0
    bearish_macd = macd_line < signal and histogram < 0
    direction = "BUY" if bullish_macd else "SELL" if bearish_macd else None

    evaluation = StrategyEvaluation(
        strategy_name="MOMENTUM", direction=direction,
        timeframe_context=timeframes, minimum_quality=_minimum(profile),
    )
    if direction is None or rsi is None:
        evaluation.require("momentum_regime", "MACD line/signal directional agreement", False,
                           f"MACD={macd_line:.6g}, signal={signal:.6g}, histogram={histogram:.6g}.")
        evaluation.note(f"{setup_tf} MACD is not in a directional momentum regime.")
        return evaluation

    # RSI is *contextual* momentum evidence. It is a hard gate only in the sense
    # that momentum must not be running against an exhausted reading.
    if direction == "BUY":
        rsi_supportive = rsi >= 50.0
        rsi_exhausted = rsi >= 80.0
    else:
        rsi_supportive = rsi <= 50.0
        rsi_exhausted = rsi <= 20.0

    htf_ok = _directional(trends.get(trend_tf), direction)
    entry_ok = _directional(trends.get(entry_tf), direction)
    zero_ok = (zero_state == "ABOVE") if direction == "BUY" else (zero_state == "BELOW")

    evaluation.require("momentum_regime", "MACD line/signal directional agreement", True,
                       f"MACD={macd_line:.6g} vs signal={signal:.6g}.")
    evaluation.require("rsi_quality", "RSI supports the momentum direction", rsi_supportive,
                       f"RSI={rsi:.1f}. A reading above 52 is not automatically a buy signal; "
                       "RSI is graded, and only a wrong-side reading is disqualifying.")
    evaluation.require("rsi_not_exhausted", "RSI is not at an exhaustion extreme", not rsi_exhausted,
                       f"RSI={rsi:.1f}.")
    evaluation.require("htf_context", "Higher-timeframe context agrees", htf_ok,
                       f"{trend_tf} trend = {trends.get(trend_tf)}.")
    evaluation.require("entry_confirmation", "Entry timeframe confirms", entry_ok,
                       f"{entry_tf} trend = {trends.get(entry_tf)}.")

    rsi_distance = abs(rsi - 50.0)
    evaluation.observe("rsi_position", "momentum_quality", "RSI distance from midline",
                       _graded(rsi_distance, 2.0, 25.0), 25, SOFT, f"RSI={rsi:.1f}.")
    evaluation.observe("macd_separation", "momentum_quality", "MACD/signal separation",
                       _graded(abs(macd_line - signal), 0.0, abs(macd_line) or 1e-9), 25, SOFT,
                       f"|MACD - signal| = {abs(macd_line - signal):.6g}.")
    evaluation.observe("histogram_slope", "momentum_quality", "Histogram is expanding",
                       1.0 if (slope is not None and ((slope > 0) == (direction == "BUY"))) else 0.0,
                       25, SOFT, f"Histogram slope = {slope}.")
    evaluation.observe("zero_line", "momentum_context", "MACD zero-line context",
                       1.0 if zero_ok else 0.0, 20, CONTEXT, f"MACD is {zero_state} zero.")
    evaluation.observe("htf_agreement", "higher_timeframe", "Trend timeframe agreement",
                       1.0 if htf_ok else 0.0, 15, CONTEXT, f"{trend_tf}={trends.get(trend_tf)}.")
    evaluation.observe("entry_agreement", "entry_timing", "Entry timeframe agreement",
                       1.0 if entry_ok else 0.0, 15, SOFT, f"{entry_tf}={trends.get(entry_tf)}.")

    evaluation.plan_context.update({"rsi": rsi, "macd": macd_line, "signal": signal,
                                    "histogram": histogram, "timeframe": setup_tf})
    evaluation.note(f"{setup_tf} MACD {'bullish' if direction == 'BUY' else 'bearish'} with RSI {rsi:.1f}.")
    return evaluation


# ==========================================================================
# BREAKOUT
# ==========================================================================
def evaluate_breakout(
    *, profile: Any, indicators: dict[str, dict[str, Any]], trends: dict[str, str],
    timeframes_data: dict[str, list[dict[str, Any]]] | None = None, **_: Any,
) -> StrategyEvaluation:
    """Hard: defined range, closed break, displacement, acceptance, viable target.

    Distinguishes a genuine break from a liquidity spike or a failed breakout,
    and the target produced here is the target the trade-level builder uses.
    """
    timeframes = _tf(profile)
    setup_tf, entry_tf, context_tf = timeframes["setup"], timeframes["entry"], timeframes["context"]
    values = _ind(indicators, setup_tf)
    candles = list((timeframes_data or {}).get(setup_tf, []) or [])
    while candles and candles[-1].get("closed") is False:
        candles.pop()

    ok, missing = _ready(values, ("atr_14", "last_close"))
    if not ok or len(candles) < 40:
        return _blocked("BREAKOUT", profile, timeframes,
                        missing or [f"{setup_tf} closed candles ({len(candles)}/40)"],
                        f"Insufficient {setup_tf} history for breakout analysis.")

    atr = _num(values, "atr_14") or 0.0
    range_window = candles[-21:-1]
    prior_window = candles[-41:-21]
    high = max(float(c.get("high", 0) or 0) for c in range_window)
    low = min(float(c.get("low", 0) or 0) for c in range_window)
    width = high - low
    last = candles[-1]
    close = float(last.get("close", 0) or 0)
    body = abs(close - float(last.get("open", 0) or 0))
    candle_range = float(last.get("high", 0) or 0) - float(last.get("low", 0) or 0)

    prior_width = (max(float(c.get("high", 0) or 0) for c in prior_window)
                   - min(float(c.get("low", 0) or 0) for c in prior_window)) if prior_window else 0.0

    direction = "BUY" if close > high else "SELL" if close < low else None
    evaluation = StrategyEvaluation(
        strategy_name="BREAKOUT", direction=direction,
        timeframe_context=timeframes, minimum_quality=_minimum(profile),
    )
    if direction is None or width <= 0 or atr <= 0:
        evaluation.require("closed_break", "Closed candle beyond the range", False,
                           f"Range {low:.6g}-{high:.6g}; last close {close:.6g}.")
        evaluation.note(f"{setup_tf} range {low:.6g}-{high:.6g} has not been broken by a closed candle.")
        return evaluation

    boundary = high if direction == "BUY" else low
    # Range quality: a meaningful, compressed, multi-touch range.
    touches = sum(
        1 for c in range_window
        if abs(float(c.get("high", 0) or 0) - high) <= atr * 0.25
        or abs(float(c.get("low", 0) or 0) - low) <= atr * 0.25
    )
    compression = (width / prior_width) if prior_width > 0 else 1.0
    range_defined = width >= atr * 1.0 and touches >= 3

    displacement = body >= atr * 1.0 and (body / candle_range if candle_range > 0 else 0) >= 0.55
    expansion = candle_range >= atr * 1.2
    # Acceptance: the break must be held, not immediately reclaimed. We use the
    # break candle's own close position within its range as the first proxy and
    # any follow-through candle beyond the boundary as confirmation.
    close_position = ((close - float(last.get("low", 0) or 0)) / candle_range) if candle_range > 0 else 0.5
    acceptance = (close_position >= 0.7) if direction == "BUY" else (close_position <= 0.3)
    penetration_atr = abs(close - boundary) / atr

    # Spike guard: a huge wick beyond the boundary with a weak body is a raid.
    wick_beyond = (float(last.get("high", 0) or 0) - close) if direction == "BUY" else (close - float(last.get("low", 0) or 0))
    spike = candle_range > 0 and (wick_beyond / candle_range) > 0.5
    htf_ok = _directional(trends.get(context_tf), direction) or trends.get(context_tf) in {None, "sideways", "unknown"}

    target = boundary + width if direction == "BUY" else boundary - width
    stop_reference = low if direction == "BUY" else high
    target_distance = abs(target - close)
    stop_distance = abs(close - stop_reference)
    target_viable = stop_distance > 0 and (target_distance / stop_distance) >= float(getattr(profile, "minimum_rr", 2.0))

    evaluation.require("range_defined", "A genuine, tested range exists", range_defined,
                       f"Range width {width:.6g} ({width / atr:.1f} ATR) with {touches} boundary touches.")
    evaluation.require("closed_break", "Closed candle beyond the range boundary", True,
                       f"Close {close:.6g} vs boundary {boundary:.6g} ({penetration_atr:.2f} ATR beyond).")
    evaluation.require("displacement", "Break candle displaced", displacement,
                       f"Body {body:.6g} = {body / atr:.2f} ATR, body ratio {body / candle_range if candle_range else 0:.2f}.")
    evaluation.require("not_a_spike", "Break is not a liquidity spike", not spike,
                       f"Wick beyond the close is {wick_beyond / candle_range if candle_range else 0:.0%} of the candle range.")
    evaluation.require("acceptance", "Break was accepted, not rejected", acceptance,
                       f"Close sits at {close_position:.0%} of the break candle's range.")
    evaluation.require("target_available", "A structurally viable target exists", target_viable,
                       f"Measured-move target {target:.6g} gives RR "
                       f"{(target_distance / stop_distance) if stop_distance else 0:.2f}.")

    evaluation.observe("range_quality", "range", "Range definition quality",
                       _graded(touches, 2, 8), 20, SOFT, f"{touches} boundary touches.")
    evaluation.observe("compression", "range", "Pre-break compression",
                       1.0 - _graded(compression, 0.5, 1.5), 20, SOFT,
                       f"Range is {compression:.2f}x the preceding window.")
    evaluation.observe("displacement_size", "break_quality", "Displacement magnitude",
                       _graded(body / atr, 0.8, 2.5), 25, SOFT, f"Body = {body / atr:.2f} ATR.")
    evaluation.observe("expansion", "break_quality", "Volatility expansion",
                       1.0 if expansion else 0.0, 25, SOFT, f"Candle range = {candle_range / atr:.2f} ATR.")
    evaluation.observe("penetration", "break_quality", "Break penetration depth",
                       _graded(penetration_atr, 0.1, 1.0), 25, SOFT, f"{penetration_atr:.2f} ATR beyond the boundary.")
    evaluation.observe("htf_context", "higher_timeframe", "Higher-timeframe context",
                       1.0 if _directional(trends.get(context_tf), direction) else 0.5 if htf_ok else 0.0,
                       15, CONTEXT, f"{context_tf}={trends.get(context_tf)}.")
    evaluation.observe("entry_confirmation", "entry_timing", "Entry timeframe agreement",
                       1.0 if _directional(trends.get(entry_tf), direction) else 0.0, 20,
                       SOFT, f"{entry_tf}={trends.get(entry_tf)}.")

    # The plan context IS the plan: the trade-level builder must consume this
    # target rather than silently recomputing a different one.
    evaluation.plan_context.update({
        "break_level": boundary, "range_high": high, "range_low": low, "range_width": width,
        "target": target, "target_basis": f"Measured move: range width ({width:.6g}) projected from the break level",
        "stop_reference": stop_reference,
        "stop_basis": f"Opposite side of the broken {setup_tf} range",
        "atr": atr, "timeframe": setup_tf,
    })
    evaluation.note(f"{setup_tf} range {low:.6g}-{high:.6g} broken to the "
                    f"{'upside' if direction == 'BUY' else 'downside'} with {body / atr:.2f} ATR displacement.")
    return evaluation


# ==========================================================================
# MEAN REVERSION
# ==========================================================================
def evaluate_mean_reversion(
    *, profile: Any, indicators: dict[str, dict[str, Any]], trends: dict[str, str],
    timeframes_data: dict[str, list[dict[str, Any]]] | None = None, **_: Any,
) -> StrategyEvaluation:
    """Hard: range regime, meaningful excursion, reversal evidence, viable target.

    Being outside a Bollinger band with an extreme RSI is not a reversal --
    price can stay there for the entire duration of a trend. Actual re-entry /
    rejection evidence is now required.
    """
    timeframes = _tf(profile)
    setup_tf, entry_tf, trend_tf = timeframes["setup"], timeframes["entry"], timeframes["trend"]
    values = _ind(indicators, setup_tf)
    ok, missing = _ready(values, ("bollinger_upper", "bollinger_lower", "bollinger_middle",
                                  "rsi_14", "adx_14", "atr_14", "last_close"))
    if not ok:
        return _blocked("MEAN_REVERSION", profile, timeframes, missing,
                        f"{setup_tf} mean-reversion indicators are not warmed up.")

    candles = list((timeframes_data or {}).get(setup_tf, []) or [])
    while candles and candles[-1].get("closed") is False:
        candles.pop()

    close = _num(values, "last_close") or 0.0
    upper = _num(values, "bollinger_upper") or 0.0
    lower = _num(values, "bollinger_lower") or 0.0
    middle = _num(values, "bollinger_middle") or 0.0
    rsi = _num(values, "rsi_14") or 50.0
    adx = _num(values, "adx_14") or 0.0
    atr = _num(values, "atr_14") or 0.0
    percent_b = _num(values, "bollinger_percent_b")

    # Excursion is measured on the *previous* candle so that "re-entry" is
    # something that actually happened rather than a coincidence of the moment.
    previous_close = float(candles[-2].get("close", 0) or 0) if len(candles) >= 2 else close
    previous_low = float(candles[-2].get("low", 0) or 0) if len(candles) >= 2 else close
    previous_high = float(candles[-2].get("high", 0) or 0) if len(candles) >= 2 else close

    below = previous_low <= lower or previous_close <= lower
    above = previous_high >= upper or previous_close >= upper
    direction = "BUY" if below and not above else "SELL" if above and not below else None

    evaluation = StrategyEvaluation(
        strategy_name="MEAN_REVERSION", direction=direction,
        timeframe_context=timeframes, minimum_quality=_minimum(profile),
    )
    if direction is None or atr <= 0 or middle <= 0:
        evaluation.require("excursion", "Meaningful excursion from the mean", False,
                           f"Close {close:.6g} vs bands {lower:.6g}/{upper:.6g}.")
        evaluation.note(f"{setup_tf} price is not at a mean-reversion extreme.")
        return evaluation

    # HARD GATE: the regime must not be trending. This is not a score item.
    range_regime = adx < 20.0 and not _directional(trends.get(trend_tf), "BUY") \
        and not _directional(trends.get(trend_tf), "SELL")
    trend_conflict = _directional(trends.get(trend_tf), "BUY" if direction == "SELL" else "SELL")

    # Reversal evidence: price closed back inside the band, and the candle
    # rejected the extreme with a wick.
    reentry = (close > lower) if direction == "BUY" else (close < upper)
    last = candles[-1] if candles else {}
    high, low = float(last.get("high", 0) or 0), float(last.get("low", 0) or 0)
    open_price = float(last.get("open", 0) or 0)
    candle_range = max(high - low, 1e-12)
    lower_wick = min(open_price, close) - low
    upper_wick = high - max(open_price, close)
    rejection = (lower_wick / candle_range >= 0.4) if direction == "BUY" else (upper_wick / candle_range >= 0.4)
    momentum_turn = (rsi > 30.0 and close > previous_close) if direction == "BUY" \
        else (rsi < 70.0 and close < previous_close)

    target = middle
    stop_reference = (min(low, previous_low) - atr * 0.25) if direction == "BUY" else (max(high, previous_high) + atr * 0.25)
    stop_distance = abs(close - stop_reference)
    target_distance = abs(target - close)
    target_viable = stop_distance > 0 and (target_distance / stop_distance) >= float(getattr(profile, "minimum_rr", 2.0))

    evaluation.require("range_regime", "Non-trending regime", range_regime,
                       f"ADX={adx:.1f} ({adx_band(adx)}), {trend_tf} trend={trends.get(trend_tf)}. "
                       "Mean reversion is only valid outside a directional regime.")
    evaluation.require("no_trend_conflict", "No opposing higher-timeframe trend", not trend_conflict,
                       f"{trend_tf} trend = {trends.get(trend_tf)}.")
    evaluation.require("excursion", "Meaningful excursion beyond the band", True,
                       f"%B = {percent_b if percent_b is not None else 'n/a'}.")
    evaluation.require("reversal_evidence", "Price re-entered the band", reentry,
                       f"Close {close:.6g} vs band {lower if direction == 'BUY' else upper:.6g}.")
    evaluation.require("target_available", "Mean target gives acceptable RR", target_viable,
                       f"Target {target:.6g} gives RR {(target_distance / stop_distance) if stop_distance else 0:.2f}.")

    evaluation.observe("band_excursion", "excursion", "Depth beyond the band",
                       _graded(abs(close - (lower if direction == "BUY" else upper)) / atr, 0.0, 1.0),
                       20, SOFT, f"{abs(close - (lower if direction == 'BUY' else upper)) / atr:.2f} ATR beyond band.")
    evaluation.observe("rsi_extreme", "excursion", "RSI extreme",
                       _graded(35.0 - rsi, 0.0, 15.0) if direction == "BUY" else _graded(rsi - 65.0, 0.0, 15.0),
                       20, SOFT, f"RSI={rsi:.1f}.")
    evaluation.observe("rejection_wick", "reversal", "Rejection wick at the extreme",
                       1.0 if rejection else 0.0, 30, SOFT,
                       f"Wick ratio {(lower_wick if direction == 'BUY' else upper_wick) / candle_range:.2f}.")
    evaluation.observe("momentum_turn", "reversal", "Momentum turning back to the mean",
                       1.0 if momentum_turn else 0.0, 30, SOFT, f"RSI={rsi:.1f}, close vs previous close.")
    evaluation.observe("regime_quality", "regime", "Range-regime quality",
                       1.0 - _graded(adx, 10.0, 25.0), 25, CONTEXT, f"ADX={adx:.1f}.")
    evaluation.observe("entry_confirmation", "entry_timing", "Entry timeframe is not opposing",
                       0.0 if _directional(trends.get(entry_tf), "BUY" if direction == "SELL" else "SELL") else 1.0,
                       15, SOFT, f"{entry_tf}={trends.get(entry_tf)}.")

    evaluation.plan_context.update({
        "target": target, "target_basis": f"{setup_tf} Bollinger middle band (mean)",
        "stop_reference": stop_reference,
        "stop_basis": f"Beyond the {setup_tf} excursion extreme + 0.25 ATR",
        "upper_band": upper, "lower_band": lower, "atr": atr, "timeframe": setup_tf,
        "zone": {"low": min(close, lower), "high": max(close, lower)} if direction == "BUY"
        else {"low": min(close, upper), "high": max(close, upper)},
    })
    evaluation.note(f"{setup_tf} mean-reversion candidate: ADX {adx:.1f}, RSI {rsi:.1f}, "
                    f"{'lower' if direction == 'BUY' else 'upper'} band excursion with re-entry={reentry}.")
    return evaluation


# ==========================================================================
# SMC
# ==========================================================================
def evaluate_smc(
    *, profile: Any, indicators: dict[str, dict[str, Any]], trends: dict[str, str],
    smc: dict[str, dict[str, Any]] | None = None, session: dict[str, Any] | None = None, **_: Any,
) -> StrategyEvaluation:
    """Nine evidence families; hard gate on a protected-swing structure break.

    Evidence families (correlated manifestations of the same impulse share a
    family and therefore share its weight budget):
      1 higher-timeframe structure   2 liquidity event      3 structure break
      4 directional zone             5 dealing-range location
      6 displacement quality         7 entry-timeframe confirmation
      8 execution timing             9 setup freshness
    """
    timeframes = _tf(profile)
    setup_tf, entry_tf, context_tf, trend_tf = (
        timeframes["setup"], timeframes["entry"], timeframes["context"], timeframes["trend"],
    )
    smc = smc or {}
    setup = smc.get(setup_tf, {}) or {}
    entry = smc.get(entry_tf, {}) or {}

    if setup.get("status") != "ready":
        return _blocked("SMC", profile, timeframes, [f"{setup_tf} SMC analysis"],
                        setup.get("reason") or f"{setup_tf} SMC analysis is unavailable.")

    structure = setup.get("market_structure", {}) or {}
    event = structure.get("last_event") or {}
    bias = str(structure.get("bias") or "")
    sweep = setup.get("liquidity_sweep") or {}
    dealing_range = setup.get("dealing_range") or {}
    gaps = [g for g in (setup.get("fair_value_gaps") or []) if isinstance(g, dict)]
    block = setup.get("order_block") if isinstance(setup.get("order_block"), dict) else None
    continuation = setup.get("continuation") or {}

    direction = None
    if event.get("direction") == BULLISH:
        direction = "BUY"
    elif event.get("direction") == BEARISH:
        direction = "SELL"
    elif bias in {BULLISH, BEARISH}:
        direction = "BUY" if bias == BULLISH else "SELL"

    evaluation = StrategyEvaluation(
        strategy_name="SMC", direction=direction,
        timeframe_context=timeframes, minimum_quality=_minimum(profile),
    )
    if direction is None:
        evaluation.require("protected_swing_break", "Closed break of a protected swing", False,
                           "No structure event has been recorded on the setup timeframe.")
        evaluation.note(f"{setup_tf} has no directional market-structure event.")
        return evaluation

    wanted = BULLISH if direction == "BUY" else BEARISH
    # --- hard requirement: a real, closed break of a PROTECTED swing --------
    break_ok = (
        bool(event)
        and event.get("direction") == wanted
        and event.get("confirmation") == "closed_candle"
        and event.get("broken_swing_index") is not None
    )
    # --- hard requirement: a real, unexpired directional zone ---------------
    directional_gaps = [
        g for g in gaps
        if g.get("type") == wanted
        and g.get("classification") in {"QUALIFIED_FVG", "TRADEABLE_FVG"}
        and g.get("status") in {"UNTOUCHED", "PARTIALLY_MITIGATED"}
    ]
    directional_block = bool(block and block.get("type") == wanted
                             and block.get("classification") == "TRADEABLE_OB")
    zone_ok = bool(directional_gaps or directional_block)

    location = str(dealing_range.get("location") or "")
    preferred_location = "discount" if direction == "BUY" else "premium"
    location_ok = location in {preferred_location, "equilibrium"}

    sweep_valid = bool(sweep.get("valid")) and sweep.get("implied_direction") == wanted
    displacement = (event.get("displacement") or {}) if isinstance(event.get("displacement"), dict) else {}
    zone = max(directional_gaps, key=lambda g: g.get("quality_score", 0)) if directional_gaps else None
    freshness = zone.get("age_candles") if zone else event.get("break_index")
    htf_ok = _directional(trends.get(context_tf), direction) or _directional(trends.get(trend_tf), direction)
    entry_ok = _directional(trends.get(entry_tf), direction) or str(
        (entry.get("market_structure") or {}).get("bias")
    ) == wanted
    in_kill_zone = bool((session or {}).get("in_kill_zone"))

    evaluation.require("protected_swing_break", "Closed break of a protected swing", break_ok,
                       f"{event.get('type')} {event.get('direction')} broke swing index "
                       f"{event.get('broken_swing_index')} at {event.get('broken_level')}. "
                       "A close above a five-candle high is deliberately NOT accepted.")
    evaluation.require("directional_zone", "Unexpired directional FVG or order block", zone_ok,
                       f"{len(directional_gaps)} qualified {wanted} FVG(s); "
                       f"tradeable OB = {directional_block}.")
    evaluation.require("dealing_range_location", "Price is not in the wrong half of the dealing range",
                       location_ok,
                       f"Location = {location or 'unknown'} (preferred {preferred_location}); "
                       f"range anchored to {dealing_range.get('basis')}.")
    evaluation.require("htf_agreement", "Higher-timeframe structure agrees", htf_ok,
                       f"{context_tf}={trends.get(context_tf)}, {trend_tf}={trends.get(trend_tf)}.")

    evaluation.observe("htf_structure", "higher_timeframe", "Higher-timeframe structure",
                       1.0 if _directional(trends.get(context_tf), direction) else
                       0.6 if _directional(trends.get(trend_tf), direction) else 0.0,
                       15, CONTEXT, f"{context_tf}={trends.get(context_tf)}, {trend_tf}={trends.get(trend_tf)}.")
    evaluation.observe("liquidity_event", "liquidity", "Meaningful liquidity raid",
                       1.0 if sweep_valid else 0.5 if sweep else 0.0, 15, SOFT,
                       f"{(sweep.get('pool') or {}).get('kind', 'none')} at "
                       f"{(sweep.get('pool') or {}).get('price', 'n/a')}.")
    evaluation.observe("structure_break", "structure", "Protected-swing break quality",
                       1.0 if (break_ok and event.get("type") == "CHoCH") else 0.85 if break_ok else 0.0,
                       15, SOFT, f"{event.get('type')} on {setup_tf}.")
    evaluation.observe("zone_quality", "entry_zone", "Entry-zone quality",
                       _graded(zone.get("quality_score", 0) if zone else (block or {}).get("quality_score", 0), 3.0, 9.0),
                       15, SOFT, f"Best zone score = {zone.get('quality_score') if zone else (block or {}).get('quality_score')}.")
    evaluation.observe("range_location", "location", "Premium/discount location",
                       1.0 if location == preferred_location else 0.5 if location == "equilibrium" else 0.0,
                       10, CONTEXT, f"Location = {location}.")
    ote = dealing_range.get("ote_zone")
    if isinstance(ote, (list, tuple)) and len(ote) == 2 and dealing_range.get("current_price") is not None:
        price = float(dealing_range["current_price"])
        evaluation.observe("ote", "location", "Price inside the OTE band",
                           1.0 if min(ote) <= price <= max(ote) else 0.0, 10, CONTEXT,
                           f"OTE {min(ote):.6g}-{max(ote):.6g}.")
    evaluation.observe("displacement", "displacement", "Displacement quality",
                       _graded(displacement.get("body_multiple") or 0, 1.0, 3.0), 10, SOFT,
                       f"Body multiple = {displacement.get('body_multiple')}.")
    evaluation.observe("entry_confirmation", "entry_timing", "Entry timeframe confirmation",
                       1.0 if entry_ok else 0.0, 10, SOFT, f"{entry_tf} confirms = {entry_ok}.")
    evaluation.observe("kill_zone", "execution_timing", "Execution timing window",
                       1.0 if in_kill_zone else 0.4, 5, CONTEXT,
                       f"Kill zones active: {(session or {}).get('kill_zones')}.")
    evaluation.observe("freshness", "freshness", "Setup freshness",
                       1.0 - _graded(freshness or 0, 0, 30), 10, SOFT,
                       f"Zone age = {freshness} candles.")

    evaluation.plan_context.update({
        "zone": {"low": zone.get("low"), "high": zone.get("high")} if zone else
                ({"low": block.get("low"), "high": block.get("high")} if block else None),
        "target": (setup.get("target_liquidity") or {}).get("price"),
        "target_basis": (setup.get("target_liquidity") or {}).get("basis"),
        "stop_reference": (zone or block or {}).get("invalidation_price"),
        "structure_event": event, "sweep": sweep, "dealing_range": dealing_range,
        "continuation": continuation, "timeframe": setup_tf,
    })
    evaluation.note(f"{setup_tf} {event.get('type')} {event.get('direction')} with "
                    f"{len(directional_gaps)} qualified zone(s) at {location or 'unknown'} location.")
    return evaluation


# ==========================================================================
# AMD
# ==========================================================================
def evaluate_amd(
    *, profile: Any, indicators: dict[str, dict[str, Any]], trends: dict[str, str],
    smc: dict[str, dict[str, Any]] | None = None, session: dict[str, Any] | None = None, **_: Any,
) -> StrategyEvaluation:
    """Every AMD phase is a hard requirement, and their ORDER is a hard requirement."""
    timeframes = _tf(profile)
    setup_tf, entry_tf, context_tf = timeframes["setup"], timeframes["entry"], timeframes["context"]
    setup = (smc or {}).get(setup_tf, {}) or {}
    amd = setup.get("amd", {}) or {}

    if amd.get("status") != "ready":
        return _blocked("AMD", profile, timeframes, ["AMD history"],
                        (amd.get("reasons") or ["Insufficient closed candles for AMD."])[0])

    direction = amd.get("trade_direction")
    phase_map = amd.get("phase_map", {}) or {}
    phases = {p.get("name"): p for p in (amd.get("phases") or []) if isinstance(p, dict)}

    evaluation = StrategyEvaluation(
        strategy_name="AMD", direction=direction if direction in {"BUY", "SELL"} else None,
        timeframe_context=timeframes, minimum_quality=_minimum(profile),
    )
    if direction not in {"BUY", "SELL"}:
        evaluation.require("accumulation", "Compressed accumulation range", bool(phase_map.get("ACCUMULATION")),
                           (phases.get("ACCUMULATION") or {}).get("reason", ""))
        evaluation.note("AMD sequence has not produced a directional bias.")
        return evaluation

    ordering_ok = True
    previous_end = -1
    for name in ("ACCUMULATION", "MANIPULATION", "REACTION", "DISTRIBUTION", "STRUCTURAL_DELIVERY"):
        phase = phases.get(name) or {}
        if not phase.get("complete"):
            continue
        end = phase.get("end_index")
        if end is None or end < previous_end:
            ordering_ok = False
            break
        previous_end = int(end)

    for key, label in (("ACCUMULATION", "Compressed accumulation range"),
                       ("MANIPULATION", "Liquidity raid of the range"),
                       ("REACTION", "Reclaim back inside the range"),
                       ("DISTRIBUTION", "Displacement in the raid direction"),
                       ("STRUCTURAL_DELIVERY", "Closed-candle structure break")):
        phase = phases.get(key) or {}
        evaluation.require(key.lower(), label, bool(phase.get("complete")), str(phase.get("reason", "")))
    evaluation.require("phase_ordering", "Phases occurred in strict order", ordering_ok,
                       "A later, unrelated candle can never retroactively complete an earlier phase.")
    expired = amd.get("age_candles") is not None and amd.get("expiry_index") is not None
    evaluation.require("not_expired", "Sequence has not expired",
                       not any("expired" in str(r).lower() for r in (amd.get("reasons") or [])),
                       f"Age = {amd.get('age_candles')} candles.")

    accumulation = phases.get("ACCUMULATION") or {}
    compression = (accumulation.get("detail") or {}).get("compression_ratio")
    displacement = (phases.get("DISTRIBUTION") or {}).get("detail") or {}

    evaluation.observe("accumulation_quality", "accumulation", "Accumulation compression",
                       1.0 - _graded(compression or 6.0, 2.0, 6.0), 20, SOFT,
                       f"Compression ratio = {compression}.")
    evaluation.observe("raid_quality", "manipulation", "Raid depth beyond the range",
                       1.0 if phase_map.get("MANIPULATION") else 0.0, 20, SOFT,
                       (phases.get("MANIPULATION") or {}).get("reason", ""))
    evaluation.observe("reaction_speed", "manipulation", "Reclaim speed",
                       1.0 if phase_map.get("REACTION") else 0.0, 20, SOFT,
                       (phases.get("REACTION") or {}).get("reason", ""))
    evaluation.observe("displacement_size", "distribution", "Displacement magnitude",
                       _graded(displacement.get("body_multiple") or 0, 1.2, 3.5), 25, SOFT,
                       f"Body multiple = {displacement.get('body_multiple')}.")
    evaluation.observe("delivery", "distribution", "Structural delivery confirmed",
                       1.0 if phase_map.get("STRUCTURAL_DELIVERY") else 0.0, 25, SOFT,
                       (phases.get("STRUCTURAL_DELIVERY") or {}).get("reason", ""))
    evaluation.observe("retracement", "entry_timing", "Price retraced into the delivery zone",
                       1.0 if (phases.get("RETRACEMENT_ENTRY") or {}).get("complete") else 0.0, 20,
                       SOFT, (phases.get("RETRACEMENT_ENTRY") or {}).get("reason", ""))
    evaluation.observe("htf_context", "higher_timeframe", "Higher-timeframe agreement",
                       1.0 if _directional(trends.get(context_tf), direction) else 0.0, 15,
                       CONTEXT, f"{context_tf}={trends.get(context_tf)}.")
    evaluation.observe("entry_confirmation", "entry_timing", "Entry timeframe agreement",
                       1.0 if _directional(trends.get(entry_tf), direction) else 0.0, 20,
                       SOFT, f"{entry_tf}={trends.get(entry_tf)}.")
    evaluation.observe("kill_zone", "execution_timing", "Execution timing window",
                       1.0 if (session or {}).get("in_kill_zone") else 0.4, 5, CONTEXT,
                       f"Kill zones: {(session or {}).get('kill_zones')}.")
    evaluation.observe("freshness", "freshness", "Sequence freshness",
                       1.0 - _graded(amd.get("age_candles") or 0, 0, 20), 10, SOFT,
                       f"Age = {amd.get('age_candles')} candles.")

    entry_phase = phases.get("RETRACEMENT_ENTRY") or {}
    zone_detail = entry_phase.get("detail") or {}
    evaluation.plan_context.update({
        "zone": {"low": zone_detail.get("zone_low"), "high": zone_detail.get("zone_high")}
        if zone_detail.get("zone_low") is not None else None,
        "stop_reference": amd.get("invalidation"),
        "stop_basis": "Beyond the AMD manipulation extreme",
        "range_high": amd.get("range_high"), "range_low": amd.get("range_low"),
        "phases": amd.get("phases"), "timeframe": setup_tf,
    })
    evaluation.note(f"{setup_tf} AMD {direction}: accumulation -> manipulation -> reaction -> "
                    f"distribution -> delivery, age {amd.get('age_candles')} candles.")
    return evaluation


# ==========================================================================
EVALUATORS = {
    "SMC": evaluate_smc,
    "AMD": evaluate_amd,
    "TREND_FOLLOWING": evaluate_trend_following,
    "MOMENTUM": evaluate_momentum,
    "BREAKOUT": evaluate_breakout,
    "MEAN_REVERSION": evaluate_mean_reversion,
}


def evaluate_all(**context: Any) -> list[StrategyEvaluation]:
    """Run every strategy through the same interface with the same inputs."""
    results: list[StrategyEvaluation] = []
    for name in STRATEGY_NAMES:
        evaluator = EVALUATORS[name]
        try:
            results.append(evaluator(**context))
        except Exception as exc:                                  # defensive: one bad strategy must not kill analysis
            failed = StrategyEvaluation(
                strategy_name=name, direction=None, data_status="unavailable",
                timeframe_context=_tf(context.get("profile")),
                minimum_quality=_minimum(context.get("profile")),
            )
            failed.block(f"{name} evaluation raised: {exc}")
            results.append(failed)
    return results
