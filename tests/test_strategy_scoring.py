from skills.trading_skill.confluence import evaluate_confluence, strategy_score_config
from skills.trading_skill.profiles import DAY_PROFILE


def test_strategy_score_scale_is_normalized():
    for name in ("SMC", "AMD", "TREND_FOLLOWING", "MOMENTUM", "BREAKOUT", "MEAN_REVERSION"):
        cfg = strategy_score_config(name)
        assert cfg["minimum"] == 70
        assert cfg["countertrend"] == 100


def test_smc_score_is_100_when_all_weighted_evidence_is_present():
    ict = {
        "ote": {"in_bullish_ote": True, "in_bearish_ote": False},
        "kill_zone": {"status": "ACTIVE", "name": "London Open"},
        "amd": {"complete": True, "phase": "distribution", "manipulation": True},
    }
    setup = {
        "liquidity_sweep": "sell_side_liquidity_sweep",
        "structure_shift": "bullish_BOS",
        "displacement": True,
        "location": "discount",
        "order_block": {"type": "bullish", "score": 5, "status": "UNMITIGATED", "price_in_zone": True},
        "ict": ict,
        "structure": {"bias": "bullish"},
        "fair_value_gaps": [],
    }
    entry = {"structure": {"bias": "bullish"}, "displacement": True}
    result = evaluate_confluence("BUY", {"D1": "bullish", "H4": "bullish", "H1": "bullish", "M15": "bullish", "M5": "bullish"}, {}, {"M15": setup, "M5": entry}, profile=DAY_PROFILE, strategy_name="SMC")
    assert result["score"] == 100
    assert result["maximum_score"] == 100
    assert result["score_passed"]
    assert result["ready"]


def test_missing_hard_requirement_cannot_pass_even_with_high_quality_score():
    setup = {
        "liquidity_sweep": "sell_side_liquidity_sweep",
        "structure_shift": "bullish_BOS",
        "displacement": True,
        "location": "discount",
        "order_block": {"type": "bullish", "score": 5, "status": "UNMITIGATED", "price_in_zone": True},
        "ict": {"ote": {"in_bullish_ote": True}, "kill_zone": {"status": "ACTIVE"}, "amd": {"complete": True, "manipulation": True}},
    }
    result = evaluate_confluence("BUY", {"D1": "bullish", "H4": "bullish", "H1": "bullish", "M15": "bullish", "M5": "bearish"}, {}, {"M15": setup, "M5": {"structure": {"bias": "bearish"}}}, profile=DAY_PROFILE, strategy_name="SMC")
    assert result["score"] < 100
    assert not result["ready"]
    assert "entry_confirmation" in result["hard_failures"]
