"""Order preflight -- the last gate before an order is sent.

Everything computed during analysis is *stale by definition* by the time the
user clicks execute. This module revalidates the entire trade against live
broker state and refuses to send anything it cannot prove.

Sequence
--------
 1. Trade permissions       -- account and symbol trade modes
 2. Market state            -- symbol is open and quoting
 3. Freshness               -- the quote and the plan are recent enough
 4. Price drift             -- the market has not moved away from the plan
 5. Spread                  -- instrument-aware gate, recomputed on live tick
 6. Level revalidation      -- tick grid, stops_level, freeze_level, correct side
 7. Volume revalidation     -- broker-solved, broker-verified
 8. Margin                  -- ``order_calc_margin`` + resulting margin level
 9. Net economics           -- net RR after live spread/commission/swap
10. ``OrderCheck``          -- the broker's own verdict

Any failure returns a precise, machine-readable blocker. There is no
"proceed anyway" path.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any

from .broker_calc import (
    BROKER_CALCULATION_UNAVAILABLE, BROKER_METADATA_INCOMPLETE, INVALID_TRADE_PARAMETERS,
    VOLUME_OUT_OF_RANGE, broker_margin, broker_profit, solve_volume_for_risk,
)
from .costs import CostAssumptions, ExecutionPrices, estimate_costs, reward_to_risk
from .instruments import TRADE_MODE_FULL, build_profile
from .spread_model import evaluate_spread_gate, measure_spread, policy_for, spread_store
from .trade_levels import validate_levels_against_broker

# Blocker codes
MARKET_CLOSED = "MARKET_CLOSED"
TRADE_DISABLED = "TRADE_DISABLED"
QUOTE_STALE = "QUOTE_STALE"
PLAN_STALE = "PLAN_STALE"
PRICE_DRIFT = "PRICE_DRIFT"
SPREAD_UNACCEPTABLE = "SPREAD_UNACCEPTABLE"
STOPS_LEVEL_VIOLATION = "STOPS_LEVEL_VIOLATION"
INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"
MARGIN_LEVEL_TOO_LOW = "MARGIN_LEVEL_TOO_LOW"
NET_RR_BELOW_MINIMUM = "NET_RR_BELOW_MINIMUM"
ORDER_CHECK_FAILED = "ORDER_CHECK_FAILED"

#: MT5 TRADE_RETCODE_DONE / _PLACED are the only acceptable order_check results.
ACCEPTABLE_ORDER_CHECK_RETCODES = {0, 10009, 10008}


@dataclass
class Blocker:
    code: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreflightConfig:
    """All limits are configurable policy and are documented as such."""
    max_quote_age_seconds: float = 10.0
    max_plan_age_seconds: float = 300.0
    #: Allowed drift between the planned entry and the live executable price,
    #: expressed as a fraction of the stop distance.
    max_price_drift_ratio: float = 0.25
    minimum_free_margin: float = 0.0
    minimum_margin_level_percent: float = 200.0
    minimum_net_rr: float | None = None
    #: Automatic execution requires a computed NET RR after costs. A missing
    #: broker-side TP profit calculation is a hard blocker, not a warning.
    require_net_rr: bool = True
    stops_level_buffer_multiple: float = 1.5
    require_order_check: bool = True
    costs: CostAssumptions = field(default_factory=CostAssumptions)


@dataclass
class PreflightResult:
    approved: bool
    blockers: list[Blocker] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: The single authoritative execution object. The UI must render THIS.
    execution: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def block(self, code: str, message: str, **detail: Any) -> "PreflightResult":
        self.blockers.append(Blocker(code, message, detail))
        self.approved = False
        return self

    def check(self, message: str) -> "PreflightResult":
        self.checks.append(message)
        return self

    def warn(self, message: str) -> "PreflightResult":
        self.warnings.append(message)
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "blockers": [item.as_dict() for item in self.blockers],
            "blocker_codes": [item.code for item in self.blockers],
            "checks": list(self.checks),
            "warnings": list(self.warnings),
            "execution": dict(self.execution),
            "timestamp": self.timestamp,
        }


def _age_seconds(value: Any, now: datetime) -> float | None:
    from .session_levels import to_datetime
    moment = to_datetime(value)
    return (now - moment).total_seconds() if moment else None


def preflight(
    *,
    symbol: str,
    direction: str,
    specs: dict[str, Any],
    tick: dict[str, Any],
    plan: dict[str, Any],
    account: dict[str, Any],
    calculator: Any = None,
    order_checker: Any = None,
    config: PreflightConfig | None = None,
    session: str = "ALL",
    market_open: bool = True,
    now: datetime | None = None,
) -> PreflightResult:
    """Revalidate a trade plan against live broker state.

    ``plan`` must carry ``entry``, ``stop_loss``, ``take_profit``,
    ``risk_percent`` and ``generated_at``. ``tick`` must carry live ``bid``,
    ``ask`` and ``time``.
    """
    config = config or PreflightConfig()
    now = now or datetime.now(timezone.utc)
    result = PreflightResult(approved=True, timestamp=now.isoformat())
    direction = str(direction).upper()
    profile = build_profile(symbol, specs)

    # ---------------------------------------------------------------- 0. inputs
    if direction not in {"BUY", "SELL"}:
        return result.block(INVALID_TRADE_PARAMETERS, f"Direction '{direction}' is not BUY or SELL.")
    if profile.missing_metadata:
        return result.block(
            BROKER_METADATA_INCOMPLETE,
            f"{symbol} is missing required broker metadata: {', '.join(profile.missing_metadata)}. "
            "Automatic execution is blocked; no generic fallback is used.",
            missing=list(profile.missing_metadata),
        )
    result.check(f"{symbol} classified as {profile.instrument_class} from broker metadata "
                 f"(trade_calc_mode={profile.trade_calc_mode}).")

    # ---------------------------------------------------------- 1. permissions
    if not account.get("trade_allowed", True):
        result.block(TRADE_DISABLED, "The account does not currently allow trading.")
    if not account.get("trade_expert", True):
        result.block(TRADE_DISABLED, "Algorithmic trading is disabled on the terminal (AutoTrading off).")
    if profile.trade_mode is not None and profile.trade_mode != TRADE_MODE_FULL:
        result.block(TRADE_DISABLED,
                     f"{symbol} trade mode is {profile.trade_mode_name} "
                     "(full trading is not permitted on this symbol).")
    else:
        result.check(f"{symbol} trade mode = {profile.trade_mode_name}.")

    # --------------------------------------------------------- 2. market state
    if not market_open:
        result.block(MARKET_CLOSED, f"{symbol} is outside its trading session.")

    # ----------------------------------------------------------- 3. freshness
    quote_age = _age_seconds(tick.get("time"), now)
    if quote_age is None:
        result.warn("Tick timestamp missing; quote freshness could not be verified.")
    elif quote_age > config.max_quote_age_seconds:
        result.block(QUOTE_STALE,
                     f"Live quote is {quote_age:.1f}s old (limit {config.max_quote_age_seconds:.0f}s).",
                     quote_age_seconds=quote_age)
    else:
        result.check(f"Quote age {quote_age:.1f}s.")

    plan_age = _age_seconds(plan.get("generated_at"), now)
    if plan_age is not None and plan_age > config.max_plan_age_seconds:
        result.block(PLAN_STALE,
                     f"Trade plan is {plan_age:.0f}s old (limit {config.max_plan_age_seconds:.0f}s). "
                     "Re-run the analysis.",
                     plan_age_seconds=plan_age)
    elif plan_age is not None:
        result.check(f"Plan age {plan_age:.0f}s.")

    # ------------------------------------------------------------- 4. prices
    bid, ask = tick.get("bid"), tick.get("ask")
    measurement = measure_spread(profile, bid, ask)
    if not measurement.valid:
        return result.block(BROKER_CALCULATION_UNAVAILABLE, measurement.reason)
    spread_store.observe(measurement, session)
    prices = ExecutionPrices(direction, float(measurement.bid), float(measurement.ask))
    live_entry = prices.entry_price
    result.check(f"{direction} will execute at {'Ask' if direction == 'BUY' else 'Bid'} "
                 f"= {live_entry:.10g}.")

    planned_entry = float(plan.get("entry") or 0)
    stop_loss = float(plan.get("stop_loss") or 0)
    take_profit = float(plan.get("take_profit") or 0)
    if not (planned_entry > 0 and stop_loss > 0 and take_profit > 0):
        return result.block(INVALID_TRADE_PARAMETERS, "Plan is missing entry, stop loss or take profit.")

    stop_distance = abs(live_entry - stop_loss)
    drift = abs(live_entry - planned_entry)
    drift_ratio = drift / stop_distance if stop_distance > 0 else float("inf")
    if drift_ratio > config.max_price_drift_ratio:
        result.block(PRICE_DRIFT,
                     f"Price has moved {profile.format_distance(drift)} from the planned entry "
                     f"({drift_ratio * 100:.0f}% of the stop distance; limit "
                     f"{config.max_price_drift_ratio * 100:.0f}%).",
                     drift=drift, drift_ratio=drift_ratio)
    else:
        result.check(f"Price drift {profile.format_distance(drift)} "
                     f"({drift_ratio * 100:.0f}% of stop distance).")

    # ------------------------------------------------------------- 5. spread
    reward_distance = abs(take_profit - live_entry)
    gate = evaluate_spread_gate(
        profile, measurement, stop_distance_price=stop_distance,
        reward_distance_price=reward_distance, session=session,
        policy=policy_for(profile.instrument_class),
    )
    if not gate.allowed:
        result.block(SPREAD_UNACCEPTABLE, "; ".join(gate.reasons), **{"spread": gate.as_dict()})
    for line in gate.checks:
        result.check(line)

    # ------------------------------------------------------------- 6. levels
    validation = validate_levels_against_broker(
        profile, direction=direction, entry=live_entry, stop_loss=stop_loss,
        take_profit=take_profit, bid=measurement.bid, ask=measurement.ask,
        buffer_multiple=config.stops_level_buffer_multiple,
    )
    for line in validation.checks:
        (result.warn if line.startswith("WARNING") else result.check)(line)
    if not validation.valid:
        result.block(validation.blocker or STOPS_LEVEL_VIOLATION, "; ".join(validation.violations),
                     **validation.detail)
    stop_loss, take_profit = validation.stop_loss, validation.take_profit

    # ------------------------------------------------------------- 7. volume
    equity = float(account.get("equity") or account.get("balance") or 0)
    risk_percent = float(plan.get("risk_percent") or 0)
    solution = solve_volume_for_risk(
        calculator, profile, direction=direction, entry=live_entry, stop_loss=stop_loss,
        equity=equity, risk_percent=risk_percent,
        max_risk_percent=float(plan.get("max_risk_percent") or risk_percent),
        require_broker=True,
    )
    if not solution.ok:
        result.block(solution.blocker or BROKER_CALCULATION_UNAVAILABLE, solution.reason,
                     **(solution.detail or {}))
        volume = None
    else:
        volume = solution.volume
        result.check(f"Volume {volume} verified with the broker: stop-loss risk "
                     f"{solution.risk_amount_actual:.2f} ({solution.risk_percent_actual:.2f}% of equity), "
                     f"target {solution.risk_amount_target:.2f}.")

    # ------------------------------------------------------------- 8. margin
    margin_value = None
    if volume:
        margin = broker_margin(calculator, profile, direction, volume, live_entry)
        if not margin.ok:
            result.block(margin.blocker or BROKER_CALCULATION_UNAVAILABLE,
                         f"Margin could not be calculated by the broker: {margin.reason}")
        else:
            margin_value = float(margin.value or 0)
            free_margin = float(account.get("margin_free") or 0)
            remaining = free_margin - margin_value
            if remaining < config.minimum_free_margin:
                result.block(INSUFFICIENT_MARGIN,
                             f"Required margin {margin_value:.2f} leaves {remaining:.2f} free "
                             f"(minimum {config.minimum_free_margin:.2f}).",
                             required=margin_value, free_margin=free_margin)
            else:
                result.check(f"Broker margin {margin_value:.2f}; {remaining:.2f} free margin remains.")
            used = float(account.get("margin") or 0) + margin_value
            level = (equity / used * 100.0) if used > 0 else None
            if level is not None and level < config.minimum_margin_level_percent:
                result.block(MARGIN_LEVEL_TOO_LOW,
                             f"Projected margin level {level:.0f}% is below the "
                             f"{config.minimum_margin_level_percent:.0f}% minimum.",
                             projected_margin_level=level)
            elif level is not None:
                result.check(f"Projected margin level {level:.0f}%.")

    # ---------------------------------------------------------- 9. net economics
    economics = None
    if volume and solution.ok:
        gross_risk = abs(float(solution.risk_amount_actual or 0))
        reward_calc = broker_profit(calculator, profile, direction, volume, live_entry, take_profit)
        gross_reward = abs(float(reward_calc.value)) if reward_calc.ok else None
        # Use the broker's own loss-per-lot figure (from solve_volume_for_risk)
        # rather than re-deriving "money per unit" from the risk budget. The
        # two are close when the broker model is linear, but the broker's is
        # authoritative for non-FX / cross-currency symbols.
        money_per_price_unit = None
        if stop_distance > 0 and volume:
            if solution.loss_per_lot:
                money_per_price_unit = solution.loss_per_lot / stop_distance
            else:
                money_per_price_unit = gross_risk / (stop_distance * volume)
        costs = estimate_costs(
            profile, volume=volume, spread_price=measurement.raw_spread_price,
            money_per_price_unit_per_lot=money_per_price_unit,
            assumptions=config.costs, direction=direction,
            prices_are_executable=True,   # gross money already used live ask/bid legs
        )
        minimum_rr = config.minimum_net_rr if config.minimum_net_rr is not None else float(plan.get("minimum_rr") or 2.0)
        economics = reward_to_risk(
            entry=live_entry, stop_loss=stop_loss, take_profit=take_profit,
            minimum_rr=minimum_rr, gross_risk_money=gross_risk, gross_reward_money=gross_reward,
            costs=costs, execution_prices=prices,
        )
        if economics.meets_minimum_net is False:
            result.block(NET_RR_BELOW_MINIMUM,
                         f"Net RR {economics.net_rr:.2f} after costs is below the {minimum_rr:.2f} minimum. "
                         f"Gross RR was {economics.gross_rr:.2f}.",
                         net_rr=economics.net_rr, gross_rr=economics.gross_rr)
        elif economics.net_rr is not None:
            result.check(f"Net RR {economics.net_rr:.2f} after costs (gross {economics.gross_rr:.2f}).")
        elif config.require_net_rr:
            result.block(
                BROKER_CALCULATION_UNAVAILABLE,
                "Net RR could not be computed because the broker did not return a "
                "profit figure at the take-profit level. Automatic execution is blocked "
                "rather than relying on gross RR alone.",
                gross_rr=economics.gross_rr, net_rr=None,
            )
        else:
            result.warn("Net RR could not be computed; only the gross RR is available.")

    # ------------------------------------------------------- 10. OrderCheck
    order_check_response = None
    if volume and order_checker is not None:
        request = {
            "action": "DEAL", "symbol": profile.symbol, "volume": volume,
            "type": direction, "price": live_entry, "sl": stop_loss, "tp": take_profit,
            "type_filling": (profile.filling_modes() or ["FOK"])[0],
        }
        try:
            order_check_response = order_checker(request)
        except Exception as exc:                                  # pragma: no cover - transport
            result.block(ORDER_CHECK_FAILED, f"OrderCheck raised: {exc}")
        else:
            retcode = (order_check_response or {}).get("retcode")
            if retcode not in ACCEPTABLE_ORDER_CHECK_RETCODES:
                result.block(ORDER_CHECK_FAILED,
                             f"Broker OrderCheck returned retcode {retcode}: "
                             f"{(order_check_response or {}).get('comment', 'no comment')}.",
                             order_check=order_check_response)
            else:
                result.check(f"Broker OrderCheck passed (retcode {retcode}).")
    elif config.require_order_check and volume:
        result.block(ORDER_CHECK_FAILED,
                     "OrderCheck is required before execution but no order_check transport was supplied.")

    # ------------------------------------------------------- authoritative object
    result.execution = {
        "symbol": profile.symbol,
        "direction": direction,
        "instrument_class": profile.instrument_class,
        "volume": volume,
        "entry": live_entry,
        "entry_side": "ask" if direction == "BUY" else "bid",
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "stop_distance": stop_distance,
        "stop_distance_display": profile.describe_distance(stop_distance),
        "target_distance": reward_distance,
        "target_distance_display": profile.describe_distance(reward_distance),
        "risk_amount": solution.risk_amount_actual if solution.ok else None,
        "risk_percent": solution.risk_percent_actual if solution.ok else None,
        "loss_per_lot": solution.loss_per_lot if solution.ok else None,
        "risk_source": solution.source,
        "risk_authoritative": bool(solution.ok and solution.authoritative),
        "margin_required": margin_value,
        "spread": measurement.as_dict(),
        "spread_gate": gate.as_dict(),
        "economics": economics.as_dict() if economics else None,
        "gross_rr": economics.gross_rr if economics else None,
        "net_rr": economics.net_rr if economics else None,
        "broker_validation": validation.as_dict(),
        "order_check": order_check_response,
        "filling_modes": profile.filling_modes(),
        "account_currency": account.get("currency"),
        "evaluated_at": result.timestamp,
        "note": "Every displayed value on this object is the value the execution decision used.",
    }
    return result
