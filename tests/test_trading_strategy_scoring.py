"""Single-score architecture: hard requirements, evidence weighting, selection."""

import pytest

from skills.trading_skill.profiles import get_trading_profile
from skills.trading_skill.strategies import EVALUATORS, STRATEGY_NAMES, evaluate_all
from skills.trading_skill.strategy_engine import select_strategy
from skills.trading_skill.strategy_evaluation import (
    DEFAULT_MINIMUM_QUALITY, StrategyEvaluation, rank, select,
)


def _evaluation(name="TEST", direction="BUY", minimum=DEFAULT_MINIMUM_QUALITY):
    return StrategyEvaluation(strategy_name=name, direction=direction, minimum_quality=minimum)


# --------------------------------------------------------------------------
# Hard requirements can never be out-scored
# --------------------------------------------------------------------------
def test_a_perfect_score_cannot_override_a_failed_hard_requirement():
    evaluation = _evaluation()
    evaluation.require("structure", "Protected-swing break", False, "no break")
    for index in range(5):
        evaluation.observe(f"e{index}", f"family{index}", "perfect evidence", 1.0, 20)
    assert evaluation.quality_score_0_100 == 100
    assert evaluation.setup_complete is False
    assert evaluation.state == "WAIT"
    assert "structure" in evaluation.failed_hard_requirements
    assert evaluation.confidence_label == "NOT_EXECUTABLE"


def test_all_hard_requirements_met_but_low_score_is_still_not_executable():
    evaluation = _evaluation()
    evaluation.require("structure", "Protected-swing break", True)
    evaluation.observe("weak", "family", "weak evidence", 0.1, 100)
    assert not evaluation.failed_hard_requirements
    assert evaluation.quality_score_0_100 < evaluation.minimum_quality
    assert evaluation.setup_complete is False


def test_setup_complete_requires_both_gates():
    evaluation = _evaluation()
    evaluation.require("structure", "Protected-swing break", True)
    evaluation.observe("strong", "family", "strong evidence", 1.0, 100)
    assert evaluation.setup_complete is True
    assert evaluation.state == "READY"


def test_a_blocker_prevents_completion_regardless_of_score():
    evaluation = _evaluation()
    evaluation.require("structure", "ok", True)
    evaluation.observe("strong", "family", "strong", 1.0, 100)
    evaluation.block("Broker metadata incomplete.")
    assert evaluation.setup_complete is False
    assert evaluation.state == "BLOCKED"


def test_missing_direction_is_never_executable():
    evaluation = _evaluation(direction=None)
    evaluation.observe("strong", "family", "strong", 1.0, 100)
    assert evaluation.setup_complete is False


# --------------------------------------------------------------------------
# Evidence families prevent double counting
# --------------------------------------------------------------------------
def test_correlated_evidence_in_one_family_cannot_award_more_than_the_family_weight():
    single = _evaluation()
    single.observe("a", "momentum", "RSI", 1.0, 30)

    stacked = _evaluation()
    for key in ("a", "b", "c", "d"):
        stacked.observe(key, "momentum", "correlated momentum signal", 1.0, 30)

    assert single.max_points == stacked.max_points == 30
    assert single.quality_score_0_100 == stacked.quality_score_0_100 == 100


def test_partial_family_agreement_scores_between_zero_and_full():
    evaluation = _evaluation()
    evaluation.observe("a", "momentum", "agrees", 1.0, 30)
    evaluation.observe("b", "momentum", "disagrees", 0.0, 30)
    assert evaluation.families["momentum"]["score"] == pytest.approx(0.5)
    assert evaluation.quality_score_0_100 == 50


def test_independent_families_each_contribute_their_own_weight():
    evaluation = _evaluation()
    evaluation.observe("a", "structure", "structure", 1.0, 50)
    evaluation.observe("b", "location", "location", 0.0, 50)
    assert evaluation.max_points == 100
    assert evaluation.quality_score_0_100 == 50


def test_score_is_zero_when_no_evidence_exists():
    assert _evaluation().quality_score_0_100 == 0


# --------------------------------------------------------------------------
# The score is not a probability
# --------------------------------------------------------------------------
def test_score_is_explicitly_not_a_probability():
    evaluation = _evaluation()
    evaluation.require("x", "x", True)
    evaluation.observe("a", "f", "a", 1.0, 100)
    data = evaluation.as_dict()
    assert "NOT a win probability" in data["score_meaning"]
    assert "probability" not in data["confidence_label"].lower()
    assert data["quality_score_0_100"] == 100
    # No key anywhere may imply a win rate.
    assert not any("win" in key.lower() or "probab" in key.lower() for key in data)


# --------------------------------------------------------------------------
# Ranking / selection
# --------------------------------------------------------------------------
def test_complete_setups_always_outrank_incomplete_higher_scoring_ones():
    complete = _evaluation("COMPLETE")
    complete.require("x", "x", True)
    complete.observe("a", "f", "a", 0.75, 100)

    incomplete = _evaluation("INCOMPLETE")
    incomplete.require("x", "x", False)
    incomplete.observe("a", "f", "a", 1.0, 100)

    assert incomplete.quality_score_0_100 > complete.quality_score_0_100
    assert rank([incomplete, complete])[0].strategy_name == "COMPLETE"


def test_selection_is_deterministic_for_equal_scores():
    first = _evaluation("AAA")
    second = _evaluation("BBB")
    for evaluation in (first, second):
        evaluation.observe("a", "f", "a", 0.5, 100)
    assert rank([second, first])[0].strategy_name == rank([first, second])[0].strategy_name


def test_preferred_strategy_is_honoured():
    a, b = _evaluation("SMC"), _evaluation("MOMENTUM")
    a.observe("x", "f", "x", 0.2, 100)
    b.observe("x", "f", "x", 0.9, 100)
    result = select([a, b], preferred="SMC")
    assert result["selected"]["name"] == "SMC"
    # Every strategy is still reported, so the choice is auditable.
    assert {c["name"] for c in result["candidates"]} == {"SMC", "MOMENTUM"}


# --------------------------------------------------------------------------
# One scoring engine only
# --------------------------------------------------------------------------
def test_confluence_reports_the_same_score_the_selector_ranked():
    from skills.trading_skill.confluence import evaluate_confluence

    profile = get_trading_profile("DAY_TRADING")
    evaluation = _evaluation("SMC", minimum=profile.minimum_quality_score)
    evaluation.require("x", "x", True)
    evaluation.observe("a", "f", "a", 0.8, 100)
    view = evaluate_confluence("BUY", {}, {}, {}, profile=profile,
                               strategy_name="SMC", evaluation=evaluation)
    assert view["score"] == evaluation.quality_score_0_100
    assert view["maximum_score"] == 100
    assert view["ready"] == evaluation.setup_complete
    assert "NOT a win probability" in view["score_meaning"]


def test_no_hard_coded_candidate_scores_remain():
    """The selector must not assign a strategy a score before evaluating it."""
    import inspect

    from skills.trading_skill import strategy_engine

    source = inspect.getsource(strategy_engine)
    for legacy in ('"score": 8', '"score": 9', "score=8", "score=9", "score=7"):
        assert legacy not in source


# --------------------------------------------------------------------------
# Profile-driven timeframes
# --------------------------------------------------------------------------
def test_strategies_use_profile_timeframes_not_hard_coded_ones():
    day = get_trading_profile("DAY_TRADING")
    swing = get_trading_profile("SWING_TRADING")
    day_result = select_strategy(profile=day, indicators={}, trends={}, smc={}, timeframes={})
    swing_result = select_strategy(profile=swing, indicators={}, trends={}, smc={}, timeframes={})

    day_tfs = day_result["evaluations"][0]["timeframe_context"]
    swing_tfs = swing_result["evaluations"][0]["timeframe_context"]
    assert day_tfs["setup"] == day.setup_timeframe
    assert swing_tfs["setup"] == swing.setup_timeframe
    assert day_tfs != swing_tfs


def test_every_strategy_is_evaluated_through_one_interface():
    assert set(EVALUATORS) == set(STRATEGY_NAMES)
    results = evaluate_all(profile=get_trading_profile("DAY_TRADING"),
                           indicators={}, trends={}, smc={}, session={}, timeframes_data={})
    assert len(results) == len(STRATEGY_NAMES)
    assert all(isinstance(r, StrategyEvaluation) for r in results)
    # With no data at all, nothing may be reported as ready.
    assert not any(r.setup_complete for r in results)


def test_a_broken_strategy_does_not_kill_the_whole_evaluation(monkeypatch):
    def explode(**_):
        raise RuntimeError("boom")

    monkeypatch.setitem(EVALUATORS, "MOMENTUM", explode)
    results = evaluate_all(profile=get_trading_profile("DAY_TRADING"),
                           indicators={}, trends={}, smc={}, session={}, timeframes_data={})
    momentum = next(r for r in results if r.strategy_name == "MOMENTUM")
    assert momentum.state.startswith("BLOCKED")
    assert not momentum.setup_complete
    assert any("boom" in blocker for blocker in momentum.blockers)
    assert len(results) == len(STRATEGY_NAMES)


# --------------------------------------------------------------------------
# Momentum readiness bug (P0)
# --------------------------------------------------------------------------
def _momentum_indicators(rsi_value, histogram, macd_value=0.001, signal=0.0005):
    return {
        "M15": {
            "rsi_14": rsi_value, "macd": macd_value, "macd_signal": signal,
            "macd_histogram": histogram, "macd_histogram_slope": 0.0001,
            "macd_zero_line": "ABOVE", "last_close": 1.1,
            "readiness": {"rsi_14": True, "macd": True, "macd_signal": True,
                          "macd_histogram": True},
        }
    }


def test_momentum_requires_rsi_and_htf_not_just_macd():
    profile = get_trading_profile("DAY_TRADING")
    # MACD is bullish and the entry timeframe agrees, but RSI is on the wrong
    # side and the higher timeframe disagrees. This previously reported READY.
    evaluation = EVALUATORS["MOMENTUM"](
        profile=profile, indicators=_momentum_indicators(41.0, 0.0002),
        trends={"H1": "bearish", "M5": "bullish", "M15": "bullish"},
    )
    assert evaluation.direction == "BUY"
    assert not evaluation.setup_complete
    assert "rsi_quality" in evaluation.failed_hard_requirements
    assert "htf_context" in evaluation.failed_hard_requirements


def test_momentum_rejects_exhausted_rsi():
    evaluation = EVALUATORS["MOMENTUM"](
        profile=get_trading_profile("DAY_TRADING"),
        indicators=_momentum_indicators(88.0, 0.0002),
        trends={"H1": "bullish", "M5": "bullish", "M15": "bullish"},
    )
    assert "rsi_not_exhausted" in evaluation.failed_hard_requirements


def test_momentum_is_ready_when_every_hard_requirement_is_met():
    evaluation = EVALUATORS["MOMENTUM"](
        profile=get_trading_profile("DAY_TRADING"),
        indicators=_momentum_indicators(66.0, 0.0004),
        trends={"H1": "bullish", "M5": "bullish", "M15": "bullish"},
    )
    assert not evaluation.failed_hard_requirements
    assert evaluation.direction == "BUY"


# --------------------------------------------------------------------------
# Mean reversion must not fire inside a trend
# --------------------------------------------------------------------------
def test_mean_reversion_is_blocked_in_a_trending_regime():
    indicators = {
        "M15": {
            "bollinger_upper": 1.1050, "bollinger_lower": 1.0950, "bollinger_middle": 1.1000,
            "bollinger_percent_b": -0.1, "rsi_14": 22.0, "adx_14": 38.0, "atr_14": 0.0010,
            "last_close": 1.0955,
            "readiness": {"bollinger_upper": True, "bollinger_lower": True,
                          "bollinger_middle": True, "rsi_14": True, "adx_14": True,
                          "atr_14": True},
        }
    }
    candles = [{"time": i, "open": 1.096, "high": 1.0965, "low": 1.0940, "close": 1.0945,
                "closed": True} for i in range(30)]
    evaluation = EVALUATORS["MEAN_REVERSION"](
        profile=get_trading_profile("DAY_TRADING"), indicators=indicators,
        trends={"H1": "bearish", "M5": "bearish"},
        timeframes_data={"M15": candles},
    )
    assert "range_regime" in evaluation.failed_hard_requirements
    assert not evaluation.setup_complete
