"""Price-unit conversions driven by broker metadata.

This module is now a thin compatibility layer over
:mod:`skills.trading_skill.instruments`, which classifies instruments from the
broker's own ``trade_calc_mode`` / ``currency_base`` / ``currency_profit``
fields instead of matching substrings in the symbol name. Name matching failed
for broker-suffixed symbols (``XAUUSD.a``, ``GOLDmicro``, ``EURUSD.VX``) and
silently applied FX pip assumptions to metals and crypto.

The public function signatures are unchanged so existing callers keep working.
"""
from __future__ import annotations

from typing import Any


def _profile(symbol: str, specs: dict[str, Any] | None):
    from skills.trading_skill.instruments import build_profile
    return build_profile(symbol, specs or {})


def is_metal_symbol(symbol: str, specs: dict[str, Any] | None = None) -> bool:
    """Classify from broker metadata when available, name only as a last resort."""
    from skills.trading_skill.instruments import METAL
    return _profile(symbol, specs).instrument_class == METAL


def is_forex_symbol(symbol: str, specs: dict[str, Any] | None = None) -> bool:
    from skills.trading_skill.instruments import FX_CLASSES
    return _profile(symbol, specs).instrument_class in FX_CLASSES


def point_from_specs(specs: dict[str, Any]) -> float:
    return float((specs or {}).get("point", 0) or 0)


def pip_size_from_specs(symbol: str, specs: dict[str, Any]) -> float:
    """One conventional FX pip in price units, or ``0.0`` when pips do not apply.

    Metals, crypto, indices, energy and equities have **no pip**. They return
    ``0.0`` so that a caller dividing by it is forced to handle the case rather
    than silently producing a number that means nothing.
    """
    return float(_profile(symbol, specs).pip_size or 0.0)


def normalize_spread(symbol: str, raw_spread: float, specs: dict[str, Any]) -> dict[str, Any]:
    """Express a raw price spread in every unit that is valid for the instrument."""
    profile = _profile(symbol, specs)
    raw = float(raw_spread or 0)
    return {
        "spread_price": raw,
        "spread_points": profile.to_points(raw),
        "spread_pips": profile.to_pips(raw),
        "spread_ticks": profile.to_ticks(raw),
        "spread_unit": profile.display_unit,
        "instrument_class": profile.instrument_class,
        "pip_size": profile.pip_size,
        "point": profile.point,
        "metadata_complete": profile.metadata_complete,
    }


def describe_distance(symbol: str, distance: float, specs: dict[str, Any]) -> str:
    """Human-readable distance in the instrument's own natural unit."""
    return _profile(symbol, specs).describe_distance(float(distance or 0))
