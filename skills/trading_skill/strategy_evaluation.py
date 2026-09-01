"""The single authoritative strategy-evaluation and scoring framework.

Why this module exists
----------------------
The engine previously had **two** competing scores: hard-coded candidate scores
in ``strategy_engine`` (SMC=8, AMD=9, Trend=7 ...) and a separate 0-14/0-10
score in ``confluence``. The selector could pick AMD while confluence rated SMC
higher, so the decision hierarchy was incoherent.

There is now exactly one score. Every strategy produces a
:class:`StrategyEvaluation` through the same interface, and the selector ranks
strategies using that object and nothing else.

What the score means -- and does not mean
-----------------------------------------
``quality_score_0_100`` answers ONE question:

    "How completely does this setup satisfy *this strategy's own* evidence
     requirements?"

It is **not** a probability. 70 does not mean a 70% chance of winning. Two
strategies both scoring 80 are not equally likely to win; they are each 80%
complete against their own, different, evidence models. See
``docs/STRATEGY_SCORE_INTERPRETATION.md``.

Hard requirements vs soft evidence
----------------------------------
* A **hard requirement** is binary and gating. If any hard requirement fails,
  ``setup_complete`` is False and the setup is not executable -- regardless of
  how high the score is. A score can never buy its way past a hard failure.
* **Soft evidence** grades quality within an evidence *family*. Correlated
  signals belong to the same family and cannot each award full points, which
  removes the "more indicators agreed so I'm more confident" failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Iterable, Sequence

# Evidence kinds, as required by the audit.
HARD = "HARD_REQUIREMENT"
SOFT = "SOFT_EVIDENCE"
CONTEXT = "CONTEXT"
DERIVED = "DERIVED_VALUE"

#: Default minimum quality for an executable setup. Policy, not science.
DEFAULT_MINIMUM_QUALITY = 70


@dataclass(frozen=True)
class HardRequirement:
    """A binary, gating condition."""
    key: str
    label: str
    satisfied: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Evidence:
    """A graded observation inside an evidence family."""
    key: str
    family: str
    label: str
    #: 0.0 - 1.0 quality within this observation.
    score: float
    weight: float
    kind: str = SOFT
    detail: str = ""

    @property
    def points(self) -> float:
        return max(0.0, min(1.0, float(self.score))) * float(self.weight)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["points"] = self.points
        return data


@dataclass
class StrategyEvaluation:
    """The one object every strategy returns and the selector ranks."""

    strategy_name: str
    direction: str | None
    hard_requirements: list[HardRequirement] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    timeframe_context: dict[str, Any] = field(default_factory=dict)
    plan_context: dict[str, Any] = field(default_factory=dict)
    data_status: str = "ready"          # ready | insufficient | unavailable
    minimum_quality: int = DEFAULT_MINIMUM_QUALITY

    # -- derived ----------------------------------------------------------
    @property
    def passed_hard_requirements(self) -> list[str]:
        return [item.key for item in self.hard_requirements if item.satisfied]

    @property
    def failed_hard_requirements(self) -> list[str]:
        return [item.key for item in self.hard_requirements if not item.satisfied]

    @property
    def families(self) -> dict[str, dict[str, float]]:
        """Aggregate evidence per family.

        Within a family, correlated observations share the family's weight
        budget: the family score is the weighted *mean* of its observations,
        not their sum. This is what prevents double counting.
        """
        grouped: dict[str, list[Evidence]] = {}
        for item in self.evidence:
            grouped.setdefault(item.family, []).append(item)
        out: dict[str, dict[str, float]] = {}
        for family, items in grouped.items():
            weight = max(item.weight for item in items)
            total_weight = sum(item.weight for item in items) or 1.0
            score = sum(item.points for item in items) / total_weight
            out[family] = {
                "score": round(max(0.0, min(1.0, score)), 6),
                "weight": weight,
                "points": round(max(0.0, min(1.0, score)) * weight, 6),
                "observations": len(items),
            }
        return out

    @property
    def raw_points(self) -> float:
        return round(sum(row["points"] for row in self.families.values()), 6)

    @property
    def max_points(self) -> float:
        return round(sum(row["weight"] for row in self.families.values()), 6)

    @property
    def quality_score_0_100(self) -> int:
        if self.max_points <= 0:
            return 0
        return int(round(self.raw_points / self.max_points * 100))

    @property
    def setup_complete(self) -> bool:
        return (
            self.data_status == "ready"
            and self.direction in {"BUY", "SELL"}
            and not self.failed_hard_requirements
            and not self.blockers
            and self.quality_score_0_100 >= self.minimum_quality
        )

    @property
    def state(self) -> str:
        if self.data_status != "ready":
            return "BLOCKED_BY_DATA"
        if self.blockers:
            return "BLOCKED"
        if self.setup_complete:
            return "READY"
        return "WAIT"

    @property
    def confidence_label(self) -> str:
        """Descriptive band. Explicitly NOT a probability."""
        if not self.setup_complete:
            return "NOT_EXECUTABLE"
        score = self.quality_score_0_100
        if score >= 90:
            return "VERY_STRONG_SETUP_QUALITY"
        if score >= 80:
            return "STRONG_SETUP_QUALITY"
        if score >= self.minimum_quality:
            return "QUALIFIED_SETUP_QUALITY"
        return "BELOW_THRESHOLD"

    # -- helpers ----------------------------------------------------------
    def require(self, key: str, label: str, satisfied: bool, detail: str = "") -> "StrategyEvaluation":
        self.hard_requirements.append(HardRequirement(key, label, bool(satisfied), detail))
        return self

    def observe(self, key: str, family: str, label: str, score: float, weight: float,
                kind: str = SOFT, detail: str = "") -> "StrategyEvaluation":
        self.evidence.append(Evidence(key, family, label, float(score), float(weight), kind, detail))
        return self

    def note(self, message: str) -> "StrategyEvaluation":
        if message and message not in self.reasons:
            self.reasons.append(message)
        return self

    def block(self, message: str) -> "StrategyEvaluation":
        if message and message not in self.blockers:
            self.blockers.append(message)
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "direction": self.direction,
            "state": self.state,
            "data_status": self.data_status,
            "hard_requirements": [item.as_dict() for item in self.hard_requirements],
            "passed_hard_requirements": self.passed_hard_requirements,
            "failed_hard_requirements": self.failed_hard_requirements,
            "evidence": [item.as_dict() for item in self.evidence],
            "evidence_families": self.families,
            "raw_points": self.raw_points,
            "max_points": self.max_points,
            "quality_score_0_100": self.quality_score_0_100,
            "minimum_quality": self.minimum_quality,
            "setup_complete": self.setup_complete,
            "confidence_label": self.confidence_label,
            "score_meaning": (
                "Completeness of this strategy's own setup definition. "
                "This is NOT a win probability."
            ),
            "reasons": list(self.reasons),
            "blockers": list(self.blockers),
            "timeframe_context": dict(self.timeframe_context),
            "plan_context": dict(self.plan_context),
        }

    # -- legacy shape used by older UI/consumers ---------------------------
    def as_candidate(self) -> dict[str, Any]:
        plan = dict(self.plan_context)
        return {
            "name": self.strategy_name,
            "direction": self.direction,
            "state": self.state,
            "score": self.quality_score_0_100,
            "quality_score": self.quality_score_0_100,
            "required": tuple(item.key for item in self.hard_requirements),
            "missing": tuple(self.failed_hard_requirements),
            "reasons": tuple(self.reasons),
            "zone": plan.get("zone"),
            "target": plan.get("target"),
            "metadata": {"evaluation": self.as_dict(), **plan},
        }


def rank(evaluations: Sequence[StrategyEvaluation]) -> list[StrategyEvaluation]:
    """Rank strategies with a single, explainable ordering.

    Complete setups always outrank incomplete ones. Within each group the
    ordering is by quality score, then by the number of hard requirements the
    strategy actually enforces (a strategy that proves more is preferred at an
    equal score), then alphabetically for determinism.
    """
    return sorted(
        evaluations,
        key=lambda e: (
            1 if e.setup_complete else 0,
            e.quality_score_0_100,
            len(e.hard_requirements),
            e.strategy_name,
        ),
        reverse=True,
    )


def select(
    evaluations: Sequence[StrategyEvaluation],
    preferred: str = "AUTO",
) -> dict[str, Any]:
    """Choose one strategy using the single score engine."""
    candidates = list(evaluations)
    preferred = str(preferred or "AUTO").upper()
    filtered = [e for e in candidates if e.strategy_name == preferred] if preferred != "AUTO" else candidates
    pool = filtered or candidates
    ordered = rank(pool)
    best = ordered[0] if ordered else None
    return {
        "selected": best.as_candidate() if best else None,
        "selected_evaluation": best.as_dict() if best else None,
        "candidates": [e.as_candidate() for e in rank(candidates)],
        "evaluations": [e.as_dict() for e in rank(candidates)],
        "scoring_engine": "strategy_evaluation.StrategyEvaluation (single authoritative score)",
        "preferred": preferred,
        "regime": _regime(best),
    }


def _regime(best: StrategyEvaluation | None) -> str:
    if best is None:
        return "UNKNOWN"
    return {
        "TREND_FOLLOWING": "TRENDING",
        "MOMENTUM": "TRENDING",
        "BREAKOUT": "EXPANSION",
        "MEAN_REVERSION": "RANGE",
        "SMC": "STRUCTURAL",
        "AMD": "STRUCTURAL",
    }.get(best.strategy_name, "MIXED")
