"""Instrument-aware price units and spread policy.

The broker's MT5 symbol specification is authoritative for executable price
increments. Conventional FX pips are only used for FX symbols; metals use
broker ticks/points and crypto uses a percentage-of-price spread policy with
an MT5-tick floor. This keeps display, execution gates and risk math on the
same source of truth.
"""
from __future__ import annotations

from typing import Any
import re


_FIAT_CODES = {
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "SGD", "HKD",
    "NOK", "SEK", "DKK", "PLN", "CZK", "HUF", "TRY", "ZAR", "MXN", "CNH",
}
_MAJOR_PAIRS = {
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD",
}
_CRYPTO_BASES = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "TRX",
    "LINK", "LTC", "BCH", "MATIC", "SHIB", "UNI", "ATOM", "ETC", "XLM",
    "FIL", "APT", "ARB", "OP", "SUI", "NEAR", "ICP", "ALGO", "VET",
}
_CRYPTO_QUOTES = {"USD", "USDT", "USDC", "EUR", "BTC", "ETH"}


def canonical_symbol(symbol: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(symbol or "").upper())


def is_metal_symbol(symbol: str) -> bool:
    key = canonical_symbol(symbol)
    return any(token in key for token in ("XAU", "XAG", "XPT", "XPD", "GOLD", "SILVER"))


def fx_pair_codes(symbol: str) -> tuple[str, str] | None:
    key = canonical_symbol(symbol)
    for start in range(max(1, len(key) - 10)):
        candidate = key[start:start + 6]
        if len(candidate) == 6:
            base, quote = candidate[:3], candidate[3:]
            if base in _FIAT_CODES and quote in _FIAT_CODES:
                return base, quote
    return None


def crypto_pair_codes(symbol: str) -> tuple[str, str] | None:
    key = canonical_symbol(symbol)
    for quote in sorted(_CRYPTO_QUOTES, key=len, reverse=True):
        if key.endswith(quote):
            base = key[:-len(quote)]
            if base in _CRYPTO_BASES:
                return base, quote
    for base in sorted(_CRYPTO_BASES, key=len, reverse=True):
        if key.startswith(base):
            remainder = key[len(base):]
            if remainder in _CRYPTO_QUOTES:
                return base, remainder
    return None


def instrument_class(symbol: str, specs: dict[str, Any] | None = None) -> str:
    """Classify a symbol for unit and spread policy selection."""
    key = canonical_symbol(symbol)
    if is_metal_symbol(key):
        return "METAL"
    pair = fx_pair_codes(key)
    if pair:
        compact = "".join(pair)
        return "FX_MAJOR" if compact in _MAJOR_PAIRS else "FX_CROSS"
    if crypto_pair_codes(key) or any(base in key[:6] for base in _CRYPTO_BASES):
        return "CRYPTO"
    # Broker metadata can identify a non-standard symbol even if its name is
    # not in our compact classification table. MT5 trade_calc_mode values are
    # intentionally not hard-coded here; the caller can override via specs.
    asset = str((specs or {}).get("asset_class", "")).upper()
    if asset in {"FX_MAJOR", "FX_CROSS", "CRYPTO", "METAL"}:
        return asset
    return "OTHER"


def point_from_specs(specs: dict[str, Any]) -> float:
    return float(specs.get("point", 0) or 0)


def tick_size_from_specs(specs: dict[str, Any]) -> float:
    tick = float(specs.get("tick_size", specs.get("trade_tick_size", 0)) or 0)
    if tick > 0:
        return tick
    return point_from_specs(specs)


def pip_size_from_specs(symbol: str, specs: dict[str, Any]) -> float:
    """Return one conventional FX pip in price units, only for FX symbols."""
    if instrument_class(symbol, specs) not in {"FX_MAJOR", "FX_CROSS"}:
        return 0.0
    point = point_from_specs(specs)
    digits = int(specs.get("digits", 0) or 0)
    if point > 0:
        return point * 10 if digits in {3, 5} else point
    base_quote = fx_pair_codes(symbol)
    if base_quote and base_quote[1] == "JPY":
        return 0.01
    return 0.0001


def normalize_spread(symbol: str, raw_spread: float, specs: dict[str, Any]) -> dict[str, float | str | None]:
    """Normalize a raw price spread into executable and display units."""
    raw = abs(float(raw_spread or 0))
    point = point_from_specs(specs)
    tick = tick_size_from_specs(specs)
    points = raw / point if point > 0 else None
    ticks = raw / tick if tick > 0 else None
    klass = instrument_class(symbol, specs)
    pip = pip_size_from_specs(symbol, specs)
    pips = raw / pip if pip > 0 else None
    if klass in {"FX_MAJOR", "FX_CROSS"}:
        return {
            "instrument_class": klass,
            "spread_price": raw,
            "spread_points": points,
            "spread_ticks": ticks,
            "spread_pips": pips,
            "spread_unit": "pips",
            "price_unit": pip,
        }
    if klass == "METAL":
        return {
            "instrument_class": klass,
            "spread_price": raw,
            "spread_points": points,
            "spread_ticks": ticks,
            "spread_pips": None,
            "spread_unit": "ticks" if ticks is not None else "points",
            "price_unit": tick or point,
        }
    if klass == "CRYPTO":
        return {
            "instrument_class": klass,
            "spread_price": raw,
            "spread_points": points,
            "spread_ticks": ticks,
            "spread_pips": None,
            "spread_unit": "price",
            "price_unit": tick or point,
        }
    return {
        "instrument_class": klass,
        "spread_price": raw,
        "spread_points": points,
        "spread_ticks": ticks,
        "spread_pips": None,
        "spread_unit": "ticks" if ticks is not None else "price",
        "price_unit": tick or point,
    }


def spread_policy(symbol: str, specs: dict[str, Any] | None, mode: str = "DAY_TRADING") -> dict[str, Any]:
    """Return the max spread policy in the symbol's native/comparable unit.

    Defaults are deliberately conservative and configurable. The comparison
    used by execution is always converted back to raw price units, so a BTC
    spread is never compared with an FX pip threshold or a gold MT5-point
    threshold.
    """
    specs = specs or {}
    mode_key = str(mode or "DAY_TRADING").upper()
    swing = mode_key in {"SWING", "SWING_TRADING"}
    klass = instrument_class(symbol, specs)
    point = point_from_specs(specs)
    tick = tick_size_from_specs(specs)

    if klass == "FX_MAJOR":
        max_pips = 3.0 if swing else 1.5
        pip = pip_size_from_specs(symbol, specs)
        max_price = max_pips * pip if pip > 0 else 0.0
        return {"instrument_class": klass, "max_value": max_pips, "max_unit": "pips", "max_price": max_price, "source": "policy:FX_MAJOR"}

    if klass == "FX_CROSS":
        max_pips = 4.0 if swing else 2.5
        pip = pip_size_from_specs(symbol, specs)
        max_price = max_pips * pip if pip > 0 else 0.0
        return {"instrument_class": klass, "max_value": max_pips, "max_unit": "pips", "max_price": max_price, "source": "policy:FX_CROSS"}

    if klass == "METAL":
        max_ticks = 60.0 if swing else 40.0
        max_price = max_ticks * tick if tick > 0 else (max_ticks * point if point > 0 else 0.0)
        return {"instrument_class": klass, "max_value": max_ticks, "max_unit": "ticks", "max_price": max_price, "source": "policy:METAL"}

    if klass == "CRYPTO":
        # Crypto spreads are best bounded relative to the symbol price because
        # different coins can have radically different tick sizes.  A tick
        # floor protects tiny-priced symbols from an unrealistically small
        # percentage ceiling.
        mid = None
        try:
            bid, ask = float(specs.get("bid", 0) or 0), float(specs.get("ask", 0) or 0)
            if bid > 0 and ask > 0:
                mid = (bid + ask) / 2.0
        except (TypeError, ValueError):
            mid = None
        max_pct = 0.20 if swing else 0.10
        pct_price = (mid * max_pct / 100.0) if mid else 0.0
        tick_floor = (15.0 if swing else 10.0) * tick if tick > 0 else 0.0
        max_price = max(pct_price, tick_floor)
        return {"instrument_class": klass, "max_value": max_pct, "max_unit": "%", "max_price": max_price, "source": "policy:CRYPTO"}

    # Unknown assets are still protected, but never receive an FX-pip limit.
    max_ticks = 100.0 if swing else 60.0
    max_price = max_ticks * tick if tick > 0 else 0.0
    return {"instrument_class": klass, "max_value": max_ticks, "max_unit": "ticks", "max_price": max_price, "source": "policy:OTHER"}
