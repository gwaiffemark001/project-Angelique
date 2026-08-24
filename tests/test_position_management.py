from skills.trading_skill.position_monitor import PositionMonitor


def position(mode="DAY_TRADING"):
    return {
        "ticket": 42,
        "symbol": "EURUSDm",
        "direction": "BUY",
        "entry": 1.1000,
        "stop_loss": 1.0980,
        "trading_mode": mode,
    }


def test_position_holds_before_one_r():
    decision = PositionMonitor.evaluate_position(position(), {"price": 1.1008, "atr": 0.001})
    assert decision["action"] == "HOLD"
    assert decision["r_multiple"] == 0.4


def test_position_moves_to_break_even_at_one_r():
    decision = PositionMonitor.evaluate_position(position(), {"price": 1.1020, "atr": 0.001})
    assert decision["action"] == "BREAK_EVEN"
    assert decision["suggested_stop"] == 1.1


def test_position_trails_after_two_r_and_preserves_mode():
    decision = PositionMonitor.evaluate_position(position("SWING_TRADING"), {"price": 1.1040, "atr": 0.001, "structure_stop": 1.1025})
    assert decision["action"] == "TRAIL"
    assert decision["suggested_stop"] == 1.1025
    assert decision["trading_mode"] == "SWING_TRADING"


def test_position_monitor_accepts_mt5_price_open_and_sl_fields():
    mt5_position = {
        "ticket": 77,
        "symbol": "NZDUSDm",
        "type": "BUY",
        "price_open": 0.5980,
        "sl": 0.5970,
    }
    decision = PositionMonitor.evaluate_position(mt5_position, {"price": 0.5990})
    assert decision["valid"] is True
    assert decision["r_multiple"] == 1.0
    assert decision["action"] == "BREAK_EVEN"