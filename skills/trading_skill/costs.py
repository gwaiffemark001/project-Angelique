"""Transaction costs and NET reward-to-risk.

A distance-based RR ("risk 10 pips, reward 25 pips, RR = 2.5") ignores the
economics that actually determine whether a trade is worth taking:

* the spread, which is paid on entry (and again implicitly at exit),
* commission per lot per side,
* swap for positions held over rollover,
* expected slippage,
* and the fact that a BUY enters at Ask and exits at Bid (and vice versa).

This module produces ``gross_rr`` **and** ``net_rr`` from the same authoritative
inputs, so the UI and the execution gate can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

from .instruments import InstrumentProfile

#: Swap is charged three times on the broker's rollover-3-days weekday.
TRIPLE_SWAP_WEEKDAY_DEFAULT = 3          # Wednesday, per MT5 swap_rollover3days


@dataclass(frozen=True)
class CostAssumptions:
    """Explicit, configurable cost assumptions. Documented as policy."""
    commission_per_lot_per_side: float = 0.0
    #: Expected slippage expressed in broker points on entry.
    slippage_points: float = 0.0
    #: Count the exit spread as well as the entry spread.
    charge_exit_spread: bool = True
    #: Nights the position is expected to be held (drives swap).
    expected_nights: int = 0
    source: str = "default assumptions (not calibrated)"


@dataclass
class ExecutionPrices:
    """Which side of the book each leg of the trade actually transacts on."""
    direction: str
    bid: float
    ask: float

    @property
    def entry_price(self) -> float:
        return self.ask if self.direction == "BUY" else self.bid

    @property
    def exit_price(self) -> float:
        return self.bid if self.direction == "BUY" else self.ask

    def as_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction, "bid": self.bid, "ask": self.ask,
            "entry_executes_at": "ask" if self.direction == "BUY" else "bid",
            "exit_executes_at": "bid" if self.direction == "BUY" else "ask",
            "entry_price": self.entry_price, "exit_price": self.exit_price,
        }


@dataclass
class CostBreakdown:
    spread_cost: float | None
    commission_cost: float | None
    swap_cost: float | None
    slippage_cost: float | None
    total_cost: float | None
    authoritative: bool
    components_available: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_costs(
    profile: InstrumentProfile,
    *,
    volume: float,
    spread_price: float | None,
    money_per_price_unit_per_lot: float | None,
    assumptions: CostAssumptions | None = None,
    direction: str = "BUY",
    prices_are_executable: bool = False,
) -> CostBreakdown:
    """Monetise the round-trip cost of a trade in account currency.

    ``money_per_price_unit_per_lot`` must come from the broker calculator
    (``order_calc_profit`` over a known distance / that distance), not from a
    generic tick-value formula.

    ``prices_are_executable`` is the key double-counting guard. When the gross
    risk/reward money values were calculated by ``order_calc_profit`` from the
    actual executable side of the book (a BUY enters at Ask and exits at Bid, a
    SELL enters at Bid and exits at Ask), the spread is already inside those
    prices. Charging a separate 2x spread on top would double-count it, so the
    spread component is recorded as zero with an explicit note. A caller that
    computes gross money from midpoint prices (display-only) must leave it
    False so the spread remains a real cost.
    """
    assumptions = assumptions or CostAssumptions()
    notes: list[str] = []
    available = {"spread": False, "commission": False, "swap": False, "slippage": False}

    spread_cost = None
    slippage_cost = None
    if spread_price is not None and money_per_price_unit_per_lot:
        if prices_are_executable:
            spread_cost = 0.0
            available["spread"] = True
            notes.append(
                "Spread is already embedded in the executable Bid/Ask legs used "
                "by order_calc_profit; it is not charged again."
            )
        else:
            legs = 2.0 if assumptions.charge_exit_spread else 1.0
            spread_cost = abs(spread_price) * legs * money_per_price_unit_per_lot * volume
            available["spread"] = True
        if assumptions.slippage_points and profile.point > 0:
            slippage_cost = (assumptions.slippage_points * profile.point
                             * money_per_price_unit_per_lot * volume)
            available["slippage"] = True
    else:
        notes.append("Spread cost unavailable: needs live spread and broker money-per-price-unit.")

    commission_cost = None
    if assumptions.commission_per_lot_per_side:
        commission_cost = abs(assumptions.commission_per_lot_per_side) * 2.0 * volume
        available["commission"] = True
    else:
        notes.append("Commission assumed zero; set CostAssumptions.commission_per_lot_per_side if the account charges one.")

    swap_cost = None
    nights = max(0, int(assumptions.expected_nights))
    if nights:
        rate = profile.swap_long if str(direction).upper() == "BUY" else profile.swap_short
        if rate:
            # swap_mode 1 = points; anything else is broker/currency specific and
            # is reported as an approximation.
            if profile.swap_mode == 1 and profile.point > 0 and money_per_price_unit_per_lot:
                per_night = rate * profile.point * money_per_price_unit_per_lot * volume
            else:
                per_night = rate * volume
                notes.append(f"Swap mode {profile.swap_mode} is not points-based; swap figure is approximate.")
            swap_cost = -per_night * nights      # positive number = cost
            available["swap"] = True
        else:
            notes.append("Broker reported no swap rate for this direction.")

    parts = [value for value in (spread_cost, commission_cost, swap_cost, slippage_cost) if value is not None]
    total = sum(parts) if parts else None
    return CostBreakdown(
        spread_cost=spread_cost, commission_cost=commission_cost, swap_cost=swap_cost,
        slippage_cost=slippage_cost, total_cost=total,
        authoritative=bool(money_per_price_unit_per_lot) and available["spread"],
        components_available=available, notes=notes,
    )


@dataclass
class RewardRisk:
    gross_risk_distance: float
    gross_reward_distance: float
    gross_rr: float
    gross_risk_money: float | None
    gross_reward_money: float | None
    net_risk_money: float | None
    net_reward_money: float | None
    net_rr: float | None
    costs: dict[str, Any]
    execution_prices: dict[str, Any] | None
    minimum_rr: float
    meets_minimum_gross: bool
    meets_minimum_net: bool | None
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def reward_to_risk(
    *,
    entry: float,
    stop_loss: float,
    take_profit: float,
    minimum_rr: float,
    gross_risk_money: float | None = None,
    gross_reward_money: float | None = None,
    costs: CostBreakdown | None = None,
    execution_prices: ExecutionPrices | None = None,
) -> RewardRisk:
    """Compute gross and net RR from one set of authoritative inputs.

    Costs are charged to *both* sides: they increase the effective risk and
    reduce the effective reward, which is what actually happens.
    """
    risk_distance = abs(float(entry) - float(stop_loss))
    reward_distance = abs(float(take_profit) - float(entry))
    gross_rr = reward_distance / risk_distance if risk_distance > 0 else 0.0

    reasons: list[str] = []
    net_risk = net_reward = net_rr = None
    total_cost = costs.total_cost if costs else None

    if gross_risk_money is not None and gross_reward_money is not None and total_cost is not None:
        net_risk = abs(gross_risk_money) + abs(total_cost)
        net_reward = abs(gross_reward_money) - abs(total_cost)
        net_rr = (net_reward / net_risk) if net_risk > 0 else 0.0
        if net_reward <= 0:
            reasons.append("Estimated transaction costs exceed the entire expected reward.")
        drag = (gross_rr - net_rr) if net_rr is not None else None
        if drag and drag > 0.25:
            reasons.append(f"Transaction costs reduce RR from {gross_rr:.2f} to {net_rr:.2f}.")
    else:
        reasons.append("Net RR unavailable: broker-calculated money values or cost data are missing.")

    meets_gross = gross_rr + 1e-9 >= minimum_rr
    meets_net = (net_rr + 1e-9 >= minimum_rr) if net_rr is not None else None
    if not meets_gross:
        reasons.append(f"Gross RR {gross_rr:.2f} is below the minimum {minimum_rr:.2f}.")
    if meets_net is False:
        reasons.append(f"Net RR {net_rr:.2f} is below the minimum {minimum_rr:.2f} after costs.")

    return RewardRisk(
        gross_risk_distance=risk_distance, gross_reward_distance=reward_distance,
        gross_rr=gross_rr, gross_risk_money=gross_risk_money, gross_reward_money=gross_reward_money,
        net_risk_money=net_risk, net_reward_money=net_reward, net_rr=net_rr,
        costs=costs.as_dict() if costs else {}, 
        execution_prices=execution_prices.as_dict() if execution_prices else None,
        minimum_rr=float(minimum_rr), meets_minimum_gross=meets_gross, meets_minimum_net=meets_net,
        reasons=reasons,
    )
