import pytest
from skills.trading_skill.safety import validate_trade_setup
from skills.trading_skill.models import MarketSnapshot


def test_validate_uses_spread_pips():
    # When spread_pips provided and TRADING_MAX_SPREAD default 3.0, check behavior
    result = validate_trade_setup(
        direction="BUY",
        entry=1.15500,
        stop_loss=1.15400,
        take_profit=1.15700,
        risk_amount=10.0,
        risk_percent=1.0,
        volume=0.01,
        margin_required=1.0,
        free_margin_after=1000.0,
        minimum_free_margin=100.0,
        current_margin_level=100.0,
        spread=None,
        spread_pips=2.5,
        minimum_rr=2.0,
    )
    assert result["valid"] is True
    assert any("Spread OK" in c for c in result["checks"]) 


def test_rejects_spread_above_config():
    result = validate_trade_setup(
        direction="BUY",
        entry=1.15500,
        stop_loss=1.15400,
        take_profit=1.15700,
        risk_amount=10.0,
        risk_percent=1.0,
        volume=0.01,
        margin_required=1.0,
        free_margin_after=1000.0,
        minimum_free_margin=100.0,
        current_margin_level=100.0,
        spread=None,
        spread_pips=5.0,
        minimum_rr=2.0,
    )
    assert result["valid"] is False
    assert any("Spread is too wide" in r for r in result["reasons"]) 