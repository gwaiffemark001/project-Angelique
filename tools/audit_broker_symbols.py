#!/usr/bin/env python3
"""Read-only MT5 broker symbol audit.

Connects to the MT5 bridge, pulls the **complete** specification for every
requested symbol, classifies each instrument from broker metadata, verifies
that ``order_calc_profit`` and ``order_calc_margin`` answer, and reports
exactly which symbols are safe for automatic execution.

SAFETY
------
This tool is strictly read-only. It calls only ``symbol_specs``,
``calculate_profit`` and ``calculate_margin`` -- all of which are MT5
*calculation* endpoints. **It never sends an order**, and it never calls the
``execute`` operation. ``order_calc_*`` do not touch the trade server.

Usage
-----
    python tools/audit_broker_symbols.py --mode demo
    python tools/audit_broker_symbols.py --symbols EURUSD XAUUSD BTCUSD
    python tools/audit_broker_symbols.py --out docs/ --mode demo
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills.trading_skill.instruments import (  # noqa: E402
    CRYPTO, ENERGY, EQUITY, FX_CROSS, FX_EXOTIC, FX_MAJOR, INDEX, METAL, OTHER,
    build_profile,
)

DEFAULT_SYMBOLS = [
    # FX majors
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
    # FX crosses
    "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD", "CADJPY", "CHFJPY",
    "EURCHF", "GBPAUD", "NZDJPY", "AUDNZD", "EURCAD", "GBPCAD",
    # Metals
    "XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD",
    # Crypto
    "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD",
    # Indices / energy
    "US30", "US500", "NAS100", "GER40", "UK100", "JP225",
    "USOIL", "UKOIL", "XTIUSD", "XBRUSD",
]

CLASS_ORDER = [FX_MAJOR, FX_CROSS, FX_EXOTIC, METAL, CRYPTO, INDEX, ENERGY, EQUITY, OTHER]

CSV_COLUMNS = [
    "symbol", "mt5_symbol", "instrument_class", "execution_safe", "blockers",
    "trade_calc_mode", "trade_mode", "currency_base", "currency_profit", "currency_margin",
    "digits", "point", "tick_size", "tick_value", "tick_value_profit", "tick_value_loss",
    "contract_size", "pip_size", "display_unit",
    "volume_min", "volume_max", "volume_step", "volume_limit",
    "stops_level_points", "freeze_level_points", "filling_modes",
    "swap_long", "swap_short", "swap_mode", "swap_rollover3days",
    "bid", "ask", "spread_price", "spread_display",
    "profit_1lot_100pt", "margin_1lot", "profit_source", "margin_source",
]


def _connect(mode: str):
    from skills.trading_skill.bridge import WineBridgeClient
    from skills.trading_skill.mt5_adapter import WineMT5Adapter
    return WineMT5Adapter(WineBridgeClient())


def audit_symbol(adapter, mode: str, name: str, payload: dict) -> dict:
    """Audit one symbol. Read-only."""
    specs = payload.get("specs", {}) or {}
    tick = payload.get("tick", {}) or {}
    mt5_symbol = payload.get("mt5_symbol") or name
    profile = build_profile(mt5_symbol, specs)

    bid, ask = tick.get("bid"), tick.get("ask")
    spread_price = (float(ask) - float(bid)) if (bid and ask) else None

    row: dict = {
        "symbol": name,
        "mt5_symbol": mt5_symbol,
        "instrument_class": profile.instrument_class,
        "trade_calc_mode": profile.trade_calc_mode,
        "trade_mode": profile.trade_mode,
        "trade_mode_name": profile.trade_mode_name,
        "currency_base": profile.currency_base,
        "currency_profit": profile.currency_profit,
        "currency_margin": specs.get("currency_margin"),
        "digits": profile.digits,
        "point": profile.point,
        "tick_size": profile.tick_size,
        "tick_value": profile.tick_value,
        "tick_value_profit": profile.tick_value_profit,
        "tick_value_loss": profile.tick_value_loss,
        "contract_size": profile.contract_size,
        "pip_size": profile.pip_size,
        "display_unit": profile.display_unit,
        "volume_min": profile.volume_min,
        "volume_max": profile.volume_max,
        "volume_step": profile.volume_step,
        "volume_limit": specs.get("volume_limit"),
        "stops_level_points": profile.stops_level_points,
        "freeze_level_points": profile.freeze_level_points,
        "filling_modes": "|".join(profile.filling_modes()),
        "swap_long": profile.swap_long,
        "swap_short": profile.swap_short,
        "swap_mode": profile.swap_mode,
        "swap_rollover3days": specs.get("swap_rollover3days"),
        "bid": bid, "ask": ask, "spread_price": spread_price,
        "spread_display": profile.format_distance(spread_price) if spread_price else None,
        "missing_metadata": list(profile.missing_metadata),
    }

    blockers: list[str] = []
    if profile.missing_metadata:
        blockers.append(f"BROKER_METADATA_INCOMPLETE: {', '.join(profile.missing_metadata)}")

    # -- order_calc_profit over a known distance (read-only) ----------------
    volume = profile.volume_min or 0.01
    profit_value = margin_value = None
    profit_source = margin_source = "unavailable"
    reference = float(ask or bid or 0)
    if reference > 0 and profile.point > 0:
        target = reference + profile.point * 100          # 100 points
        response = adapter.calculate_profit(mode, mt5_symbol, "BUY", volume, reference, target)
        if isinstance(response, dict) and response.get("profit") is not None:
            profit_value = float(response["profit"])
            profit_source = "order_calc_profit"
        else:
            blockers.append(f"order_calc_profit failed: {(response or {}).get('error', 'no value')}")

        margin_response = adapter.calculate_margin(mode, mt5_symbol, "BUY", volume, reference)
        if isinstance(margin_response, dict) and margin_response.get("margin") is not None:
            margin_value = float(margin_response["margin"])
            margin_source = "order_calc_margin"
        else:
            blockers.append(f"order_calc_margin failed: {(margin_response or {}).get('error', 'no value')}")
    else:
        blockers.append("No live quote; broker calculations could not be verified.")

    if not profile.trade_allowed:
        blockers.append(f"Symbol trade mode is {profile.trade_mode_name}, not FULL.")

    # -- cross-check the tick-value approximation against the broker --------
    approximation_delta = None
    if profit_value is not None and profile.tick_size > 0 and profile.tick_value:
        approximated = (profile.point * 100 / profile.tick_size) * profile.tick_value * volume
        if profit_value != 0:
            approximation_delta = abs(approximated - profit_value) / abs(profit_value)

    row.update({
        "profit_1lot_100pt": profit_value,
        "margin_1lot": margin_value,
        "profit_source": profit_source,
        "margin_source": margin_source,
        "probe_volume": volume,
        "tick_value_approximation_error": approximation_delta,
        "execution_safe": not blockers,
        "blockers": "; ".join(blockers),
        "blocker_list": blockers,
    })
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only MT5 broker symbol audit. Never sends an order.")
    parser.add_argument("--mode", default="demo", choices=["demo", "live"])
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--out", default="docs", help="Output directory")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()

    symbols = args.symbols or DEFAULT_SYMBOLS
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)

    print(f"Broker symbol audit ({args.mode}) -- READ ONLY, no orders will be sent.")
    try:
        adapter = _connect(args.mode)
    except Exception as exc:
        print(f"ERROR: could not reach the MT5 bridge: {exc}")
        return 2

    rows: list[dict] = []
    errors: dict[str, str] = {}
    for start in range(0, len(symbols), args.batch_size):
        batch = symbols[start:start + args.batch_size]
        print(f"  querying {len(batch)} symbols ...")
        try:
            response = adapter.symbol_specs(args.mode, batch)
        except Exception as exc:
            print(f"ERROR: symbol_specs failed: {exc}")
            return 2
        if response.get("status") == "error":
            print(f"ERROR: {response.get('error')}")
            return 2
        errors.update(response.get("errors", {}) or {})
        for name, payload in (response.get("symbols") or {}).items():
            try:
                rows.append(audit_symbol(adapter, args.mode, name, payload))
            except Exception as exc:
                errors[name] = f"audit failed: {exc}"

    by_class: dict[str, list[dict]] = {}
    for row in rows:
        by_class.setdefault(row["instrument_class"], []).append(row)

    safe = [r for r in rows if r["execution_safe"]]
    unsafe = [r for r in rows if not r["execution_safe"]]

    report = {
        "generated_at": started.isoformat(),
        "account_mode": args.mode,
        "read_only": True,
        "orders_sent": 0,
        "symbols_requested": len(symbols),
        "symbols_resolved": len(rows),
        "symbols_unresolved": errors,
        "execution_safe_count": len(safe),
        "execution_blocked_count": len(unsafe),
        "by_instrument_class": {k: len(v) for k, v in sorted(by_class.items())},
        "symbols": rows,
    }

    json_path = out_dir / "broker_symbol_audit.json"
    json_path.write_text(json.dumps(report, indent=2, default=str))

    csv_path = out_dir / "broker_symbol_audit.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    md_path = out_dir / "BROKER_SYMBOL_CALCULATION_REPORT.md"
    md_path.write_text(_markdown(report, by_class))

    print(f"\n{len(safe)}/{len(rows)} symbols are safe for automatic execution.")
    for row in unsafe:
        print(f"  BLOCKED {row['symbol']}: {row['blockers']}")
    print(f"\nWrote:\n  {json_path}\n  {csv_path}\n  {md_path}")
    return 0


def _markdown(report: dict, by_class: dict[str, list[dict]]) -> str:
    lines = [
        "# Broker Symbol Calculation Report",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Account mode: `{report['account_mode']}`",
        f"- **Read-only audit. Orders sent: {report['orders_sent']}.**",
        f"- Symbols resolved: {report['symbols_resolved']} / {report['symbols_requested']}",
        f"- Safe for automatic execution: **{report['execution_safe_count']}**",
        f"- Blocked: **{report['execution_blocked_count']}**",
        "",
        "## Method",
        "",
        "For each symbol the audit reads the full MT5 `symbol_info` specification, "
        "classifies the instrument from `trade_calc_mode` and the currency fields "
        "(never from the symbol name), then verifies that `order_calc_profit` and "
        "`order_calc_margin` return values. A symbol is marked execution-safe only "
        "when its metadata is complete, its trade mode is FULL, and both broker "
        "calculators answer.",
        "",
    ]
    for instrument_class in CLASS_ORDER:
        rows = by_class.get(instrument_class)
        if not rows:
            continue
        lines += [
            f"## {instrument_class} ({len(rows)} symbols)",
            "",
            "| Symbol | Digits | Point | Tick size | Tick value | Contract | Pip | Unit | "
            "Vol min/step/max | Stops | Profit 100pt | Margin | Safe |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for row in sorted(rows, key=lambda r: r["symbol"]):
            lines.append(
                f"| {row['symbol']} | {row['digits']} | {row['point']} | {row['tick_size']} | "
                f"{row['tick_value']} | {row['contract_size']} | {row['pip_size']} | "
                f"{row['display_unit']} | {row['volume_min']}/{row['volume_step']}/{row['volume_max']} | "
                f"{row['stops_level_points']} | {row['profit_1lot_100pt']} | {row['margin_1lot']} | "
                f"{'YES' if row['execution_safe'] else 'NO'} |"
            )
        lines.append("")
    blocked = [r for r in report["symbols"] if not r["execution_safe"]]
    if blocked:
        lines += ["## Blocked symbols", "", "| Symbol | Blockers |", "|---|---|"]
        lines += [f"| {r['symbol']} | {r['blockers']} |" for r in blocked]
        lines.append("")
    if report["symbols_unresolved"]:
        lines += ["## Unresolved symbols", "", "| Symbol | Reason |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(report["symbols_unresolved"].items())]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
