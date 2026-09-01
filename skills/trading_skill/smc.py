"""SMC evidence assembly.

This module no longer implements its own structure/liquidity/FVG heuristics. It
composes the corrected engines:

  * :mod:`market_structure` -- protected swings, BOS/CHoCH, liquidity pools,
    dealing range, displacement
  * :mod:`fvg_engine`       -- FVG/IFVG lifecycle, order blocks, sweep continuation
  * :mod:`amd`              -- ordered AMD phase machine
  * :mod:`session_levels`   -- previous-day and session liquidity

Nothing here declares a trade. It produces evidence; ``strategies.evaluate_smc``
decides whether that evidence satisfies the SMC setup definition.
"""

from __future__ import annotations

from typing import Any, Sequence

from .amd import AMDConfig, detect_amd
from .fvg_engine import detect_fvg_playbook
from .indicators import atr
from .market_structure import (
    BULLISH, BEARISH, SIDEWAYS, StructureState, build_dealing_range,
    build_liquidity_pools, build_structure, closed_candles, detect_liquidity_sweep,
    displacement_at, find_swings, _close, _high, _low, _open, _time,
)
from .session_levels import liquidity_levels_from_sessions

MINIMUM_SMC_CANDLES = 40


class ZoneRegistry:
    """Keep zone identity and lifecycle continuity across repeated scans."""

    def __init__(self) -> None:
        self._zones: dict[str, dict[str, Any]] = {}

    def observe(self, zone: dict[str, Any], timeframe: str | None, kind: str) -> dict[str, Any]:
        identity = zone.get("zone_id") or (
            f"{timeframe or '-'}:{kind}:{zone.get('formation_index')}:{zone.get('low')}:{zone.get('high')}"
        )
        previous = self._zones.get(identity, {})
        merged = {**previous, **zone, "zone_id": identity, "timeframe": timeframe, "kind": kind}
        self._zones[identity] = merged
        return merged

    def prune(self, timeframe: str | None, current_index: int, max_age: int = 100) -> None:
        cutoff = current_index - max(1, int(max_age))
        doomed = []
        for key, zone in self._zones.items():
            if timeframe is not None and zone.get("timeframe") != timeframe:
                continue
            try:
                formation = int(zone.get("formation_index"))
            except (TypeError, ValueError):
                continue
            if formation < cutoff:
                doomed.append(key)
        for key in doomed:
            self._zones.pop(key, None)

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._zones.values())


# Backwards-compatible helper used by analysis._support_resistance.
def _swing_points(candles: Sequence[dict[str, Any]], strength: int = 2):
    points = find_swings(list(candles), strength)
    highs = [(p.index, p.price) for p in points if p.kind == "swing_high"]
    lows = [(p.index, p.price) for p in points if p.kind == "swing_low"]
    return highs, lows


def _structure(candles: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Legacy structure view backed by the new state machine."""
    state = build_structure(candles)
    data = state.as_dict()
    data["labels"] = [
        {"type": "HH" if b.price > a.price else "LH" if b.price < a.price else "EQ",
         "index": b.index, "price": b.price}
        for kind in ("swing_high", "swing_low")
        for a, b in zip(
            [p for p in state.swings if p.kind == kind],
            [p for p in state.swings if p.kind == kind][1:],
        )
    ]
    return data


_ZONE_AGE = {"M1": 80, "M5": 80, "M15": 120, "M30": 140, "H1": 160,
             "H4": 180, "D1": 220, "W1": 260, "MN": 300}


def detect_smc(
    candles: Sequence[dict[str, Any]],
    direction: str | None = None,
    timeframe: str | None = None,
    registry: ZoneRegistry | None = None,
    *,
    trades_24_7: bool = False,
    amd_config: AMDConfig | None = None,
) -> dict[str, Any]:
    """Return observable SMC evidence with explicit lifecycle and provenance."""
    rows = closed_candles(candles)
    if len(rows) < MINIMUM_SMC_CANDLES:
        return {
            "status": "insufficient", "valid": False,
            "reason": f"At least {MINIMUM_SMC_CANDLES} completed candles are required for SMC context.",
            "required_candles": MINIMUM_SMC_CANDLES, "available_candles": len(rows),
        }

    key = str(timeframe or "").upper()
    if registry is not None:
        registry.prune(timeframe, len(rows) - 1, _ZONE_AGE.get(key, 140))

    structure = build_structure(rows, timeframe=timeframe)
    external = liquidity_levels_from_sessions(rows, trades_24_7=trades_24_7)
    pools = build_liquidity_pools(rows, structure, external_levels=external)
    sweep = detect_liquidity_sweep(rows, pools)
    dealing_range = build_dealing_range(rows, structure)
    atr_value = atr(rows, 14)

    playbook = detect_fvg_playbook(
        rows, structure=structure, dealing_range=dealing_range,
        liquidity_sweep=sweep, atr_value=atr_value, timeframe=timeframe,
    )
    amd = detect_amd(rows, structure=structure, timeframe=timeframe, config=amd_config)

    gaps = playbook["fair_value_gaps"]
    blocks = playbook["order_blocks"]
    if registry is not None:
        gaps = [registry.observe(gap, timeframe, "FVG") for gap in gaps]
        blocks = [registry.observe(block, timeframe, "OB") for block in blocks]

    last = rows[-1]
    current_price = _close(last)
    last_displacement = displacement_at(rows, len(rows) - 1)
    event = structure.last_event

    structure_view = structure.as_dict()
    structure_view["displacement"] = last_displacement
    range_view = dealing_range.as_dict() if dealing_range else {}
    if range_view:
        range_view["current_price"] = current_price

    bias = structure.bias
    target_price = None
    target_basis = None
    if bias == BULLISH:
        upside = [p for p in pools if p.side == "buy_side" and p.price > current_price and not p.swept]
        if upside:
            best = min(upside, key=lambda p: (p.price - current_price))
            target_price, target_basis = best.price, f"nearest unswept buy-side liquidity ({best.kind})"
    elif bias == BEARISH:
        downside = [p for p in pools if p.side == "sell_side" and p.price < current_price and not p.swept]
        if downside:
            best = min(downside, key=lambda p: (current_price - p.price))
            target_price, target_basis = best.price, f"nearest unswept sell-side liquidity ({best.kind})"

    evidence: dict[str, Any] = {
        "status": "ready",
        "valid": True,
        "timeframe": timeframe,
        "current_price": current_price,
        "market_structure": structure_view,
        "structure": structure_view,                     # legacy alias
        "structure_event": event.as_dict() if event else None,
        "structure_shift": (f"{event.direction}_{event.type}" if event else None),
        "liquidity_pools": [pool.as_dict() for pool in pools],
        "liquidity_sweep": sweep.as_dict() if sweep else None,
        "external_levels": external,
        "dealing_range": range_view,
        "location": range_view.get("location"),
        "preferred_location": ("discount" if bias == BULLISH else "premium" if bias == BEARISH else None),
        "displacement": bool(last_displacement.get("displacement")),
        "displacement_detail": last_displacement,
        "fair_value_gaps": gaps,
        "tradeable_gaps": [gap for gap in gaps if gap.get("tradeable")],
        "inversion_fvgs": playbook["inversion_fvgs"],
        "ifvg": {
            "status": "ready",
            "candidates": playbook["inversion_fvgs"],
            "confirmed": playbook["confirmed_inversions"],
            "tradeable": bool(playbook["confirmed_inversions"]),
        },
        "order_blocks": blocks,
        "order_block": blocks[-1] if blocks else None,
        "continuation": playbook["continuation"],
        "amd": amd.as_dict(),
        "target_liquidity": {
            "type": "buy_side_liquidity" if bias == BULLISH else "sell_side_liquidity",
            "price": target_price,
            "timeframe": timeframe,
            "basis": target_basis or "no unswept opposing liquidity identified",
        },
        "setup_model": ("SWEEP_REVERSAL" if sweep and sweep.valid else
                        "BOS_CONTINUATION" if event and event.type == "BOS" else "NO_MODEL"),
        "decision_reasons": [
            "SMC zones are monitoring locations, not entries.",
            "A setup requires a protected-swing break plus an unexpired directional zone.",
        ],
    }

    sequence = {
        "liquidity": bool(sweep and sweep.valid),
        "structural_event": bool(event),
        "displacement": bool(last_displacement.get("displacement")),
        "smc_zone": bool(evidence["tradeable_gaps"] or (evidence["order_block"] or {}).get("classification") == "TRADEABLE_OB"),
        "retracement": any(gap.get("status") == "PARTIALLY_MITIGATED" for gap in gaps),
        "entry_confirmation": False,
    }
    sequence["complete"] = all(sequence[key] for key in ("liquidity", "structural_event", "displacement", "smc_zone"))
    evidence["sequence"] = sequence
    evidence["decision"] = "WAIT" if any(sequence.values()) and not sequence["complete"] else "NO_SETUP"

    if direction:
        expected = BULLISH if direction == "BUY" else BEARISH
        evidence["directional_confluence"] = bool(
            (event and event.direction == expected)
            or any(gap.get("type") == expected and gap.get("tradeable") for gap in gaps)
            or ((evidence["order_block"] or {}).get("type") == expected)
        )
    return evidence
