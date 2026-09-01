# Broker Symbol Calculation Report

> **STATUS: NOT YET GENERATED FROM A LIVE BROKER.**
>
> This file is a placeholder describing what the audit produces and how to run
> it. No MT5 terminal was reachable from the environment in which the trading
> logic was corrected, so **no live broker data has been collected**. Do not
> treat any symbol as execution-safe until this report has been regenerated
> against your actual broker.

---

## How to generate

```bash
# Default symbol set (FX majors, crosses, metals, crypto, indices, energy)
python tools/audit_broker_symbols.py --mode demo

# A specific list
python tools/audit_broker_symbols.py --mode demo --symbols EURUSD GBPJPY XAUUSD BTCUSD US30
```

Outputs, written to `docs/`:

| File | Contents |
|---|---|
| `BROKER_SYMBOL_CALCULATION_REPORT.md` | This report, populated |
| `broker_symbol_audit.json` | Full machine-readable specification per symbol |
| `broker_symbol_audit.csv` | Flat table for spreadsheet review |

## Safety

The audit is **strictly read-only**. It calls only:

- `symbol_info` / `symbol_info_tick` (read)
- `order_calc_profit` (a pure calculation; does not touch the trade server)
- `order_calc_margin` (a pure calculation; does not touch the trade server)

It **never** calls `order_send`, and it never invokes the bridge's `execute`
operation. The generated report records `orders_sent: 0` explicitly.

---

## What is checked per symbol

**Specification captured**

`trade_calc_mode`, `trade_mode`, `trade_exemode`, `digits`, `point`,
`trade_tick_size`, `trade_tick_value`, `trade_tick_value_profit`,
`trade_tick_value_loss`, `trade_contract_size`, `volume_min`/`max`/`step`/`limit`,
`currency_base`/`currency_profit`/`currency_margin`,
`margin_initial`/`maintenance`/`hedged`, `trade_stops_level`,
`trade_freeze_level`, `filling_mode`, `swap_long`/`short`/`mode`/`rollover3days`,
`path`, `description`.

**Derived and verified**

| Check | Meaning |
|---|---|
| Instrument class | Derived from `trade_calc_mode` and the currency fields — never from the symbol name |
| `pip_size` | A real pip for FX; **`None`** for metals, crypto, indices, energy and equities |
| `display_unit` | `pips` / `points` / `price` |
| Metadata completeness | Which required fields, if any, are missing |
| `order_calc_profit` | Profit for `volume_min` over a 100-point move, in account currency |
| `order_calc_margin` | Required margin for `volume_min` at the live price |
| Tick-value approximation error | How far `distance/tick_size*tick_value` diverges from the broker's own figure — the error that made the old fallback unsafe |
| `execution_safe` | `true` only when metadata is complete, trade mode is FULL, and both broker calculators answered |

A symbol that is not `execution_safe` is blocked by
`execution_preflight.preflight()` with `BROKER_METADATA_INCOMPLETE` or
`BROKER_CALCULATION_UNAVAILABLE`. There is no generic fallback.

---

## Report structure once generated

```
# Broker Symbol Calculation Report

- Generated: <timestamp>
- Account mode: demo|live
- Read-only audit. Orders sent: 0
- Symbols resolved: N / M
- Safe for automatic execution: X
- Blocked: Y

## FX_MAJOR (n symbols)
| Symbol | Digits | Point | Tick size | Tick value | Contract | Pip | Unit |
  Vol min/step/max | Stops | Profit 100pt | Margin | Safe |

## FX_CROSS  ...
## METAL     ...
## CRYPTO    ...
## INDEX     ...
## ENERGY    ...

## Blocked symbols
| Symbol | Blockers |

## Unresolved symbols
| Symbol | Reason |
```

---

## What to look for when you run it

1. **Every symbol you intend to trade must show `Safe = YES`.** Anything else
   will be blocked at execution, by design.
2. **`Pip` must be blank for metals, crypto and indices.** A pip value on gold
   indicates the broker metadata is misreporting `trade_calc_mode`.
3. **Compare `Profit 100pt` against the tick-value approximation** in the JSON
   (`tick_value_approximation_error`). A large error on cross-currency pairs is
   expected and is precisely why the generic formula was removed.
4. **`Stops` (stops_level) drives the minimum stop distance.** Strategies whose
   natural stop is tighter than `stops_level x 1.5` cannot be traded on that
   symbol with that broker.
5. **Check `volume_min` against your risk budget.** If the broker minimum lot
   risks more than the configured percentage, `solve_volume_for_risk` blocks with
   `VOLUME_OUT_OF_RANGE` rather than over-risking.

---

## Offline validation already performed

While no live broker data exists, the calculation chain itself has been
validated against deterministic fixtures covering one instrument per class:

| Symbol | Class | Checks |
|---|---|---|
| EURUSD | FX_MAJOR | 18/18 |
| GBPJPY | FX_CROSS | 18/18 |
| XAUUSD | METAL | 18/18 |
| BTCUSD | CRYPTO | 17/17 |
| US30 | INDEX | 18/18 |
| **Total** | | **89/89** |

Reproduce with:

```bash
python tools/validate_trade_calculations.py
```

The GBPJPY fixture deliberately models JPY→USD conversion, so the
cross-currency case that broke the old tick-value formula is actually exercised
rather than assumed away.

This proves the **logic**. It does not prove **broker agreement**. Run
`python tools/validate_trade_calculations.py --live --mode demo` for that.
