"""Broker-authoritative profit / margin / volume calculation.

Policy enforced here
--------------------
* ``order_calc_profit`` (MT5) is the **only** trusted source of monetary P/L for
  automatic execution. Generic ``distance / tick_size * tick_value`` is an
  approximation that breaks for cross-currency and non-FX calculation modes.
* ``order_calc_margin`` (MT5) is the **only** trusted source of margin.
  ``contract_size * price / leverage`` is valid only for
  ``SYMBOL_CALC_MODE_FOREX`` and is never used for execution here.
* When the broker calculator is unavailable, or the symbol metadata is
  incomplete, execution is **blocked** with a precise blocker code. Nothing is
  guessed.

An *estimate* path exists for display-only contexts and is always labelled
``authoritative=False`` so the UI cannot present it as broker truth.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable, Protocol

from .instruments import InstrumentProfile, FOREX_CALC_MODES

# Blocker codes (mirrored in data_quality.Blocker)
BROKER_METADATA_INCOMPLETE = "BROKER_METADATA_INCOMPLETE"
BROKER_CALCULATION_UNAVAILABLE = "BROKER_CALCULATION_UNAVAILABLE"
INVALID_TRADE_PARAMETERS = "INVALID_TRADE_PARAMETERS"
VOLUME_OUT_OF_RANGE = "VOLUME_OUT_OF_RANGE"
RISK_CEILING_EXCEEDED = "RISK_CEILING_EXCEEDED"


class BrokerCalculator(Protocol):
    """Read-only broker calculation surface (maps to MT5 order_calc_*)."""

    def calculate_profit(self, symbol: str, direction: str, volume: float,
                         price_open: float, price_close: float) -> dict[str, Any]: ...

    def calculate_margin(self, symbol: str, direction: str, volume: float,
                         price: float) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CalcResult:
    ok: bool
    value: float | None
    authoritative: bool
    source: str
    blocker: str | None = None
    reason: str = ""
    detail: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def broker_profit(
    calculator: BrokerCalculator | None,
    profile: InstrumentProfile,
    direction: str,
    volume: float,
    price_open: float,
    price_close: float,
) -> CalcResult:
    """Profit/loss in account currency via MT5 ``order_calc_profit``."""
    direction = str(direction).upper()
    if direction not in {"BUY", "SELL"}:
        return CalcResult(False, None, False, "validation", INVALID_TRADE_PARAMETERS,
                          f"Direction '{direction}' is not BUY or SELL.")
    if not (volume > 0 and price_open > 0 and price_close > 0):
        return CalcResult(False, None, False, "validation", INVALID_TRADE_PARAMETERS,
                          "Volume, open price and close price must all be positive.")
    if calculator is None:
        return CalcResult(False, None, False, "none", BROKER_CALCULATION_UNAVAILABLE,
                          "No MT5 calculator is connected; order_calc_profit cannot be called.")
    try:
        response = calculator.calculate_profit(profile.symbol, direction, float(volume),
                                               float(price_open), float(price_close))
    except Exception as exc:                                     # pragma: no cover - transport
        return CalcResult(False, None, False, "order_calc_profit", BROKER_CALCULATION_UNAVAILABLE,
                          f"order_calc_profit raised: {exc}")
    if not isinstance(response, dict) or response.get("status") == "error" or response.get("error"):
        reason = (response or {}).get("error", "order_calc_profit returned an error.")
        return CalcResult(False, None, False, "order_calc_profit", BROKER_CALCULATION_UNAVAILABLE, str(reason))
    value = _num(response.get("profit", response.get("value")))
    if value is None:
        return CalcResult(False, None, False, "order_calc_profit", BROKER_CALCULATION_UNAVAILABLE,
                          "order_calc_profit returned no numeric value.")
    return CalcResult(True, value, True, "order_calc_profit", None,
                      "Profit calculated by the broker in account currency.", dict(response))


def broker_margin(
    calculator: BrokerCalculator | None,
    profile: InstrumentProfile,
    direction: str,
    volume: float,
    price: float,
) -> CalcResult:
    """Required margin in account currency via MT5 ``order_calc_margin``."""
    direction = str(direction).upper()
    if direction not in {"BUY", "SELL"}:
        return CalcResult(False, None, False, "validation", INVALID_TRADE_PARAMETERS,
                          f"Direction '{direction}' is not BUY or SELL.")
    if not (volume > 0 and price > 0):
        return CalcResult(False, None, False, "validation", INVALID_TRADE_PARAMETERS,
                          "Volume and price must be positive.")
    if calculator is None:
        return CalcResult(False, None, False, "none", BROKER_CALCULATION_UNAVAILABLE,
                          "No MT5 calculator is connected; order_calc_margin cannot be called.")
    try:
        response = calculator.calculate_margin(profile.symbol, direction, float(volume), float(price))
    except Exception as exc:                                     # pragma: no cover - transport
        return CalcResult(False, None, False, "order_calc_margin", BROKER_CALCULATION_UNAVAILABLE,
                          f"order_calc_margin raised: {exc}")
    if not isinstance(response, dict) or response.get("status") == "error" or response.get("error"):
        reason = (response or {}).get("error", "order_calc_margin returned an error.")
        return CalcResult(False, None, False, "order_calc_margin", BROKER_CALCULATION_UNAVAILABLE, str(reason))
    value = _num(response.get("margin", response.get("value")))
    if value is None or value < 0:
        return CalcResult(False, None, False, "order_calc_margin", BROKER_CALCULATION_UNAVAILABLE,
                          "order_calc_margin returned no usable value.")
    return CalcResult(True, value, True, "order_calc_margin", None,
                      "Margin calculated by the broker in account currency.", dict(response))


def estimate_profit(
    profile: InstrumentProfile,
    direction: str,
    volume: float,
    price_open: float,
    price_close: float,
) -> CalcResult:
    """Tick-value approximation. **Display only** -- never for execution.

    Uses ``trade_tick_value_profit`` / ``trade_tick_value_loss`` when the broker
    supplies them, because they differ for cross-currency instruments.
    """
    if profile.tick_size <= 0:
        return CalcResult(False, None, False, "estimate", BROKER_METADATA_INCOMPLETE,
                          "tick_size is missing; no estimate is possible.")
    move = float(price_close) - float(price_open)
    signed = move if str(direction).upper() == "BUY" else -move
    ticks = signed / profile.tick_size
    tick_value = profile.tick_value_profit if ticks >= 0 else profile.tick_value_loss
    tick_value = tick_value or profile.tick_value
    if not tick_value:
        return CalcResult(False, None, False, "estimate", BROKER_METADATA_INCOMPLETE,
                          "tick_value is missing; no estimate is possible.")
    return CalcResult(
        True, ticks * tick_value * float(volume), False, "tick_value_estimate", None,
        "APPROXIMATION from tick value; not broker-authoritative and unsafe for execution.",
        {"ticks": ticks, "tick_value_used": tick_value},
    )


def estimate_margin(profile: InstrumentProfile, volume: float, price: float, leverage: float) -> CalcResult:
    """Leverage approximation, valid only for FOREX calc modes. Display only."""
    if profile.trade_calc_mode not in FOREX_CALC_MODES:
        return CalcResult(
            False, None, False, "estimate", BROKER_CALCULATION_UNAVAILABLE,
            f"contract_size*price/leverage is not valid for trade_calc_mode="
            f"{profile.trade_calc_mode}; order_calc_margin is required.",
        )
    if not (profile.contract_size > 0 and leverage > 0 and price > 0 and volume > 0):
        return CalcResult(False, None, False, "estimate", BROKER_METADATA_INCOMPLETE,
                          "contract_size / leverage / price incomplete.")
    return CalcResult(
        True, profile.contract_size * float(volume) * float(price) / float(leverage), False,
        "leverage_estimate", None,
        "APPROXIMATION for FOREX calc mode only; not broker-authoritative.",
    )


# --------------------------------------------------------------------------
# Volume solving
# --------------------------------------------------------------------------
@dataclass
class VolumeSolution:
    ok: bool
    volume: float | None
    ideal_volume: float | None
    risk_amount_target: float
    risk_amount_actual: float | None
    risk_percent_actual: float | None
    loss_per_lot: float | None
    authoritative: bool
    source: str
    blocker: str | None
    reason: str
    iterations: int = 0
    detail: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def solve_volume_for_risk(
    calculator: BrokerCalculator | None,
    profile: InstrumentProfile,
    *,
    direction: str,
    entry: float,
    stop_loss: float,
    equity: float,
    risk_percent: float,
    max_risk_percent: float | None = None,
    require_broker: bool = True,
) -> VolumeSolution:
    """Solve for the largest broker-legal volume whose SL loss stays within budget.

    Procedure:
      1. Ask the broker what one lot loses between ``entry`` and ``stop_loss``
         for this exact direction (``order_calc_profit``).
      2. Divide the risk budget by that figure.
      3. Floor onto the broker's ``volume_step`` grid and clamp to
         ``volume_min``/``volume_max``.
      4. **Re-ask the broker** for the loss at the normalised volume and verify
         it is still inside the budget. Rounding is never assumed safe.
    """
    max_risk_percent = max_risk_percent if max_risk_percent is not None else risk_percent
    target = float(equity) * float(risk_percent) / 100.0

    if profile.missing_metadata:
        return VolumeSolution(False, None, None, target, None, None, None, False, "none",
                              BROKER_METADATA_INCOMPLETE,
                              f"Missing broker metadata: {', '.join(profile.missing_metadata)}.")
    if equity <= 0:
        return VolumeSolution(False, None, None, target, None, None, None, False, "none",
                              INVALID_TRADE_PARAMETERS, "Account equity is not positive.")
    distance = abs(float(entry) - float(stop_loss))
    if distance <= 0:
        return VolumeSolution(False, None, None, target, None, None, None, False, "none",
                              INVALID_TRADE_PARAMETERS, "Stop loss is not distinct from entry.")

    probe = profile.volume_min if profile.volume_min > 0 else 0.01
    first = broker_profit(calculator, profile, direction, probe, entry, stop_loss)
    if not first.ok:
        if require_broker:
            return VolumeSolution(False, None, None, target, None, None, None, False, first.source,
                                  first.blocker or BROKER_CALCULATION_UNAVAILABLE,
                                  f"Execution blocked: {first.reason} "
                                  "Automatic sizing requires broker-calculated P/L.")
        first = estimate_profit(profile, direction, probe, entry, stop_loss)
        if not first.ok:
            return VolumeSolution(False, None, None, target, None, None, None, False, first.source,
                                  first.blocker or BROKER_CALCULATION_UNAVAILABLE, first.reason)

    loss_at_probe = abs(float(first.value or 0.0))
    if loss_at_probe <= 0:
        return VolumeSolution(False, None, None, target, None, None, None, first.authoritative, first.source,
                              BROKER_CALCULATION_UNAVAILABLE,
                              "Broker reported zero loss at the stop; sizing cannot proceed.")
    loss_per_lot = loss_at_probe / probe
    ideal = target / loss_per_lot

    volume = profile.normalize_volume(ideal)
    iterations = 0
    if volume < profile.volume_min - 1e-12:
        return VolumeSolution(
            False, None, ideal, target, None, None, loss_per_lot, first.authoritative, first.source,
            VOLUME_OUT_OF_RANGE,
            f"Broker minimum volume {profile.volume_min} would risk more than the "
            f"{risk_percent:.2f}% budget (ideal volume {ideal:.6f}).",
        )

    # Verify -- and step down if the broker's own figure exceeds the ceiling.
    ceiling = float(equity) * float(max_risk_percent) / 100.0
    actual = None
    while volume >= profile.volume_min - 1e-12 and iterations < 50:
        iterations += 1
        check = (broker_profit(calculator, profile, direction, volume, entry, stop_loss)
                 if first.authoritative else
                 estimate_profit(profile, direction, volume, entry, stop_loss))
        if not check.ok:
            return VolumeSolution(False, None, ideal, target, None, None, loss_per_lot,
                                  first.authoritative, check.source,
                                  check.blocker or BROKER_CALCULATION_UNAVAILABLE, check.reason, iterations)
        actual = abs(float(check.value or 0.0))
        if actual <= ceiling + 1e-9:
            return VolumeSolution(
                ok=True, volume=volume, ideal_volume=ideal, risk_amount_target=target,
                risk_amount_actual=actual, risk_percent_actual=actual / float(equity) * 100.0,
                loss_per_lot=loss_per_lot, authoritative=first.authoritative, source=check.source,
                blocker=None,
                reason=("Volume solved and re-verified with the broker calculator."
                        if first.authoritative else
                        "Volume solved from a tick-value ESTIMATE; not valid for automatic execution."),
                iterations=iterations,
                detail={"probe_volume": probe, "probe_loss": loss_at_probe, "ceiling": ceiling},
            )
        volume = profile.normalize_volume(volume - profile.volume_step)

    return VolumeSolution(False, None, ideal, target, actual, None, loss_per_lot,
                          first.authoritative, first.source, RISK_CEILING_EXCEEDED,
                          "No broker-legal volume keeps the stop-loss risk inside the configured ceiling.",
                          iterations)
