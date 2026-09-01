"""Accumulation -> Manipulation -> Distribution as an ordered phase machine.

The previous implementation was a heuristic pattern matcher: "20 candles of
accumulation + 10 candles after + one raid + the last candle displaced". Its
critical flaw was that the *last candle of the whole window* could retroactively
complete the distribution phase even when unrelated price action had occurred in
between.

This implementation enforces strict ordering and gives every phase its own
index, timestamp, and invalidation level:

    ACCUMULATION -> MANIPULATION (raid) -> REACTION -> DISTRIBUTION
                 -> STRUCTURAL DELIVERY -> RETRACEMENT/ENTRY

A phase can only be satisfied by price action that occurred *after* the previous
phase completed, and each phase has a bounded window. If any phase is violated
the whole sequence is invalidated rather than silently repaired.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Sequence

from .market_structure import (
    BULLISH, BEARISH, StructureState, closed_candles, displacement_at,
    _high, _low, _open, _close, _time,
)


@dataclass
class AMDConfig:
    """Every window here is *strategy policy*, not market truth."""
    accumulation_min_candles: int = 12
    accumulation_max_candles: int = 60
    #: The accumulation range must be compressed: its width must not exceed this
    #: multiple of the average candle range inside it.
    accumulation_compression_max: float = 6.0
    #: A raid must occur within this many candles of the accumulation ending.
    manipulation_window: int = 15
    #: Price must react back into the range within this many candles of the raid.
    reaction_window: int = 6
    #: Displacement/delivery must occur within this many candles of the reaction.
    distribution_window: int = 12
    #: The whole completed sequence expires after this many candles.
    setup_expiry_candles: int = 20


@dataclass
class Phase:
    name: str
    complete: bool
    start_index: int | None = None
    end_index: int | None = None
    start_timestamp: Any = None
    end_timestamp: Any = None
    detail: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AMDResult:
    status: str                  # ready | insufficient
    phase: str                   # unclear | accumulation | manipulation | reaction | distribution | delivered
    complete: bool
    direction: str | None        # BUY | SELL
    phases: list[Phase]
    range_high: float | None
    range_low: float | None
    invalidation: float | None
    expiry_index: int | None
    age_candles: int | None
    reasons: list[str]
    config: dict[str, Any]
    timeframe: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "phase": self.phase,
            "complete": self.complete,
            "direction": BULLISH if self.direction == "BUY" else BEARISH if self.direction == "SELL" else None,
            "trade_direction": self.direction,
            "phases": [phase.as_dict() for phase in self.phases],
            "phase_map": {phase.name: phase.complete for phase in self.phases},
            "range_high": self.range_high,
            "range_low": self.range_low,
            "range_width": (self.range_high - self.range_low) if (self.range_high and self.range_low) else None,
            "invalidation": self.invalidation,
            "expiry_index": self.expiry_index,
            "age_candles": self.age_candles,
            "reasons": list(self.reasons),
            "config": dict(self.config),
            "timeframe": self.timeframe,
            # Legacy compatibility keys used by older consumers.
            "accumulation": any(p.name == "ACCUMULATION" and p.complete for p in self.phases),
            "manipulation": any(p.name == "MANIPULATION" and p.complete for p in self.phases),
            "distribution": any(p.name == "DISTRIBUTION" and p.complete for p in self.phases),
            "displacement": any(p.name == "DISTRIBUTION" and p.complete for p in self.phases),
            "trade_filter": not self.complete,
        }


def _insufficient(required: int, available: int, config: AMDConfig, timeframe: str | None) -> AMDResult:
    return AMDResult(
        status="insufficient", phase="unclear", complete=False, direction=None,
        phases=[], range_high=None, range_low=None, invalidation=None,
        expiry_index=None, age_candles=None,
        reasons=[f"AMD requires at least {required} closed candles; {available} available."],
        config=asdict(config), timeframe=timeframe,
    )


def _accumulation_candidates(
    rows: list[dict[str, Any]], config: AMDConfig, limit: int = 60
) -> list[Phase]:
    """Yield compressed-range candidates, most recent first.

    The accumulation must leave room for the later phases, so a candidate can
    never extend into the last ``manipulation_window`` candles -- otherwise the
    range would simply swallow its own raid (the bug in the previous version).
    """
    candidates: list[Phase] = []
    minimum_forward_room = 2
    latest_end = len(rows) - minimum_forward_room
    horizon = (config.accumulation_max_candles + config.manipulation_window
               + config.reaction_window + config.distribution_window + 20)
    earliest_end = max(config.accumulation_min_candles, len(rows) - horizon)

    for end in range(latest_end, earliest_end - 1, -1):
        for length in range(config.accumulation_max_candles, config.accumulation_min_candles - 1, -1):
            start = end - length
            if start < 0:
                continue
            window = rows[start:end]
            if len(window) < config.accumulation_min_candles:
                continue
            highs = [_high(c) for c in window]
            lows = [_low(c) for c in window]
            width = max(highs) - min(lows)
            ranges = [h - l for h, l in zip(highs, lows) if h >= l]
            average_range = sum(ranges) / len(ranges) if ranges else 0.0
            if average_range <= 0 or width <= 0:
                continue
            if width > average_range * config.accumulation_compression_max:
                continue
            candidates.append(Phase(
                name="ACCUMULATION", complete=True,
                start_index=start, end_index=end - 1,
                start_timestamp=_time(window[0]), end_timestamp=_time(window[-1]),
                detail={"high": max(highs), "low": min(lows), "width": width,
                        "average_candle_range": average_range,
                        "compression_ratio": width / average_range, "candles": length},
                reason=f"{length}-candle compressed range (width {width:.6g} = "
                       f"{width / average_range:.1f}x average candle range).",
            ))
            break        # longest compressed window ending here is enough
        if len(candidates) >= limit:
            break
    return candidates


def detect_amd(
    candles: Sequence[dict[str, Any]],
    *,
    structure: StructureState | None = None,
    timeframe: str | None = None,
    config: AMDConfig | None = None,
) -> AMDResult:
    """Evaluate AMD as a strictly ordered sequence.

    Several accumulation ranges may be plausible; each is evaluated
    independently and the *most advanced* ordered sequence wins. A later
    candle can never retroactively complete an earlier phase, because every
    phase search is bounded by the previous phase's end index.
    """
    config = config or AMDConfig()
    rows = closed_candles(candles)
    required = config.accumulation_min_candles + config.manipulation_window + config.distribution_window
    if len(rows) < required:
        return _insufficient(required, len(rows), config, timeframe)

    candidates = _accumulation_candidates(rows, config)
    if not candidates:
        phase = Phase("ACCUMULATION", False, reason="No sufficiently compressed range was found.")
        return AMDResult("ready", "unclear", False, None, [phase], None, None, None, None, None,
                         [phase.reason], asdict(config), timeframe)

    best: AMDResult | None = None
    for accumulation in candidates:
        result = _evaluate_sequence(rows, accumulation, structure, config, timeframe)
        if best is None or _sequence_rank(result) > _sequence_rank(best):
            best = result
        if best.complete:
            break
    return best  # type: ignore[return-value]


_PHASE_ORDER = ("ACCUMULATION", "MANIPULATION", "REACTION", "DISTRIBUTION",
                "STRUCTURAL_DELIVERY", "RETRACEMENT_ENTRY")


def _sequence_rank(result: AMDResult) -> tuple[int, int, int]:
    completed = sum(1 for phase in result.phases if phase.complete)
    recency = max((phase.end_index or 0) for phase in result.phases) if result.phases else 0
    return (1 if result.complete else 0, completed, recency)


def _evaluate_sequence(
    rows: list[dict[str, Any]],
    accumulation: Phase,
    structure: StructureState | None,
    config: AMDConfig,
    timeframe: str | None,
) -> AMDResult:
    last_index = len(rows) - 1
    phases: list[Phase] = [accumulation]
    reasons: list[str] = []
    range_high = float(accumulation.detail["high"])
    range_low = float(accumulation.detail["low"])
    accumulation_end = int(accumulation.end_index or 0)


    # ---------------------------------------------------------------- phase 2
    manipulation = Phase("MANIPULATION", False, reason="No liquidity raid of the accumulation range.")
    raid_side = None
    for index in range(accumulation_end + 1, min(len(rows), accumulation_end + 1 + config.manipulation_window)):
        candle = rows[index]
        if _low(candle) < range_low:
            raid_side, raid_index = "sell_side", index
        elif _high(candle) > range_high:
            raid_side, raid_index = "buy_side", index
        else:
            continue
        manipulation = Phase(
            "MANIPULATION", True, start_index=index, end_index=index,
            start_timestamp=_time(candle), end_timestamp=_time(candle),
            detail={"side": raid_side,
                    "raided_level": range_low if raid_side == "sell_side" else range_high,
                    "extreme": _low(candle) if raid_side == "sell_side" else _high(candle)},
            reason=f"{raid_side} liquidity raid of the accumulation range at index {index}.",
        )
        break
    phases.append(manipulation)
    if not manipulation.complete:
        reasons.append(manipulation.reason)
        return AMDResult("ready", "accumulation", False, None, phases, range_high, range_low,
                         None, None, None, reasons, asdict(config), timeframe)
    raid_index = int(manipulation.end_index or 0)
    implied = "BUY" if raid_side == "sell_side" else "SELL"

    # ---------------------------------------------------------------- phase 3
    reaction = Phase("REACTION", False,
                     reason="Price did not close back inside the range after the raid.")
    for index in range(raid_index, min(len(rows), raid_index + 1 + config.reaction_window)):
        close = _close(rows[index])
        back_inside = (close > range_low) if raid_side == "sell_side" else (close < range_high)
        if back_inside:
            reaction = Phase(
                "REACTION", True, start_index=raid_index, end_index=index,
                start_timestamp=_time(rows[raid_index]), end_timestamp=_time(rows[index]),
                detail={"reclaim_price": close,
                        "reclaimed_level": range_low if raid_side == "sell_side" else range_high},
                reason=f"Price reclaimed the raided level with a closed candle at index {index}.",
            )
            break
    phases.append(reaction)
    if not reaction.complete:
        reasons.append(reaction.reason)
        return AMDResult("ready", "manipulation", False, implied, phases, range_high, range_low,
                         manipulation.detail.get("extreme"), None, last_index - raid_index,
                         reasons, asdict(config), timeframe)
    reaction_end = int(reaction.end_index or raid_index)

    # ---------------------------------------------------------------- phase 4
    wanted = BULLISH if implied == "BUY" else BEARISH
    distribution = Phase("DISTRIBUTION", False,
                         reason="No displacement candle in the raid direction after the reaction.")
    for index in range(reaction_end, min(len(rows), reaction_end + 1 + config.distribution_window)):
        disp = displacement_at(rows, index, lookback=20)
        if disp.get("displacement") and disp.get("direction") == wanted:
            distribution = Phase(
                "DISTRIBUTION", True, start_index=reaction_end, end_index=index,
                start_timestamp=_time(rows[reaction_end]), end_timestamp=_time(rows[index]),
                detail=disp,
                reason=f"Displacement candle at index {index} "
                       f"({disp.get('body_multiple') or 0:.1f}x average body) in the {wanted} direction.",
            )
            break
    phases.append(distribution)
    if not distribution.complete:
        reasons.append(distribution.reason)
        return AMDResult("ready", "reaction", False, implied, phases, range_high, range_low,
                         manipulation.detail.get("extreme"), None, last_index - raid_index,
                         reasons, asdict(config), timeframe)
    distribution_index = int(distribution.end_index or reaction_end)

    # ---------------------------------------------------------------- phase 5
    delivery = Phase("STRUCTURAL_DELIVERY", False,
                     reason="No closed-candle structure break confirmed the delivery.")
    if structure is not None:
        for event in reversed(structure.events):
            if event.direction == wanted and event.break_index >= raid_index:
                delivery = Phase(
                    "STRUCTURAL_DELIVERY", True, start_index=raid_index, end_index=event.break_index,
                    start_timestamp=_time(rows[raid_index]), end_timestamp=event.break_timestamp,
                    detail=event.as_dict(),
                    reason=f"{event.type} ({event.direction}) broke a protected swing at index {event.break_index}.",
                )
                break
    phases.append(delivery)

    # ---------------------------------------------------------------- phase 6
    expiry_index = distribution_index + config.setup_expiry_candles
    age = last_index - distribution_index
    entry = Phase("RETRACEMENT_ENTRY", False, reason="Awaiting a retracement into the delivery zone.")
    if last_index > expiry_index:
        entry = Phase("RETRACEMENT_ENTRY", False,
                      reason=f"Sequence expired: {age} candles since displacement (limit "
                             f"{config.setup_expiry_candles}).")
        reasons.append(entry.reason)
    else:
        displacement_candle = rows[distribution_index]
        zone_low = min(_open(displacement_candle), _close(displacement_candle))
        zone_high = max(_open(displacement_candle), _close(displacement_candle))
        current = _close(rows[-1])
        inside = zone_low <= current <= zone_high
        entry = Phase(
            "RETRACEMENT_ENTRY", inside,
            start_index=distribution_index, end_index=last_index,
            start_timestamp=_time(displacement_candle), end_timestamp=_time(rows[-1]),
            detail={"zone_low": zone_low, "zone_high": zone_high, "current_price": current},
            reason=("Price has retraced into the delivery zone."
                    if inside else "Price has not yet retraced into the delivery zone."),
        )
    phases.append(entry)

    complete = all(p.complete for p in phases if p.name != "RETRACEMENT_ENTRY") and delivery.complete
    phase_label = "delivered" if complete else "distribution"
    invalidation = manipulation.detail.get("extreme")
    if not complete:
        reasons.append(delivery.reason if not delivery.complete else entry.reason)

    return AMDResult(
        status="ready", phase=phase_label, complete=complete, direction=implied,
        phases=phases, range_high=range_high, range_low=range_low,
        invalidation=invalidation, expiry_index=expiry_index, age_candles=age,
        reasons=reasons or ["AMD sequence completed in order."],
        config=asdict(config), timeframe=timeframe,
    )
