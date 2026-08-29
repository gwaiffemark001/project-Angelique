"""Broker-metadata-driven price unit conversions.

For FX symbols this module exposes conventional pips. For metals such as
XAUUSD, the UI/risk engine should use MT5 points and raw price distance rather
than inventing a universal "pip" convention.
"""
from __future__ import annotations

from typing import Any


def is_metal_symbol(symbol: str) -> bool:
    key = str(symbol or "").upper().replace("/", "")
    return any(token in key for token in ("XAU", "XAG", "XPT", "XPD", "GOLD", "SILVER"))


def point_from_specs(specs: dict[str, Any]) -> float:
    return float(specs.get("point", 0) or 0)


def pip_size_from_specs(symbol: str, specs: dict[str, Any]) -> float:
    """Return one conventional FX pip in price units.

    For non-FX instruments, callers should normally use MT5 points and raw
    price distance instead of treating the instrument's point as a pip.
    """
    point = point_from_specs(specs)
    digits = int(specs.get("digits", 0) or 0)
    if is_metal_symbol(symbol):
        return 0.0
    if point > 0:
        return point * 10 if digits in {3, 5} else point
    if "JPY" in str(symbol).upper():
        return 0.01
    return 0.0001


def normalize_spread(symbol: str, raw_spread: float, specs: dict[str, Any]) -> dict[str, float | str | None]:
    raw = float(raw_spread or 0)
    point = point_from_specs(specs)
    points = raw / point if point > 0 else None
    pip = pip_size_from_specs(symbol, specs)
    pips = raw / pip if pip > 0 else None
    if is_metal_symbol(symbol):
        return {"spread_price": raw, "spread_points": points, "spread_pips": None, "spread_unit": "points"}
    return {"spread_price": raw, "spread_points": points, "spread_pips": pips, "spread_unit": "pips"}
