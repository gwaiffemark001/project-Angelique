"""Confluence -- now a *view* of the single authoritative score, not a second score.

Historically this module computed an independent 0-10/0-14 score that could
disagree with the strategy selector. That dual-scoring architecture has been
removed. ``evaluate_confluence`` re-runs the selected strategy's own evidence
model and reports it in the legacy shape, so there is exactly one number.
"""

from __future__ import annotations

from typing import Any

from .strategies import EVALUATORS
from .strategy_evaluation import StrategyEvaluation, DEFAULT_MINIMUM_QUALITY


def _minimum(profile: Any) -> int:
    value = getattr(profile, "minimum_quality_score", None)
    if value:
        return int(value)
    legacy = getattr(profile, "minimum_score", None)
    # A legacy 0-10 style threshold is scaled onto the 0-100 quality scale.
    if legacy and int(legacy) <= 14:
        return int(round(float(legacy) / 10.0 * 100))
    return int(legacy or DEFAULT_MINIMUM_QUALITY)


def evaluate_confluence(
    direction: str,
    trends: dict[str, str],
    indicator_data: dict[str, dict[str, Any]],
    smc_data: dict[str, dict[str, Any]],
    profile=None,
    strategy_name: str = "SMC",
    *,
    session: dict[str, Any] | None = None,
    timeframes_data: dict[str, list[dict[str, Any]]] | None = None,
    evaluation: StrategyEvaluation | None = None,
) -> dict[str, Any]:
    """Return the selected strategy's quality score in the legacy response shape.

    The returned ``score`` is the SAME number the selector ranked on. It is a
    setup-quality score on a 0-100 scale, NOT a win probability.
    """
    strategy = str(strategy_name or "SMC").upper()
    if profile is None:
        from .profiles import get_trading_profile
        profile = get_trading_profile("DAY_TRADING")

    if evaluation is None:
        evaluator = EVALUATORS.get(strategy)
        if evaluator is None:
            return {
                "score": 0, "maximum_score": 100, "minimum_score": _minimum(profile),
                "ready": False, "strategy": strategy, "agree": [], "disagree": [],
                "summary": f"Unknown strategy '{strategy}'.",
                "score_meaning": "Setup completeness (0-100). Not a probability.",
                "supporting_evidence": {},
            }
        evaluation = evaluator(
            profile=profile, indicators=indicator_data or {}, trends=trends or {},
            smc=smc_data or {}, session=session or {}, timeframes_data=timeframes_data or {},
        )

    agree: list[str] = []
    disagree: list[str] = []
    for requirement in evaluation.hard_requirements:
        line = f"{requirement.label}: {requirement.detail}".strip().rstrip(":")
        (agree if requirement.satisfied else disagree).append(
            ("AGREES (hard requirement met): " if requirement.satisfied
             else "BLOCKS (hard requirement failed): ") + line
        )
    for item in evaluation.evidence:
        line = f"{item.label} [{item.family}] {item.detail}".strip()
        if item.score >= 0.75:
            agree.append(f"AGREES: {line}")
        elif item.score <= 0.25:
            disagree.append(f"DISAGREES: {line}")

    score = evaluation.quality_score_0_100
    minimum = evaluation.minimum_quality
    return {
        "score": score,
        "maximum_score": 100,
        "minimum_score": minimum,
        "ready": evaluation.setup_complete,
        "score_passed": score >= minimum,
        "strategy": evaluation.strategy_name,
        "direction": evaluation.direction,
        "state": evaluation.state,
        "confidence_label": evaluation.confidence_label,
        "score_meaning": (
            "Completeness of this strategy's own setup definition on a 0-100 scale. "
            "This is NOT a win probability and is not comparable across strategies "
            "as if it were one."
        ),
        "hard_requirements": [item.as_dict() for item in evaluation.hard_requirements],
        "failed_hard_requirements": evaluation.failed_hard_requirements,
        "evidence_families": evaluation.families,
        "agree": agree,
        "disagree": disagree,
        "summary": (
            f"{evaluation.strategy_name} setup quality {score}/100 "
            f"({evaluation.confidence_label}); "
            f"{len(evaluation.passed_hard_requirements)}/{len(evaluation.hard_requirements)} "
            f"hard requirements met."
        ),
        "supporting_evidence": {
            "setup_timeframe": evaluation.timeframe_context.get("setup"),
            "entry_timeframe": evaluation.timeframe_context.get("entry"),
            "timeframes": evaluation.timeframe_context,
            "plan_context": evaluation.plan_context,
        },
        "evaluation": evaluation.as_dict(),
    }
