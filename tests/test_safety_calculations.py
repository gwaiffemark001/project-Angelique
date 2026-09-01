from skills.trading_skill.risk import build_risk
from skills.trading_skill.safety import validate_trade_setup


def specs():
    return {"tick_size":0.00001,"tick_value":1.0,"volume_step":0.01,"volume_min":0.01,"volume_max":10.0,"margin_per_volume":100.0}


def test_volume_never_exceeds_risk_budget():
    result=build_risk(1.10000,1.09900,1000,1.0,specs(),free_margin=5000,used_margin=100,minimum_free_margin=100)
    assert result["actual_risk_amount"] <= result["risk_amount"] + 1e-9


def test_directional_tp_and_rr_are_enforced():
    ok=validate_trade_setup(symbol="EURUSD",direction="BUY",entry=1.1000,stop_loss=1.0980,take_profit=1.1060,risk_amount=20,risk_percent=1,volume=0.1,margin_required=100,free_margin_after=900,minimum_free_margin=100,projected_margin_level=1000,minimum_rr=2.5,spread_pips=0.8,maximum_spread_pips=3)
    assert ok["valid"]
    bad=validate_trade_setup(symbol="EURUSD",direction="BUY",entry=1.1000,stop_loss=1.0980,take_profit=1.0990,risk_amount=20,risk_percent=1,volume=0.1,margin_required=100,free_margin_after=900,minimum_free_margin=100,projected_margin_level=1000,minimum_rr=2.5,spread_pips=0.8,maximum_spread_pips=3)
    assert not bad["valid"]


def test_spread_gate_is_authoritative_and_overrides_legacy_profile_ceiling():
    # The instrument-aware gate (live Bid/Ask, observed distribution, relative
    # spread-to-stop/reward) is the source of truth. A rejected gate must block
    # even when the legacy profile pip ceiling would have passed.
    gate = {
        "allowed": False,
        "reasons": ["Spread is 30% of the stop distance (limit 15%)."],
        "checks": [],
        "measurement": {"spread_pips": 0.8, "spread_points": 8.0, "spread_percent_of_price": 0.01},
        "policy": {}, "stats": None,
    }
    result = validate_trade_setup(
        symbol="EURUSD", direction="BUY", entry=1.1000, stop_loss=1.0980,
        take_profit=1.1060, risk_amount=20, risk_percent=1, volume=0.1,
        margin_required=100, free_margin_after=900, minimum_free_margin=100,
        projected_margin_level=1000, minimum_rr=2.5, spread_pips=0.8,
        maximum_spread_pips=3, specs=specs(), net_rr=3.0, spread_gate=gate,
    )
    assert not result["valid"]
    assert any("30%" in reason for reason in result["reasons"])
    assert result["spread_gate"]["allowed"] is False


def test_sell_stop_direction_is_correct():
    result=validate_trade_setup(symbol="EURUSD",direction="SELL",entry=1.1000,stop_loss=1.1020,take_profit=1.0940,risk_amount=20,risk_percent=1,volume=0.1,margin_required=100,free_margin_after=900,minimum_free_margin=100,projected_margin_level=1000,minimum_rr=2.5,spread_pips=0.8,maximum_spread_pips=3)
    assert result["valid"]
