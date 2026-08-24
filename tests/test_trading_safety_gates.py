import pytest

from core.execution_gateway import GATEWAY
import core.trading_gateway
from skills.trading_skill.profiles import DAY_PROFILE
from skills.trading_skill.risk import validate_profile_limits
from skills.trading_skill.risk import build_risk


def test_trading_tools_are_registered_with_gateway():
    assert GATEWAY.registry.get("trading.execute_approved_trade") is not None
    assert GATEWAY.registry.get("trading.close_position") is not None


def test_portfolio_limit_rejects_max_positions():
    result = validate_profile_limits({}, [{"ticket": number} for number in range(3)], DAY_PROFILE)
    assert result["valid"] is False
    assert "Maximum positions reached" in result["reasons"][0]


def test_portfolio_limit_rejects_open_risk_and_loss_limits():
    result = validate_profile_limits(
        {"daily_loss_percent": 2.0, "weekly_loss_percent": 5.0},
        [{"risk_percent": 0.75}],
        DAY_PROFILE,
    )
    assert result["valid"] is False
    assert any("Open risk" in reason for reason in result["reasons"])
    assert any("Daily loss" in reason for reason in result["reasons"])
    assert any("Weekly loss" in reason for reason in result["reasons"])


def test_small_equity_uses_percentage_risk_and_rejects_broker_minimum():
    with pytest.raises(ValueError, match="Broker minimum volume"):
        build_risk(
            entry=1.1000,
            stop_loss=1.0900,
            equity=13.0,
            risk_percent=0.5,
            symbol_specs={
                "tick_size": 0.00001,
                "tick_value": 1.0,
                "volume_min": 0.01,
                "volume_max": 100.0,
                "volume_step": 0.01,
                "margin_per_volume": 1.0,
            },
            free_margin=13.0,
        )


def test_equity_scaling_keeps_risk_percentage_constant():
    specs = {
        "tick_size": 0.01,
        "tick_value": 1.0,
        "volume_min": 0.001,
        "volume_max": 100.0,
        "volume_step": 0.001,
        "margin_per_volume": 1.0,
    }
    small = build_risk(1.10, 1.09, 100.0, 0.5, specs, free_margin=100.0)
    large = build_risk(1.10, 1.09, 1000.0, 0.5, specs, free_margin=1000.0)
    assert small["risk_amount"] == 0.5
    assert large["risk_amount"] == 5.0
    assert small["volume"] < large["volume"]