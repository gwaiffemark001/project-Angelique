"""Execution mathematics: instruments, spread, costs, broker calcs, preflight."""

from datetime import datetime, timedelta, timezone

import pytest

from skills.trading_skill.broker_calc import (
    BROKER_CALCULATION_UNAVAILABLE, BROKER_METADATA_INCOMPLETE,
    broker_margin, broker_profit, estimate_margin, estimate_profit,
    solve_volume_for_risk,
)
from skills.trading_skill.costs import (
    CostAssumptions, ExecutionPrices, estimate_costs, reward_to_risk,
)
from skills.trading_skill.execution_preflight import PreflightConfig, preflight
from skills.trading_skill.instruments import (
    CRYPTO, FX_CROSS, FX_MAJOR, INDEX, METAL, build_profile,
)
from skills.trading_skill.spread_model import (
    SpreadProfileStore, evaluate_spread_gate, measure_spread, policy_for,
)
from skills.trading_skill.trade_levels import validate_levels_against_broker

FX_SPECS = {
    "point": 0.00001, "digits": 5, "trade_tick_size": 0.00001, "trade_tick_value": 1.0,
    "trade_tick_value_profit": 1.0, "trade_tick_value_loss": 1.0,
    "trade_contract_size": 100000, "volume_min": 0.01, "volume_max": 100.0,
    "volume_step": 0.01, "currency_base": "EUR", "currency_profit": "USD",
    "trade_calc_mode": 0, "trade_mode": 4, "trade_stops_level": 10,
    "trade_freeze_level": 0, "filling_mode": 1,
}
GOLD_SPECS = {
    "point": 0.01, "digits": 2, "trade_tick_size": 0.01, "trade_tick_value": 1.0,
    "trade_tick_value_loss": 1.0, "trade_contract_size": 100, "volume_min": 0.01,
    "volume_max": 20.0, "volume_step": 0.01, "currency_base": "XAU",
    "currency_profit": "USD", "trade_calc_mode": 2, "trade_mode": 4,
    "trade_stops_level": 50, "filling_mode": 2,
}


class Calculator:
    """Deterministic broker calculator standing in for MT5 order_calc_*."""

    def __init__(self, contract=100000, rate=1.0, leverage=500.0, fail=False):
        self.contract, self.rate, self.leverage, self.fail = contract, rate, leverage, fail
        self.profit_calls = 0

    def calculate_profit(self, symbol, direction, volume, price_open, price_close):
        self.profit_calls += 1
        if self.fail:
            return {"status": "error", "error": "order_calc_profit unavailable"}
        move = price_close - price_open
        signed = move if direction == "BUY" else -move
        return {"profit": signed * self.contract * volume * self.rate}

    def calculate_margin(self, symbol, direction, volume, price):
        if self.fail:
            return {"status": "error", "error": "order_calc_margin unavailable"}
        return {"margin": self.contract * volume * price / self.leverage}


class ProfitFailCalculator(Calculator):
    """Broker calculator that answers SL loss but refuses a TP profit figure."""

    def calculate_profit(self, symbol, direction, volume, price_open, price_close):
        result = super().calculate_profit(symbol, direction, volume, price_open, price_close)
        if isinstance(result, dict) and result.get("profit") is not None and float(result["profit"]) > 0:
            return {"status": "error", "error": "order_calc_profit unavailable at TP"}
        return result

    def calculate_margin(self, symbol, direction, volume, price):
        if self.fail:
            return {"status": "error", "error": "order_calc_margin unavailable"}
        return {"margin": self.contract * volume * price / self.leverage}


def _account(equity=10000.0):
    return {"equity": equity, "balance": equity, "margin_free": equity * 0.98,
            "margin": 0.0, "currency": "USD", "trade_allowed": True, "trade_expert": True}


def _plan(now, entry=1.10000, stop=1.09500, target=1.11500):
    return {"entry": entry, "stop_loss": stop, "take_profit": target,
            "risk_percent": 1.0, "minimum_rr": 2.0, "generated_at": now.isoformat()}


def _tick(now, bid=1.09990, ask=1.10000):
    return {"bid": bid, "ask": ask, "time": now.isoformat()}


# ==========================================================================
# Instrument classification
# ==========================================================================
def test_classification_comes_from_broker_metadata_not_the_symbol_name():
    # A broker-suffixed symbol that name matching would get wrong.
    profile = build_profile("EURUSD.VX", FX_SPECS)
    assert profile.instrument_class == FX_MAJOR
    assert profile.pip_size == pytest.approx(0.0001)


def test_gold_is_never_given_an_fx_pip():
    profile = build_profile("XAUUSD.a", GOLD_SPECS)
    assert profile.instrument_class == METAL
    assert profile.pip_size is None
    assert profile.to_pips(1.0) is None
    assert profile.display_unit == "points"
    assert "pip" not in profile.format_distance(1.0)


def test_jpy_cross_uses_a_two_decimal_pip():
    specs = {**FX_SPECS, "point": 0.001, "digits": 3,
             "trade_tick_size": 0.001, "currency_base": "GBP", "currency_profit": "JPY"}
    profile = build_profile("GBPJPYm", specs)
    assert profile.instrument_class == FX_CROSS
    assert profile.pip_size == pytest.approx(0.01)


def test_crypto_and_index_have_no_pip():
    crypto = build_profile("BTCUSD", {**GOLD_SPECS, "currency_base": "BTC",
                                      "trade_calc_mode": 4, "trade_contract_size": 1})
    index = build_profile("US30.cash", {**GOLD_SPECS, "currency_base": "USD",
                                        "currency_profit": "USD", "trade_calc_mode": 3,
                                        "path": "CFD\\Indices\\US30"})
    assert crypto.instrument_class == CRYPTO
    assert index.instrument_class == INDEX
    assert crypto.pip_size is index.pip_size is None


def test_incomplete_metadata_is_reported_precisely():
    profile = build_profile("EURUSD", {})
    assert profile.metadata_complete is False
    assert profile.missing_metadata
    assert all(isinstance(field, str) for field in profile.missing_metadata)


def test_volume_normalisation_never_rounds_up():
    profile = build_profile("EURUSD", FX_SPECS)
    assert profile.normalize_volume(0.0199) == pytest.approx(0.01)
    assert profile.normalize_volume(0.0299) == pytest.approx(0.02)
    assert profile.normalize_volume(1e9) <= profile.volume_max


def test_price_normalisation_snaps_to_the_tick_grid():
    profile = build_profile("EURUSD", FX_SPECS)
    assert profile.normalize_price(1.123456789) == pytest.approx(1.12346, abs=1e-9)


# ==========================================================================
# Spread
# ==========================================================================
def test_spread_is_derived_from_raw_bid_ask():
    profile = build_profile("EURUSD", FX_SPECS)
    measurement = measure_spread(profile, 1.09990, 1.10000)
    assert measurement.valid
    assert measurement.raw_spread_price == pytest.approx(0.0001)
    assert measurement.spread_pips == pytest.approx(1.0)
    assert measurement.spread_points == pytest.approx(10.0)


def test_inverted_quote_is_rejected():
    profile = build_profile("EURUSD", FX_SPECS)
    assert measure_spread(profile, 1.10010, 1.10000).valid is False


def test_an_fx_pip_ceiling_is_never_applied_to_gold():
    gold = build_profile("XAUUSD", GOLD_SPECS)
    policy = policy_for(gold.instrument_class)
    assert policy.absolute_pips is None
    assert policy.absolute_points is not None


def test_spread_relative_to_stop_distance_gates_scalps():
    profile = build_profile("EURUSD", FX_SPECS)
    measurement = measure_spread(profile, 1.09980, 1.10000)     # 2 pips
    wide_stop = evaluate_spread_gate(profile, measurement, stop_distance_price=0.0100,
                                     store=SpreadProfileStore())
    tight_stop = evaluate_spread_gate(profile, measurement, stop_distance_price=0.0006,
                                      store=SpreadProfileStore())
    assert wide_stop.allowed is True
    assert tight_stop.allowed is False
    assert any("stop distance" in reason for reason in tight_stop.reasons)


def test_rolling_distribution_rejects_abnormal_widening():
    profile = build_profile("EURUSD", FX_SPECS)
    store = SpreadProfileStore()
    for _ in range(40):
        store.observe(measure_spread(profile, 1.09990, 1.10000))       # 1 pip normal
    blowout = measure_spread(profile, 1.09980, 1.10000)                # 2 pips
    result = evaluate_spread_gate(profile, blowout, store=store)
    assert result.observed_percentile is not None
    assert result.allowed is False
    assert any("percentile" in reason for reason in result.reasons)


def test_percentile_gate_is_skipped_without_enough_samples():
    profile = build_profile("EURUSD", FX_SPECS)
    store = SpreadProfileStore()
    store.observe(measure_spread(profile, 1.09990, 1.10000))
    result = evaluate_spread_gate(profile, measure_spread(profile, 1.09990, 1.10000), store=store)
    assert result.allowed is True
    assert any("not yet significant" in check for check in result.checks)


# ==========================================================================
# Broker calculations
# ==========================================================================
def test_broker_profit_is_authoritative():
    profile = build_profile("EURUSD", FX_SPECS)
    result = broker_profit(Calculator(), profile, "BUY", 1.0, 1.10, 1.11)
    assert result.ok and result.authoritative
    assert result.source == "order_calc_profit"
    assert result.value == pytest.approx(1000.0)


def test_missing_calculator_blocks_rather_than_estimating():
    profile = build_profile("EURUSD", FX_SPECS)
    result = broker_profit(None, profile, "BUY", 1.0, 1.10, 1.11)
    assert not result.ok
    assert result.blocker == BROKER_CALCULATION_UNAVAILABLE
    assert result.authoritative is False


def test_failing_calculator_blocks():
    profile = build_profile("EURUSD", FX_SPECS)
    assert not broker_profit(Calculator(fail=True), profile, "BUY", 1.0, 1.10, 1.11).ok
    assert not broker_margin(Calculator(fail=True), profile, "BUY", 1.0, 1.10).ok


def test_estimates_are_always_flagged_non_authoritative():
    profile = build_profile("EURUSD", FX_SPECS)
    estimate = estimate_profit(profile, "BUY", 1.0, 1.10, 1.11)
    assert estimate.ok
    assert estimate.authoritative is False
    assert "APPROXIMATION" in estimate.reason


def test_leverage_margin_estimate_is_refused_for_non_forex_modes():
    gold = build_profile("XAUUSD", GOLD_SPECS)
    result = estimate_margin(gold, 1.0, 2400.0, 500.0)
    assert not result.ok
    assert result.blocker == BROKER_CALCULATION_UNAVAILABLE
    assert "order_calc_margin is required" in result.reason


# ==========================================================================
# Volume solving
# ==========================================================================
def test_volume_never_exceeds_the_risk_budget():
    profile = build_profile("EURUSD", FX_SPECS)
    solution = solve_volume_for_risk(Calculator(), profile, direction="BUY",
                                     entry=1.10, stop_loss=1.095, equity=10000, risk_percent=1.0)
    assert solution.ok
    # The binding guarantee: the broker-verified loss never exceeds the budget.
    assert solution.risk_amount_actual <= 100.0 + 1e-9
    # Volume is floored onto the grid, allowing only IEEE-754 noise upward.
    assert solution.volume <= solution.ideal_volume + profile.volume_step * 1e-6


def test_volume_is_reverified_with_the_broker_after_rounding():
    profile = build_profile("EURUSD", FX_SPECS)
    calculator = Calculator()
    solution = solve_volume_for_risk(calculator, profile, direction="BUY", entry=1.10,
                                     stop_loss=1.095, equity=10000, risk_percent=1.0)
    assert solution.ok
    # A probe call plus at least one verification call at the normalised volume.
    assert calculator.profit_calls >= 2
    assert solution.iterations >= 1


def test_volume_solving_blocks_when_metadata_is_incomplete():
    profile = build_profile("EURUSD", {"point": 0.00001, "digits": 5})
    solution = solve_volume_for_risk(Calculator(), profile, direction="BUY", entry=1.10,
                                     stop_loss=1.095, equity=10000, risk_percent=1.0)
    assert not solution.ok
    assert solution.blocker == BROKER_METADATA_INCOMPLETE


def test_volume_solving_blocks_when_the_minimum_lot_is_too_risky():
    profile = build_profile("EURUSD", FX_SPECS)
    solution = solve_volume_for_risk(Calculator(), profile, direction="BUY", entry=1.10,
                                     stop_loss=1.00, equity=100, risk_percent=1.0)
    assert not solution.ok
    assert solution.blocker == "VOLUME_OUT_OF_RANGE"


def test_volume_solving_refuses_the_estimate_path_by_default():
    profile = build_profile("EURUSD", FX_SPECS)
    solution = solve_volume_for_risk(None, profile, direction="BUY", entry=1.10,
                                     stop_loss=1.095, equity=10000, risk_percent=1.0)
    assert not solution.ok
    assert "broker-calculated" in solution.reason


# ==========================================================================
# Bid/Ask sides and costs
# ==========================================================================
def test_buy_enters_at_ask_and_exits_at_bid():
    prices = ExecutionPrices("BUY", bid=1.09990, ask=1.10000)
    assert prices.entry_price == 1.10000
    assert prices.exit_price == 1.09990
    data = prices.as_dict()
    assert data["entry_executes_at"] == "ask"
    assert data["exit_executes_at"] == "bid"


def test_sell_enters_at_bid_and_exits_at_ask():
    prices = ExecutionPrices("SELL", bid=1.09990, ask=1.10000)
    assert prices.entry_price == 1.09990
    assert prices.exit_price == 1.10000


def test_net_rr_is_lower_than_gross_rr():
    profile = build_profile("EURUSD", FX_SPECS)
    costs = estimate_costs(profile, volume=0.2, spread_price=0.0001,
                           money_per_price_unit_per_lot=100000,
                           assumptions=CostAssumptions(commission_per_lot_per_side=3.5))
    economics = reward_to_risk(entry=1.10, stop_loss=1.095, take_profit=1.115,
                               minimum_rr=2.0, gross_risk_money=100.0,
                               gross_reward_money=300.0, costs=costs)
    assert economics.gross_rr == pytest.approx(3.0)
    assert economics.net_rr < economics.gross_rr
    assert economics.meets_minimum_gross is True


def test_costs_can_destroy_an_apparently_good_rr():
    profile = build_profile("EURUSD", FX_SPECS)
    costs = estimate_costs(profile, volume=1.0, spread_price=0.0020,          # 20 pips
                           money_per_price_unit_per_lot=100000,
                           assumptions=CostAssumptions(commission_per_lot_per_side=7.0))
    economics = reward_to_risk(entry=1.10, stop_loss=1.099, take_profit=1.103,
                               minimum_rr=2.0, gross_risk_money=100.0,
                               gross_reward_money=300.0, costs=costs)
    assert economics.gross_rr == pytest.approx(3.0)
    assert economics.meets_minimum_net is False
    assert economics.reasons


def test_executable_prices_do_not_double_count_the_spread():
    # gross risk/reward were computed by order_calc_profit from live Ask/Bid, so
    # the spread is already inside those prices. Charging a separate 2x spread
    # would double-count it and overstate the drag on net RR.
    profile = build_profile("EURUSD", FX_SPECS)
    costs = estimate_costs(
        profile, volume=1.0, spread_price=0.0001,
        money_per_price_unit_per_lot=100000,
        assumptions=CostAssumptions(commission_per_lot_per_side=3.5),
        prices_are_executable=True,
    )
    assert costs.spread_cost == pytest.approx(0.0)
    assert costs.total_cost == pytest.approx(7.0)      # 2 sides x 3.5/2? no, 7.0
    economics = reward_to_risk(
        entry=1.10000, stop_loss=1.09900, take_profit=1.10600,
        minimum_rr=2.0, gross_risk_money=100.0, gross_reward_money=600.0,
        costs=costs,
        execution_prices=ExecutionPrices("BUY", bid=1.09990, ask=1.10000),
    )
    assert economics.net_rr == pytest.approx((600.0 - 7.0) / (100.0 + 7.0))


def test_non_executable_prices_still_charge_the_spread():
    profile = build_profile("EURUSD", FX_SPECS)
    costs = estimate_costs(profile, volume=1.0, spread_price=0.0001,
                           money_per_price_unit_per_lot=100000,
                           assumptions=CostAssumptions(commission_per_lot_per_side=3.5))
    assert costs.spread_cost == pytest.approx(20.0)     # 10 pips x 1.0 lot x 2 legs
    assert costs.total_cost == pytest.approx(27.0)


def test_net_rr_is_none_when_broker_money_values_are_missing():
    economics = reward_to_risk(entry=1.10, stop_loss=1.095, take_profit=1.115, minimum_rr=2.0)
    assert economics.net_rr is None
    assert any("Net RR unavailable" in reason for reason in economics.reasons)


# ==========================================================================
# Level validation
# ==========================================================================
def test_buy_stop_is_validated_against_bid():
    profile = build_profile("EURUSD", FX_SPECS)
    result = validate_levels_against_broker(profile, direction="BUY", entry=1.10000,
                                            stop_loss=1.09500, take_profit=1.11500,
                                            bid=1.09990, ask=1.10000)
    assert result.valid
    assert result.detail["sl_reference_side"] == "bid"
    assert result.detail["sl_reference_price"] == pytest.approx(1.09990)


def test_sell_stop_is_validated_against_ask():
    profile = build_profile("EURUSD", FX_SPECS)
    result = validate_levels_against_broker(profile, direction="SELL", entry=1.09990,
                                            stop_loss=1.10500, take_profit=1.08500,
                                            bid=1.09990, ask=1.10000)
    assert result.valid
    assert result.detail["sl_reference_side"] == "ask"


def test_stops_level_violation_is_caught_before_the_broker_rejects_it():
    profile = build_profile("EURUSD", FX_SPECS)         # stops_level = 10 points
    result = validate_levels_against_broker(profile, direction="BUY", entry=1.10000,
                                            stop_loss=1.09985, take_profit=1.11500,
                                            bid=1.09990, ask=1.10000)
    assert not result.valid
    assert result.blocker == "STOPS_LEVEL_VIOLATION"
    assert any("10016" in violation for violation in result.violations)


def test_levels_are_rounded_to_the_tick_grid():
    profile = build_profile("EURUSD", FX_SPECS)
    result = validate_levels_against_broker(profile, direction="BUY", entry=1.1000012345,
                                            stop_loss=1.0950012345, take_profit=1.1150012345,
                                            bid=1.09990, ask=1.10000)
    for price in (result.entry, result.stop_loss, result.take_profit):
        assert abs(round(price / profile.tick_size) * profile.tick_size - price) < 1e-9


def test_inverted_levels_are_rejected():
    profile = build_profile("EURUSD", FX_SPECS)
    result = validate_levels_against_broker(profile, direction="BUY", entry=1.10000,
                                            stop_loss=1.10500, take_profit=1.11500,
                                            bid=1.09990, ask=1.10000)
    assert not result.valid
    assert any("not below the entry" in violation for violation in result.violations)


def test_gold_violations_are_expressed_in_points_not_pips():
    profile = build_profile("XAUUSD", GOLD_SPECS)       # stops_level = 50 points
    result = validate_levels_against_broker(profile, direction="BUY", entry=2411.60,
                                            stop_loss=2411.50, take_profit=2450.00,
                                            bid=2411.25, ask=2411.60)
    assert not result.valid
    assert any("points" in violation for violation in result.violations)
    assert not any("pips" in violation for violation in result.violations)


# ==========================================================================
# Full preflight
# ==========================================================================
def test_preflight_approves_a_sound_trade():
    now = datetime.now(timezone.utc)
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=_tick(now),
                       plan=_plan(now), account=_account(), calculator=Calculator(),
                       order_checker=lambda request: {"retcode": 0})
    assert result.approved, [b.message for b in result.blockers]
    assert result.execution["risk_authoritative"] is True
    assert result.execution["net_rr"] is not None


def test_preflight_blocks_without_a_broker_calculator():
    now = datetime.now(timezone.utc)
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=_tick(now),
                       plan=_plan(now), account=_account(), calculator=None,
                       order_checker=lambda request: {"retcode": 0})
    assert not result.approved
    assert BROKER_CALCULATION_UNAVAILABLE in [b.code for b in result.blockers]


def test_preflight_blocks_on_incomplete_metadata():
    now = datetime.now(timezone.utc)
    result = preflight(symbol="EURUSD", direction="BUY", specs={"point": 0.00001, "digits": 5},
                       tick=_tick(now), plan=_plan(now), account=_account(),
                       calculator=Calculator(), order_checker=lambda request: {"retcode": 0})
    assert not result.approved
    assert result.blockers[0].code == BROKER_METADATA_INCOMPLETE


def test_preflight_blocks_a_stale_plan():
    now = datetime.now(timezone.utc)
    plan = _plan(now)
    plan["generated_at"] = (now - timedelta(hours=2)).isoformat()
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=_tick(now),
                       plan=plan, account=_account(), calculator=Calculator(),
                       order_checker=lambda request: {"retcode": 0})
    assert "PLAN_STALE" in [b.code for b in result.blockers]


def test_preflight_blocks_a_stale_quote():
    now = datetime.now(timezone.utc)
    tick = _tick(now)
    tick["time"] = (now - timedelta(minutes=5)).isoformat()
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=tick,
                       plan=_plan(now), account=_account(), calculator=Calculator(),
                       order_checker=lambda request: {"retcode": 0})
    assert "QUOTE_STALE" in [b.code for b in result.blockers]


def test_preflight_blocks_price_drift():
    now = datetime.now(timezone.utc)
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS,
                       tick=_tick(now, bid=1.10490, ask=1.10500), plan=_plan(now),
                       account=_account(), calculator=Calculator(),
                       order_checker=lambda request: {"retcode": 0})
    assert "PRICE_DRIFT" in [b.code for b in result.blockers]


def test_preflight_blocks_a_closed_market():
    now = datetime.now(timezone.utc)
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=_tick(now),
                       plan=_plan(now), account=_account(), calculator=Calculator(),
                       order_checker=lambda request: {"retcode": 0}, market_open=False)
    assert "MARKET_CLOSED" in [b.code for b in result.blockers]


def test_preflight_blocks_when_trading_is_disabled():
    now = datetime.now(timezone.utc)
    account = {**_account(), "trade_expert": False}
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=_tick(now),
                       plan=_plan(now), account=account, calculator=Calculator(),
                       order_checker=lambda request: {"retcode": 0})
    assert "TRADE_DISABLED" in [b.code for b in result.blockers]


def test_preflight_requires_order_check():
    now = datetime.now(timezone.utc)
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=_tick(now),
                       plan=_plan(now), account=_account(), calculator=Calculator(),
                       order_checker=None)
    assert "ORDER_CHECK_FAILED" in [b.code for b in result.blockers]


def test_preflight_respects_a_failing_order_check():
    now = datetime.now(timezone.utc)
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=_tick(now),
                       plan=_plan(now), account=_account(), calculator=Calculator(),
                       order_checker=lambda request: {"retcode": 10016, "comment": "Invalid stops"})
    assert not result.approved
    assert "ORDER_CHECK_FAILED" in [b.code for b in result.blockers]


def test_preflight_blocks_insufficient_margin():
    now = datetime.now(timezone.utc)
    account = {**_account(), "margin_free": 1.0}
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=_tick(now),
                       plan=_plan(now), account=account, calculator=Calculator(),
                       order_checker=lambda request: {"retcode": 0})
    assert "INSUFFICIENT_MARGIN" in [b.code for b in result.blockers]


def test_preflight_blocks_a_wide_spread():
    now = datetime.now(timezone.utc)
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS,
                       tick=_tick(now, bid=1.09900, ask=1.10000), plan=_plan(now),
                       account=_account(), calculator=Calculator(),
                       order_checker=lambda request: {"retcode": 0})
    assert "SPREAD_UNACCEPTABLE" in [b.code for b in result.blockers]


def test_preflight_blocks_when_net_rr_cannot_be_computed():
    now = datetime.now(timezone.utc)
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=_tick(now),
                       plan=_plan(now), account=_account(), calculator=ProfitFailCalculator(),
                       order_checker=lambda request: {"retcode": 0})
    assert not result.approved
    assert BROKER_CALCULATION_UNAVAILABLE in [b.code for b in result.blockers]
    assert any("Net RR could not be computed" in b.message for b in result.blockers)


def test_preflight_blocks_when_costs_destroy_the_net_rr():
    now = datetime.now(timezone.utc)
    config = PreflightConfig(costs=CostAssumptions(commission_per_lot_per_side=200.0))
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=_tick(now),
                       plan=_plan(now), account=_account(), calculator=Calculator(),
                       order_checker=lambda request: {"retcode": 0}, config=config)
    assert "NET_RR_BELOW_MINIMUM" in [b.code for b in result.blockers]


def test_every_blocker_carries_a_code_and_a_message():
    now = datetime.now(timezone.utc)
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS,
                       tick=_tick(now, bid=1.09000, ask=1.10000), plan=_plan(now),
                       account={**_account(), "margin_free": 0.5}, calculator=None,
                       order_checker=None, market_open=False)
    assert not result.approved
    assert result.blockers
    for blocker in result.blockers:
        assert blocker.code and blocker.code.isupper()
        assert len(blocker.message) > 10


def test_execution_object_is_the_single_source_for_the_ui():
    now = datetime.now(timezone.utc)
    result = preflight(symbol="EURUSD", direction="BUY", specs=FX_SPECS, tick=_tick(now),
                       plan=_plan(now), account=_account(), calculator=Calculator(),
                       order_checker=lambda request: {"retcode": 0})
    execution = result.execution
    for key in ("symbol", "direction", "volume", "entry", "stop_loss", "take_profit",
                "risk_amount", "margin_required", "gross_rr", "net_rr", "spread",
                "instrument_class", "entry_side"):
        assert key in execution
    # The values the UI shows must be the ones the decision used.
    assert execution["entry"] == pytest.approx(float(_tick(now)["ask"]))
    assert execution["entry_side"] == "ask"


def test_gold_preflight_uses_points_throughout():
    now = datetime.now(timezone.utc)
    tick = {"bid": 2411.25, "ask": 2411.60, "time": now.isoformat()}
    plan = {"entry": 2411.60, "stop_loss": 2398.00, "take_profit": 2450.00,
            "risk_percent": 1.0, "minimum_rr": 2.0, "generated_at": now.isoformat()}
    result = preflight(symbol="XAUUSD", direction="BUY", specs=GOLD_SPECS, tick=tick,
                       plan=plan, account=_account(), calculator=Calculator(contract=100),
                       order_checker=lambda request: {"retcode": 0})
    assert result.execution["instrument_class"] == METAL
    assert "points" in result.execution["stop_distance_display"]["unit"]
    assert result.execution["spread"]["spread_pips"] is None
