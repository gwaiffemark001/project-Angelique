"""Strategy selection -- a thin, explainable wrapper over the single score engine.

This module used to hold a *second* scoring system with hard-coded candidate
scores (SMC=8, AMD=9, TREND=7, ...) that competed with ``confluence``. Those
numbers are gone. Selection now compares strategies purely on the
:class:`~skills.trading_skill.strategy_evaluation.StrategyEvaluation` objects
produced by ``strategies.evaluate_all``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .strategies import evaluate_all, STRATEGY_NAMES
from .strategy_evaluation import StrategyEvaluation, rank, select


@dataclass(frozen=True)
class StrategyCandidate:
    """Legacy view of a :class:`StrategyEvaluation` (kept for existing consumers)."""
    name: str
    direction: str | None
    state: str
    score: float
    required: tuple[str, ...]
    missing: tuple[str, ...]
    reasons: tuple[str, ...]
    zone: dict[str, float] | None = None
    target: float | None = None
    metadata: dict[str, Any] | None = None

    @classmethod
    def from_evaluation(cls, evaluation: StrategyEvaluation) -> "StrategyCandidate":
        data = evaluation.as_candidate()
        return cls(
            name=data["name"], direction=data["direction"], state=data["state"],
            score=data["score"], required=data["required"], missing=data["missing"],
            reasons=data["reasons"], zone=data["zone"], target=data["target"],
            metadata=data["metadata"],
        )


def select_strategy(
    *,
    timeframes: dict[str, list[dict[str, Any]]] | None = None,
    indicators: dict[str, dict[str, Any]] | None = None,
    trends: dict[str, str] | None = None,
    structure: dict[str, Any] | None = None,
    smc: dict[str, dict[str, Any]] | None = None,
    session: dict[str, Any] | None = None,
    profile: Any = None,
    preferred: str = "AUTO",
    **_legacy: Any,
) -> dict[str, Any]:
    """Evaluate every strategy with one engine and return the ranked result.

    ``profile`` is required: every strategy derives its timeframes from the
    :class:`TradingProfile`, so DAY and SWING genuinely evaluate different data.
    """
    if profile is None:
        from .profiles import get_trading_profile
        profile = get_trading_profile("DAY_TRADING")

    smc_data = smc if smc is not None else ((structure or {}).get("smc") or {})
    evaluations = evaluate_all(
        profile=profile,
        indicators=indicators or {},
        trends=trends or {},
        smc=smc_data,
        session=session or {},
        timeframes_data=timeframes or {},
        structure=structure,
    )
    result = select(evaluations, preferred=preferred)
    result["strategies_evaluated"] = list(STRATEGY_NAMES)
    return result


__all__ = ["select_strategy", "StrategyCandidate", "rank"]
