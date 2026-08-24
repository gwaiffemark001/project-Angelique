from skills.trading_skill.position_display import format_position_row, pip_size


def test_position_display_calculates_pips_and_r_multiple():
    row = format_position_row(
        {"ticket": 4, "symbol": "EURUSDm", "type": "BUY", "price_open": 1.1000, "sl": 1.0980, "tp": 1.1040, "profit": 12.5, "expected_profit": 20.0},
        {"bid": 1.1020, "ask": 1.1021, "spread_pips": 1.0},
    )
    assert row["current"] == 1.102
    assert row["to_stop_pips"] == 40.0
    assert row["to_target_pips"] == 20.0
    assert row["total_stop_pips"] == 20.0
    assert row["total_target_pips"] == 40.0
    assert row["r_multiple"] == 1.0
    assert row["expected_profit"] == 20.0
    assert row["status"] == "PROFIT"


def test_position_display_uses_jpy_pip_size_for_sell():
    assert pip_size("USDJPYm") == 0.01
    row = format_position_row(
        {"symbol": "USDJPYm", "type": "SELL", "price_open": 150.0, "sl": 150.5, "tp": 149.0},
        {"bid": 149.8, "ask": 149.82},
    )
    assert row["current"] == 149.82
    assert row["status"] == "PROFIT"
    assert row["to_target_pips"] == 82.0