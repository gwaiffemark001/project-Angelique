from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .indicators import snapshot
from .evidence import detect_amd_phase as detect_amd_evidence, detect_candle_pattern, detect_ifvg, detect_wave_context
from .fvg_engine import detect_fvg_playbook
from .smc import ZoneRegistry, detect_smc

# Import ICT core concepts
try:
    from skills.trading.ict_core import (
        analyze_premium_discount,
        identify_ote_zone,
        get_kill_zone_status,
        calculate_ote,
    )
    ICT_AVAILABLE = True
except ImportError:
    ICT_AVAILABLE = False


def _ict_snapshot(candles: list[dict[str, Any]]) -> dict[str, Any]:
    if not ICT_AVAILABLE or len(candles) < 20:
        return {"status": "unavailable"}
    try:
        import pandas as pd
        df = pd.DataFrame(candles)
        needed = {"high", "low", "close", "open"}
        if not needed.issubset(df.columns):
            return {"status": "invalid_data"}
        # Ensure numeric columns are usable before passing them to ICT helpers.
        for name in needed:
            df[name] = pd.to_numeric(df[name], errors="coerce")
        df = df.dropna(subset=list(needed))
        if len(df) < 20:
            return {"status": "insufficient_data"}
        ote = identify_ote_zone(df, lookback=min(50, len(df)))
        pd_zone = analyze_premium_discount(df, lookback=min(50, len(df)))
        now = datetime.now(timezone.utc)
        amd_cycle = detect_amd_phase(df, now)
        kill_status, kill_zone = get_kill_zone_status(now)
        latest = df.iloc[-1]
        return {
            "status": "ready",
            "ote": ote or {},
            "premium_discount": pd_zone or {},
            "amd": {"phase": amd_cycle.current_phase.value, "complete": amd_cycle.is_complete, "accumulation_low": amd_cycle.accumulation_low, "accumulation_high": amd_cycle.accumulation_high, "manipulation_low": amd_cycle.manipulation_low, "manipulation_high": amd_cycle.manipulation_high},
            "kill_zone": {"status": kill_status, "name": kill_zone, "timestamp": now.isoformat()},
            "current_price": float(latest["close"]),
        }
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def _trend(candles: list[dict[str, Any]]) -> str:
    """Use structure first; fall back to a smoothed price slope.

    A single last-candle comparison was too noisy and could label a whole
    timeframe bullish/bearish from a tiny move.
    """
    if len(candles) < 9:
        return "unknown"
    try:
        from .smc import _structure
        bias = _structure(candles[-200:]).get("bias")
        if bias in {"bullish", "bearish"}:
            return bias
    except Exception:
        pass
    closes = [float(c.get("close", 0) or 0) for c in candles if float(c.get("close", 0) or 0) > 0]
    if len(closes) < 20:
        return "unknown"
    fast = sum(closes[-10:]) / 10
    slow = sum(closes[-20:]) / 20
    if fast > slow and closes[-1] > closes[-5]:
        return "bullish"
    if fast < slow and closes[-1] < closes[-5]:
        return "bearish"
    return "sideways"


@dataclass(frozen=True)
class MarketContext:
    trends: dict[str, str]
    indicators: dict[str, dict[str, Any]]
    smc: dict[str, dict[str, Any]]
    ict: dict[str, Any] = field(default_factory=dict)
    direction: str | None = None
    confluence: dict[str, Any] = field(default_factory=dict)


def build_market_context(timeframes: dict[str, list[dict[str, Any]]], windows: dict[str, dict[str, int]] | None = None, registry: ZoneRegistry | None = None) -> MarketContext:
    windows = windows or {}
    trend_candles = {
        timeframe: candles[-windows.get(timeframe, {}).get("trend", len(candles)):]
        for timeframe, candles in timeframes.items()
    }
    smc_candles = {
        timeframe: candles[-windows.get(timeframe, {}).get("smc_liquidity", len(candles)):]
        for timeframe, candles in timeframes.items()
    }
    trends = {timeframe: _trend(candles) for timeframe, candles in trend_candles.items()}
    indicator_data = {timeframe: snapshot(candles) for timeframe, candles in timeframes.items()}
    smc_data = {}
    for timeframe, candles in smc_candles.items():
        evidence = detect_smc(candles, timeframe=timeframe, registry=registry)
        evidence.update({
            "ifvg": detect_ifvg(candles, evidence.get("fair_value_gaps", [])),
            "fvg_playbook": detect_fvg_playbook(candles),
            "amd": detect_amd_evidence(candles),
            "ict": _ict_snapshot(candles),
            "candle_pattern": detect_candle_pattern(candles),
            "wave_context": detect_wave_context(candles),
        })
        smc_data[timeframe] = evidence
    return MarketContext(trends=trends, indicators=indicator_data, smc=smc_data, ict={tf: data.get("ict", {}) for tf, data in smc_data.items()})
