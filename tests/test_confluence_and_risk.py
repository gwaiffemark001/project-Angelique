from skills.trading_skill.confluence import evaluate_confluence
from skills.trading_skill.profiles import DAY_PROFILE
from skills.trading_skill.safety import validate_trade_setup


def test_smc_confluence_max_is_one_hundred():
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
    entry = {"structure": {"bias": "bullish"}}
    result = evaluate_confluence("BUY", {"D1": "bullish", "H4": "bullish", "H1": "bullish", "M15": "bullish", "M5": "bullish"}, {}, {"M15": setup, "M5": entry}, profile=DAY_PROFILE, strategy_name="SMC")
    assert result["maximum_score"] == 100
    assert result["score"] == 100
    assert result["ready"]


def test_countertrend_requires_perfect_score():
    result = evaluate_confluence("BUY", {"D1": "bearish", "H4": "bullish", "H1": "bullish"}, {}, {}, profile=DAY_PROFILE, strategy_name="SMC")
    assert result["htf_alignment"]["countertrend"]
    assert not result["htf_alignment"]["countertrend_allowed"]


def test_half_risk_only_allowed_for_countertrend():
    kwargs = dict(symbol="EURUSD", direction="BUY", entry=1.1000, stop_loss=1.0990, take_profit=1.1030, risk_amount=5, volume=0.1, margin_required=10, free_margin_after=990, minimum_free_margin=0, projected_margin_level=1000, spread_pips=1.0, minimum_rr=2.5, maximum_spread_pips=1.5)
    assert validate_trade_setup(risk_percent=0.5, countertrend=True, **kwargs)["valid"]
    assert not validate_trade_setup(risk_percent=0.5, countertrend=False, **kwargs)["valid"]


def test_countertrend_build_risk_uses_half_risk_budget():
    from skills.trading_skill.risk import build_risk
    spec = {"tick_size": 0.00001, "tick_value": 1.0, "volume_step": 0.01, "volume_min": 0.01, "volume_max": 10.0, "margin_per_volume": 1.0}
    risk = build_risk(1.1000, 1.0990, 1000.0, 0.5, spec, free_margin=1000.0, countertrend=True)
    assert abs(risk["risk_amount"] - 5.0) < 1e-9


def test_countertrend_build_risk_rejects_half_risk_without_gate():
    from skills.trading_skill.risk import build_risk
    spec = {"tick_size": 0.00001, "tick_value": 1.0, "volume_step": 0.01, "volume_min": 0.01, "volume_max": 10.0, "margin_per_volume": 1.0}
    try:
        build_risk(1.1000, 1.0990, 1000.0, 0.5, spec, free_margin=1000.0, countertrend=False)
    except ValueError as exc:
        assert "Risk policy" in str(exc)
    else:
        raise AssertionError("Half-risk must require the explicit countertrend gate")
