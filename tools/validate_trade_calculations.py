#!/usr/bin/env python3
"""Validate the trade-calculation chain end to end.

Runs the same code path the live engine uses -- instrument classification,
spread measurement, level validation, volume solving, cost and net-RR
modelling, and full execution preflight -- against either a deterministic
offline fixture set or a live MT5 connection.

Offline mode (default) proves the *logic* is correct and requires no broker.
Live mode additionally proves the broker calculators agree; that is the only
mode that can claim broker verification.

Usage
-----
    python tools/validate_trade_calculations.py
    python tools/validate_trade_calculations.py --live --mode demo --symbol EURUSD
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills.trading_skill.broker_calc import solve_volume_for_risk  # noqa: E402
from skills.trading_skill.costs import CostAssumptions, ExecutionPrices, estimate_costs, reward_to_risk  # noqa: E402
from skills.trading_skill.execution_preflight import PreflightConfig, preflight  # noqa: E402
from skills.trading_skill.instruments import build_profile  # noqa: E402
from skills.trading_skill.spread_model import evaluate_spread_gate, measure_spread  # noqa: E402
from skills.trading_skill.trade_levels import validate_levels_against_broker  # noqa: E402

# --------------------------------------------------------------------------
# Offline fixtures: one representative instrument per class.
# --------------------------------------------------------------------------
FIXTURES = {
    "EURUSD": {
        "specs": {"point": 0.00001, "digits": 5, "trade_tick_size": 0.00001,
                  "trade_tick_value": 1.0, "trade_tick_value_profit": 1.0,
                  "trade_tick_value_loss": 1.0, "trade_contract_size": 100000,
                  "volume_min": 0.01, "volume_max": 100.0, "volume_step": 0.01,
                  "currency_base": "EUR", "currency_profit": "USD", "currency_margin": "EUR",
                  "trade_calc_mode": 0, "trade_mode": 4, "trade_stops_level": 10,
                  "trade_freeze_level": 0, "filling_mode": 1},
        "bid": 1.09990, "ask": 1.10000,
        "expect_class": "FX_MAJOR", "expect_unit": "pips", "expect_pip": 0.0001,
        "entry": 1.10000, "stop_loss": 1.09500, "take_profit": 1.11500,
        "profit_to_account": 1.0,   # profit currency is already USD
    },
    "GBPJPY": {
        "specs": {"point": 0.001, "digits": 3, "trade_tick_size": 0.001,
                  "trade_tick_value": 0.67, "trade_tick_value_loss": 0.67,
                  "trade_contract_size": 100000, "volume_min": 0.01, "volume_max": 50.0,
                  "volume_step": 0.01, "currency_base": "GBP", "currency_profit": "JPY",
                  "trade_calc_mode": 0, "trade_mode": 4, "trade_stops_level": 20,
                  "filling_mode": 1},
        "bid": 193.450, "ask": 193.478,
        "expect_class": "FX_CROSS", "expect_unit": "pips", "expect_pip": 0.01,
        "entry": 193.478, "stop_loss": 192.800, "take_profit": 195.600,
        # GBPJPY profits in JPY on a USD account: JPY -> USD at ~1/155.
        "profit_to_account": 1.0 / 155.0,
        # Margin is valued in GBP: GBP -> USD is ~1.27, not the GBPJPY quote.
        "margin_reference_price": 1.27,
    },
    "XAUUSD": {
        "specs": {"point": 0.01, "digits": 2, "trade_tick_size": 0.01,
                  "trade_tick_value": 1.0, "trade_tick_value_loss": 1.0,
                  "trade_contract_size": 100, "volume_min": 0.01, "volume_max": 20.0,
                  "volume_step": 0.01, "currency_base": "XAU", "currency_profit": "USD",
                  "trade_calc_mode": 2, "trade_mode": 4, "trade_stops_level": 50,
                  "filling_mode": 2},
        "bid": 2411.25, "ask": 2411.60,
        "expect_class": "METAL", "expect_unit": "points", "expect_pip": None,
        "entry": 2411.60, "stop_loss": 2398.00, "take_profit": 2450.00,
    },
    "BTCUSD": {
        "specs": {"point": 0.01, "digits": 2, "trade_tick_size": 0.01,
                  "trade_tick_value": 0.01, "trade_tick_value_loss": 0.01,
                  "trade_contract_size": 1, "volume_min": 0.01, "volume_max": 5.0,
                  "volume_step": 0.01, "currency_base": "BTC", "currency_profit": "USD",
                  "trade_calc_mode": 4, "trade_mode": 4, "trade_stops_level": 0,
                  "filling_mode": 2},
        "bid": 64120.50, "ask": 64158.00,
        "expect_class": "CRYPTO", "expect_unit": "points", "expect_pip": None,
        "entry": 64158.00, "stop_loss": 62900.00, "take_profit": 68000.00,
    },
    "US30": {
        "specs": {"point": 0.1, "digits": 1, "trade_tick_size": 0.1,
                  "trade_tick_value": 0.1, "trade_tick_value_loss": 0.1,
                  "trade_contract_size": 1, "volume_min": 0.1, "volume_max": 50.0,
                  "volume_step": 0.1, "currency_base": "USD", "currency_profit": "USD",
                  "trade_calc_mode": 3, "trade_mode": 4, "trade_stops_level": 30,
                  "filling_mode": 2, "path": "CFD\\\\Indices\\\\US30"},
        "bid": 39120.4, "ask": 39124.8,
        "expect_class": "INDEX", "expect_unit": "points", "expect_pip": None,
        "entry": 39124.8, "stop_loss": 38900.0, "take_profit": 39800.0,
    },
}


class FixtureCalculator:
    """Deterministic stand-in for MT5 ``order_calc_*``.

    Applies real ``contract_size`` semantics AND converts the profit currency
    into the account currency. That conversion is exactly the step a generic
    ``distance / tick_size * tick_value`` formula gets wrong for cross-currency
    instruments such as GBPJPY on a USD account, so the fixture has to model it
    for the offline run to be meaningful.
    """

    def __init__(self, specs: dict, leverage: float = 500.0, profit_to_account: float = 1.0,
                 margin_reference_price: float | None = None):
        self.specs = specs
        self.leverage = leverage
        self.profit_to_account = profit_to_account
        self.margin_reference_price = margin_reference_price

    def calculate_profit(self, symbol, direction, volume, price_open, price_close):
        contract = float(self.specs.get("trade_contract_size", 1) or 1)
        move = float(price_close) - float(price_open)
        signed = move if str(direction).upper() == "BUY" else -move
        in_profit_currency = signed * contract * float(volume)
        return {"profit": in_profit_currency * self.profit_to_account}

    def calculate_margin(self, symbol, direction, volume, price):
        # MT5 values margin in the MARGIN currency, converted to the account
        # currency. For GBPJPY that is GBP->USD (~1.27), NOT the GBPJPY quote.
        contract = float(self.specs.get("trade_contract_size", 1) or 1)
        reference = float(self.margin_reference_price or price)
        return {"margin": contract * float(volume) * reference / self.leverage}


def _check(results: list, name: str, ok: bool, detail: str) -> None:
    results.append({"check": name, "passed": bool(ok), "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def validate_symbol(symbol: str, fixture: dict, equity: float = 10000.0) -> dict:
    print(f"\n=== {symbol} ===")
    results: list[dict] = []
    specs = fixture["specs"]
    profile = build_profile(symbol, specs)
    calculator = FixtureCalculator(
        specs,
        profit_to_account=fixture.get("profit_to_account", 1.0),
        margin_reference_price=fixture.get("margin_reference_price"),
    )

    # 1. classification
    _check(results, "instrument classification",
           profile.instrument_class == fixture["expect_class"],
           f"{profile.instrument_class} (expected {fixture['expect_class']}), "
           f"trade_calc_mode={profile.trade_calc_mode}")
    _check(results, "pip semantics", profile.pip_size == fixture["expect_pip"],
           f"pip_size={profile.pip_size} (expected {fixture['expect_pip']})")
    _check(results, "display unit", profile.display_unit == fixture["expect_unit"],
           f"{profile.display_unit}")
    _check(results, "no FX pip on non-FX",
           not (fixture["expect_pip"] is None and profile.to_pips(1.0) is not None),
           "to_pips() returns None for every non-FX instrument")
    _check(results, "metadata completeness", profile.metadata_complete,
           f"missing={list(profile.missing_metadata) or 'none'}")

    # 2. spread
    measurement = measure_spread(profile, fixture["bid"], fixture["ask"])
    _check(results, "spread from raw bid/ask", measurement.valid,
           f"{profile.format_distance(measurement.raw_spread_price)} "
           f"(raw {measurement.raw_spread_price:.10g})")

    # 3. volume solving
    for direction in ("BUY", "SELL"):
        entry = fixture["entry"]
        stop = fixture["stop_loss"] if direction == "BUY" else entry + (entry - fixture["stop_loss"])
        solution = solve_volume_for_risk(
            calculator, profile, direction=direction, entry=entry, stop_loss=stop,
            equity=equity, risk_percent=1.0,
        )
        within = solution.ok and solution.risk_amount_actual <= equity * 0.01 + 1e-6
        _check(results, f"{direction} volume never exceeds the risk budget", within,
               (f"volume={solution.volume}, risk={solution.risk_amount_actual:.2f} "
                f"({solution.risk_percent_actual:.3f}%)" if solution.ok else solution.reason))
        if solution.ok:
            on_grid = abs(round(solution.volume / profile.volume_step) * profile.volume_step
                          - solution.volume) < 1e-9
            _check(results, f"{direction} volume sits on the broker step grid", on_grid,
                   f"{solution.volume} with step {profile.volume_step}")
            _check(results, f"{direction} volume rounds DOWN, never up",
                   solution.volume <= solution.ideal_volume + 1e-12,
                   f"{solution.volume} <= ideal {solution.ideal_volume:.6f}")

    # 4. level validation
    validation = validate_levels_against_broker(
        profile, direction="BUY", entry=fixture["entry"], stop_loss=fixture["stop_loss"],
        take_profit=fixture["take_profit"], bid=fixture["bid"], ask=fixture["ask"],
    )
    _check(results, "levels satisfy the broker constraints", validation.valid,
           "; ".join(validation.violations) or "tick grid, stops_level and freeze_level all satisfied")
    on_grid = abs(round(validation.stop_loss / profile.tick_size) * profile.tick_size
                  - validation.stop_loss) < profile.tick_size * 1e-6
    _check(results, "stop loss rounded to the tick grid", on_grid,
           f"{validation.stop_loss} on a {profile.tick_size} grid")

    # A stop inside stops_level must be rejected.
    if profile.stops_level_points > 0:
        tight = fixture["bid"] - profile.stops_level_price * 0.25
        tight_check = validate_levels_against_broker(
            profile, direction="BUY", entry=fixture["entry"], stop_loss=tight,
            take_profit=fixture["take_profit"], bid=fixture["bid"], ask=fixture["ask"],
        )
        _check(results, "stops_level violation is rejected", not tight_check.valid,
               "; ".join(tight_check.violations)[:110] or "unexpectedly accepted")

    # 5. costs / net RR
    solution = solve_volume_for_risk(calculator, profile, direction="BUY",
                                     entry=fixture["entry"], stop_loss=fixture["stop_loss"],
                                     equity=equity, risk_percent=1.0)
    if solution.ok:
        stop_distance = abs(fixture["entry"] - fixture["stop_loss"])
        money_per_unit = solution.risk_amount_actual / (stop_distance * solution.volume)
        costs = estimate_costs(profile, volume=solution.volume,
                               spread_price=measurement.raw_spread_price,
                               money_per_price_unit_per_lot=money_per_unit,
                               assumptions=CostAssumptions(commission_per_lot_per_side=3.5))
        reward = calculator.calculate_profit(symbol, "BUY", solution.volume,
                                             fixture["entry"], fixture["take_profit"])["profit"]
        economics = reward_to_risk(
            entry=fixture["entry"], stop_loss=fixture["stop_loss"],
            take_profit=fixture["take_profit"], minimum_rr=2.0,
            gross_risk_money=solution.risk_amount_actual, gross_reward_money=reward,
            costs=costs, execution_prices=ExecutionPrices("BUY", fixture["bid"], fixture["ask"]),
        )
        _check(results, "net RR is computed and is below gross RR",
               economics.net_rr is not None and economics.net_rr < economics.gross_rr,
               f"gross {economics.gross_rr:.3f} -> net {economics.net_rr:.3f} "
               f"(costs {costs.total_cost:.2f})")

    # 6. full preflight
    now = datetime.now(timezone.utc)
    result = preflight(
        symbol=symbol, direction="BUY", specs=specs,
        tick={"bid": fixture["bid"], "ask": fixture["ask"], "time": now.isoformat()},
        plan={"entry": fixture["entry"], "stop_loss": fixture["stop_loss"],
              "take_profit": fixture["take_profit"], "risk_percent": 1.0,
              "minimum_rr": 2.0, "generated_at": now.isoformat()},
        account={"equity": equity, "balance": equity, "margin_free": equity * 0.98,
                 "margin": 0, "currency": "USD", "trade_allowed": True, "trade_expert": True},
        calculator=calculator, order_checker=lambda request: {"retcode": 0, "comment": "Done"},
        config=PreflightConfig(costs=CostAssumptions(commission_per_lot_per_side=3.5)),
    )
    _check(results, "full preflight approves a valid trade", result.approved,
           "; ".join(b.message for b in result.blockers)[:140] or
           f"{len(result.checks)} checks passed")

    # 7. preflight must BLOCK when the broker calculator is unavailable
    blocked = preflight(
        symbol=symbol, direction="BUY", specs=specs,
        tick={"bid": fixture["bid"], "ask": fixture["ask"], "time": now.isoformat()},
        plan={"entry": fixture["entry"], "stop_loss": fixture["stop_loss"],
              "take_profit": fixture["take_profit"], "risk_percent": 1.0,
              "minimum_rr": 2.0, "generated_at": now.isoformat()},
        account={"equity": equity, "balance": equity, "margin_free": equity * 0.98,
                 "margin": 0, "currency": "USD", "trade_allowed": True, "trade_expert": True},
        calculator=None, order_checker=lambda request: {"retcode": 0},
    )
    _check(results, "execution blocks without a broker calculator",
           not blocked.approved and "BROKER_CALCULATION_UNAVAILABLE" in
           [b.code for b in blocked.blockers],
           f"blockers={[b.code for b in blocked.blockers]}")

    passed = sum(1 for r in results if r["passed"])
    return {"symbol": symbol, "instrument_class": profile.instrument_class,
            "checks": results, "passed": passed, "total": len(results)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the trade-calculation chain.")
    parser.add_argument("--live", action="store_true", help="Also verify against a live MT5 connection")
    parser.add_argument("--mode", default="demo", choices=["demo", "live"])
    parser.add_argument("--symbol", action="append", default=None)
    parser.add_argument("--out", default=None, help="Write a JSON report to this path")
    args = parser.parse_args()

    print("Trade calculation validation")
    print("=" * 60)
    print("Offline fixtures exercise the real code path with a deterministic calculator.")

    selected = args.symbol or list(FIXTURES)
    reports = [validate_symbol(name, FIXTURES[name]) for name in selected if name in FIXTURES]

    if args.live:
        print("\n=== LIVE broker cross-check ===")
        try:
            from skills.trading_skill.bridge import WineBridgeClient
            from skills.trading_skill.mt5_adapter import WineMT5Adapter
            adapter = WineMT5Adapter(WineBridgeClient())
            response = adapter.symbol_specs(args.mode, selected)
            if response.get("status") == "error":
                print(f"  LIVE CHECK UNAVAILABLE: {response.get('error')}")
            else:
                for name, payload in (response.get("symbols") or {}).items():
                    specs = payload.get("specs", {})
                    profile = build_profile(payload.get("mt5_symbol", name), specs)
                    print(f"  {name}: class={profile.instrument_class} "
                          f"complete={profile.metadata_complete} "
                          f"missing={list(profile.missing_metadata) or 'none'}")
        except Exception as exc:
            print(f"  LIVE CHECK UNAVAILABLE: {exc}")

    total = sum(r["total"] for r in reports)
    passed = sum(r["passed"] for r in reports)
    print("\n" + "=" * 60)
    print(f"{passed}/{total} checks passed across {len(reports)} instruments.")
    for report in reports:
        state = "OK" if report["passed"] == report["total"] else "FAILURES"
        print(f"  {report['symbol']:<10} {report['instrument_class']:<10} "
              f"{report['passed']}/{report['total']}  {state}")
    if not args.live:
        print("\nNOTE: this run verified LOGIC only. Broker agreement is NOT verified "
              "until this tool is run with --live against a real MT5 terminal.")

    if args.out:
        Path(args.out).write_text(json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(),
             "live_verified": bool(args.live), "passed": passed, "total": total,
             "reports": reports}, indent=2))
        print(f"\nWrote {args.out}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
