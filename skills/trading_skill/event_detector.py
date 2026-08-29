from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any


@dataclass
class MarketEvent:
    symbol: str
    timeframe: str
    event: str
    candle_time: Any
    price: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MarketEventDetector:
    """Small in-memory event bus for candle changes and setup progression.

    It does not create trades. It gives the strategy a persistent place to record
    what changed so a setup can develop over several polling cycles.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._last_candle: dict[tuple[str, str], Any] = {}
        self._last_signature: dict[tuple[str, str], tuple[Any, ...]] = {}
        self._events: list[MarketEvent] = []
        self._max_events = 500

    @staticmethod
    def _signature(candle: dict[str, Any]) -> tuple[Any, ...]:
        return (
            candle.get("time"),
            candle.get("open"),
            candle.get("high"),
            candle.get("low"),
            candle.get("close"),
            candle.get("tick_volume"),
        )

    def update(self, symbol: str, timeframe: str, candles: list[dict[str, Any]]) -> list[MarketEvent]:
        if not candles:
            return []
        key = (str(symbol), str(timeframe).upper())
        candle = candles[-1]
        signature = self._signature(candle)
        events: list[MarketEvent] = []
        with self._lock:
            previous_time = self._last_candle.get(key)
            previous_signature = self._last_signature.get(key)
            if previous_time is None:
                event_name = "INITIALIZED"
            elif candle.get("time") != previous_time:
                event_name = "NEW_CANDLE"
            elif signature != previous_signature:
                event_name = "CANDLE_UPDATED"
            else:
                event_name = None
            if event_name:
                event = MarketEvent(
                    symbol=str(symbol),
                    timeframe=str(timeframe).upper(),
                    event=event_name,
                    candle_time=candle.get("time"),
                    price=float(candle.get("close", 0) or 0) or None,
                )
                self._events.append(event)
                self._events = self._events[-self._max_events:]
                events.append(event)
            self._last_candle[key] = candle.get("time")
            self._last_signature[key] = signature
        return events

    def record_setup_state(self, symbol: str, timeframe: str, assessment: dict[str, Any]) -> MarketEvent:
        stages = assessment.get("stages", {}) if isinstance(assessment, dict) else {}
        complete = bool(assessment.get("complete")) if isinstance(assessment, dict) else False
        missing = list(assessment.get("missing", [])) if isinstance(assessment, dict) else []
        event = MarketEvent(
            symbol=str(symbol),
            timeframe=str(timeframe).upper(),
            event="SETUP_COMPLETE" if complete else "SETUP_FORMING",
            candle_time=None,
            price=None,
            details={
                "model": assessment.get("model") if isinstance(assessment, dict) else None,
                "stages": stages,
                "missing": missing,
                "next_stage": missing[0] if missing else None,
            },
        )
        with self._lock:
            self._events.append(event)
            self._events = self._events[-self._max_events:]
        return event

    def recent(self, symbol: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            events = self._events[-max(1, int(limit)):]
        if symbol:
            events = [e for e in events if e.symbol.upper() == str(symbol).upper()]
        return [
            {
                "symbol": e.symbol,
                "timeframe": e.timeframe,
                "event": e.event,
                "candle_time": e.candle_time,
                "price": e.price,
                "details": e.details,
                "detected_at": e.detected_at,
            }
            for e in events
        ]


market_events = MarketEventDetector()
