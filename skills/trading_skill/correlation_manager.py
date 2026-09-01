from __future__ import annotations

from typing import Any
import math
from core.price_units import is_metal_symbol
from core import config


def normalize_symbol(symbol: Any) -> str:
    return "".join(ch for ch in str(symbol or "").upper() if ch.isalnum())


def split_fx_symbol(symbol: Any) -> tuple[str | None, str | None]:
    key = normalize_symbol(symbol)
    for suffix in (".A", ".M", "_A", "_M"):
        key = key.replace(suffix, "")
    if len(key) < 6:
        return None, None
    majors = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"}
    for start in range(0, len(key) - 5):
        base, quote = key[start:start + 3], key[start + 3:start + 6]
        if base in majors and quote in majors:
            return base, quote
    return None, None


def currency_exposure(
    symbol: Any,
    direction: str,
    volume: float = 1.0,
    *,
    specs: dict[str, Any] | None = None,
    price: float | None = None,
) -> dict[str, float]:
    """Signed **notional** exposure per currency.

    The previous implementation treated ``volume`` (lots) as a currency amount
    and applied it identically to both legs. That is wrong twice over:

      * one lot of EURUSD is 100,000 EUR, not 1 unit, so ``contract_size``
        must be applied; and
      * the quote-leg exposure is ``base_notional * price``, not the same
        number -- 1 lot of EURUSD at 1.10 is +100,000 EUR and -110,000 USD.

    Without a price or contract size the function degrades to lot-weighted
    exposure and marks the result, rather than silently reporting a number that
    looks like notional.
    """
    base, quote = split_fx_symbol(symbol)
    if not base or not quote:
        return {}
    lots = abs(float(volume or 0) or 1.0)
    sign = 1.0 if str(direction).upper() in {"BUY", "LONG", "0"} else -1.0
    contract_size = float((specs or {}).get("contract_size", (specs or {}).get("trade_contract_size", 0)) or 0)
    base_notional = lots * contract_size if contract_size > 0 else lots
    quote_notional = base_notional * float(price) if price else base_notional
    return {base: sign * base_notional, quote: -sign * quote_notional}


def portfolio_exposure(
    positions: list[dict[str, Any]],
    *,
    specs_by_symbol: dict[str, dict[str, Any]] | None = None,
    price_by_symbol: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Aggregate net notional exposure per currency across the whole book.

    Three EURUSD-correlated longs are a single concentrated EUR bet; counting
    them as three independent 1% risks understates the real exposure.
    """
    specs_by_symbol = specs_by_symbol or {}
    price_by_symbol = price_by_symbol or {}
    net: dict[str, float] = {}
    gross: dict[str, float] = {}
    incomplete: list[str] = []
    for position in positions or []:
        symbol = str(position.get("symbol") or "")
        specs = specs_by_symbol.get(symbol)
        price = price_by_symbol.get(symbol) or position.get("price_current") or position.get("price_open")
        if not specs or not price:
            incomplete.append(symbol)
        exposure = currency_exposure(
            symbol, position.get("type", position.get("direction", "BUY")),
            position.get("volume", 1.0), specs=specs,
            price=float(price) if price else None,
        )
        for currency, amount in exposure.items():
            net[currency] = net.get(currency, 0.0) + amount
            gross[currency] = gross.get(currency, 0.0) + abs(amount)
    return {
        "net_exposure": {k: round(v, 2) for k, v in sorted(net.items())},
        "gross_exposure": {k: round(v, 2) for k, v in sorted(gross.items())},
        "largest_net_currency": max(net.items(), key=lambda kv: abs(kv[1]))[0] if net else None,
        "largest_net_amount": round(max((abs(v) for v in net.values()), default=0.0), 2),
        "notional_complete": not incomplete,
        "symbols_missing_specs_or_price": sorted(set(incomplete)),
        "basis": ("Notional per currency from contract_size and price."
                  if not incomplete else
                  "PARTIAL: some positions lacked contract_size or price and were counted in lots."),
    }


def _returns(values: list[float]) -> list[float]:
    clean = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v)) and float(v) > 0]
    return [math.log(clean[i] / clean[i - 1]) for i in range(1, len(clean)) if clean[i - 1] > 0]


def align_series(
    series_a: list[dict[str, Any]],
    series_b: list[dict[str, Any]],
) -> tuple[list[float], list[float], int]:
    """Pair closes by TIMESTAMP, not by list position.

    Two symbols rarely have identical bar counts -- different sessions,
    holidays, or a missed tick shift one series relative to the other. Zipping
    two raw lists then correlates Monday against Tuesday and produces a number
    that is confidently wrong. Only timestamps present in both series are used.
    """
    def index(series):
        out = {}
        for row in series or []:
            key = row.get("time", row.get("timestamp"))
            try:
                close = float(row.get("close"))
            except (TypeError, ValueError):
                continue
            if key is not None and close > 0:
                out[key] = close
        return out

    map_a, map_b = index(series_a), index(series_b)
    shared = sorted(set(map_a) & set(map_b))
    dropped = (len(map_a) - len(shared)) + (len(map_b) - len(shared))
    return [map_a[k] for k in shared], [map_b[k] for k in shared], dropped


def correlate_candles(
    candles_a: list[dict[str, Any]],
    candles_b: list[dict[str, Any]],
    lookback: int = 100,
    minimum_samples: int = 30,
) -> dict[str, Any]:
    """Timestamp-aligned rolling correlation with an explicit sample count."""
    closes_a, closes_b, dropped = align_series(candles_a, candles_b)
    value = rolling_correlation(closes_a, closes_b, lookback, minimum_samples)
    samples = max(0, min(len(closes_a), len(closes_b)) - 1)
    return {
        "correlation": value,
        "aligned_bars": len(closes_a),
        "samples": min(samples, lookback),
        "unaligned_bars_dropped": dropped,
        "minimum_samples": minimum_samples,
        "reliable": value is not None,
        "reason": ("Timestamp-aligned log-return correlation."
                   if value is not None else
                   f"Fewer than {minimum_samples} timestamp-aligned returns; correlation not reported."),
    }


def rolling_correlation(prices_a: list[float], prices_b: list[float], lookback: int = 100,
                        minimum_samples: int = 30) -> float | None:
    ra, rb = _returns(prices_a)[-lookback:], _returns(prices_b)[-lookback:]
    n = min(len(ra), len(rb))
    if n < max(2, int(minimum_samples)):
        return None
    ra, rb = ra[-n:], rb[-n:]
    mean_a = sum(ra) / n
    mean_b = sum(rb) / n
    covariance = sum((a - mean_a) * (b - mean_b) for a, b in zip(ra, rb))
    var_a = sum((a - mean_a) ** 2 for a in ra)
    var_b = sum((b - mean_b) ** 2 for b in rb)
    if var_a <= 0 or var_b <= 0:
        return None
    return covariance / math.sqrt(var_a * var_b)


def check_shared_currency(
    candidate_symbol: str,
    candidate_direction: str,
    positions: list[dict[str, Any]],
    strict: bool = True,
) -> dict[str, Any]:
    candidate = currency_exposure(candidate_symbol, candidate_direction)
    conflicts: list[dict[str, Any]] = []
    for pos in positions:
        exposure = currency_exposure(pos.get("symbol"), pos.get("type", pos.get("direction", "BUY")), pos.get("volume", 1.0))
        shared = sorted(set(candidate) & set(exposure))
        if shared and strict:
            conflicts.append({
                "symbol": pos.get("symbol"),
                "ticket": pos.get("ticket"),
                "shared_currencies": shared,
                "candidate_exposure": {c: candidate.get(c, 0.0) for c in shared},
                "existing_exposure": {c: exposure.get(c, 0.0) for c in shared},
            })
    return {
        "valid": not conflicts,
        "candidate_exposure": candidate,
        "conflicts": conflicts,
        "shared_currencies": sorted({c for item in conflicts for c in item["shared_currencies"]}),
    }


def evaluate_portfolio(
    candidate_symbol: str,
    candidate_direction: str,
    candidate_risk_percent: float,
    positions: list[dict[str, Any]],
    *,
    max_positions: int,
    max_open_risk: float,
    strict_shared_currency: bool = True,
    specs_by_symbol: dict[str, dict[str, Any]] | None = None,
    price_by_symbol: dict[str, float] | None = None,
    max_currency_notional: float | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    known_risk = 0.0
    unknown_risk: list[dict[str, Any]] = []
    for pos in positions:
        risk = pos.get("risk_percent")
        if risk is None:
            unknown_risk.append(pos)
        else:
            try:
                known_risk += max(0.0, float(risk))
            except (TypeError, ValueError):
                unknown_risk.append(pos)
    if unknown_risk:
        reasons.append("Existing position risk cannot be verified because at least one open position has unknown SL risk.")
    if len(positions) >= max_positions:
        reasons.append(f"Maximum positions reached ({len(positions)}/{max_positions}).")
    if known_risk + candidate_risk_percent > max_open_risk + 1e-9:
        reasons.append(f"Open risk would exceed {max_open_risk:.2f}% ({known_risk:.2f}% existing + {candidate_risk_percent:.2f}% candidate).")
    shared = check_shared_currency(candidate_symbol, candidate_direction, positions, strict_shared_currency)
    if not shared["valid"]:
        reasons.append("Candidate shares currency exposure with an existing position.")
    if is_metal_symbol(candidate_symbol):
        metal_positions = [pos for pos in positions if is_metal_symbol(pos.get("symbol"))]
        max_metals = int(getattr(config, "TRADING_MAX_METAL_POSITIONS", 1))
        if len(metal_positions) >= max_metals:
            reasons.append(f"Maximum metal positions reached ({len(metal_positions)}/{max_metals}).")
    exposure = portfolio_exposure(positions, specs_by_symbol=specs_by_symbol,
                                  price_by_symbol=price_by_symbol)
    if max_currency_notional is not None and exposure["largest_net_amount"] > max_currency_notional:
        reasons.append(
            f"Net {exposure['largest_net_currency']} exposure "
            f"{exposure['largest_net_amount']:,.0f} exceeds the "
            f"{max_currency_notional:,.0f} portfolio limit."
        )

    return {
        "valid": not reasons,
        "reasons": reasons,
        "portfolio_exposure": exposure,
        "known_open_risk_percent": known_risk,
        "unknown_risk_positions": unknown_risk,
        "candidate_risk_percent": candidate_risk_percent,
        "aggregate_risk_percent": known_risk + candidate_risk_percent,
        "shared_currency": shared,
    }
