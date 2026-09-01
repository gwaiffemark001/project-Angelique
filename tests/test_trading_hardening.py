import pytest
from types import SimpleNamespace


def _candle(i, o, h, l, c, closed=True):
    return {"time": i, "open": o, "high": h, "low": l, "close": c, "closed": closed}


def _series(n=220, base=1.1):
    return [_candle(i, base + i * 0.00001, base + 0.0002 + i * 0.00001, base - 0.0002 + i * 0.00001, base + 0.00005 + i * 0.00001) for i in range(n)]


def _specs():
    return {"point": 0.00001, "digits": 5, "tick_size": 0.00001, "tick_value": 1.0, "volume_step": 0.01, "volume_min": 0.01, "volume_max": 10.0, "margin_per_volume": 100.0}


def test_indicator_snapshot_never_ready_from_five_candles():
    from skills.trading_skill.indicators import snapshot
    result = snapshot(_series(5))
    assert result["status"] == "insufficient"
    assert result["available_candles"] == 5


def test_price_units_distinguish_fx_pips_and_metal_points():
    from core.price_units import normalize_spread
    fx = normalize_spread("EURUSD", 0.00012, _specs())
    assert round(fx["spread_points"], 6) == 12
    assert round(fx["spread_pips"], 6) == 1.2
    assert fx["spread_unit"] == "pips"
    metal = normalize_spread("XAUUSD", 0.35, {"point": 0.01, "digits": 2})
    assert round(metal["spread_points"], 6) == 35
    assert metal["spread_pips"] is None
    assert metal["spread_unit"] == "points"


def test_correlation_shared_currency_blocks_eurusd_and_gbpusd():
    from skills.trading_skill.correlation_manager import evaluate_portfolio
    result = evaluate_portfolio("GBPUSD", "BUY", 1.0, [{"symbol": "EURUSD", "type": "BUY", "risk_percent": 1.0}], max_positions=3, max_open_risk=3.0, strict_shared_currency=True)
    assert not result["valid"]
    assert "USD" in result["shared_currency"]["shared_currencies"]


def test_missing_sl_is_unknown_risk_and_blocks_new_trade():
    from skills.trading_skill.risk import validate_profile_limits
    from skills.trading_skill.profiles import get_trading_profile
    result = validate_profile_limits({"equity": 1000, "daily_loss_percent": 0, "weekly_loss_percent": 0}, [{"symbol": "EURUSD", "risk_percent": None}], get_trading_profile("DAY_TRADING"), new_risk_percent=1.0, symbol="GBPUSD", direction="BUY")
    assert not result["valid"]
    assert result["unknown_risk_positions"]


def test_structural_buy_levels_use_validated_swings_not_window_extremes():
    from skills.trading_skill.trade_levels import calculate_trade_levels
    structure = {
        "swing_highs": [(10, 1.1100), (30, 1.1200), (50, 1.1300)],
        "swing_lows": [(12, 1.0900), (32, 1.0950), (48, 1.1000)],
        "structural_points": [
            {"index": 10, "timestamp": 10, "type": "swing_high", "strength": 2, "valid": True},
            {"index": 30, "timestamp": 30, "type": "swing_high", "strength": 2, "valid": True},
            {"index": 50, "timestamp": 50, "type": "swing_high", "strength": 2, "valid": True},
            {"index": 12, "timestamp": 12, "type": "swing_low", "strength": 2, "valid": True},
            {"index": 32, "timestamp": 32, "type": "swing_low", "strength": 2, "valid": True},
            {"index": 48, "timestamp": 48, "type": "swing_low", "strength": 2, "valid": True},
        ],
    }
    analysis = {"smc": {"M15": {"structure": structure}}}
    profile = SimpleNamespace(structure_timeframe="M15", minimum_rr=2.0)
    result = calculate_trade_levels(symbol="EURUSD", direction="BUY", strategy="SMC", analysis=analysis, timeframes={}, specs=_specs(), profile=profile, entry=1.1050)
    assert result["valid"]
    assert result["stop_swing"]["index"] == 48
    assert result["target_swing"]["index"] == 50
    assert result["stop_loss"] < 1.1000
    assert result["take_profit"] == 1.1300


def test_strategy_plan_context_does_not_require_a_swing_scan():
    from skills.trading_skill.trade_levels import calculate_trade_levels
    profile = SimpleNamespace(structure_timeframe="M15", minimum_rr=1.5)
    plan_context = {
        "target": 1.12000,
        "target_basis": "Breakout measured move",
        "stop_reference": 1.09600,
        "stop_basis": "Opposite side of the broken range",
    }
    result = calculate_trade_levels(
        symbol="EURUSD", direction="BUY", strategy="BREAKOUT",
        analysis={"smc": {}}, timeframes={}, specs=_specs(),
        profile=profile, entry=1.10500, bid=1.09990, ask=1.10000,
        plan_context=plan_context,
    )
    assert result["valid"], result.get("reason")
    assert result["take_profit"] == pytest.approx(1.12000)
    assert result["stop_loss"] < 1.09600
    assert result["target_basis"] == "Breakout measured move"
    assert result["stop_basis"] == "Opposite side of the broken range"


def test_position_close_pending_is_not_called_closed():
    from skills.trading_skill.position_monitor import PositionMonitor

    class Bridge:
        def __init__(self):
            self.calls = []
        def request(self, operation, payload):
            self.calls.append((operation, payload))
            return {"success": True, "status": "verification_pending", "ticket": payload["ticket"]}

    bridge = Bridge()
    monitor = PositionMonitor(bridge)
    first = monitor.close_single(123, "EURUSD")
    second = monitor.close_single(123, "EURUSD")
    assert first["status"] == "verification_pending"
    assert second["status"] == "verification_pending"
    assert len(bridge.calls) == 1


def test_position_monitor_pauses_technical_management_on_stale_data():
    from skills.trading_skill.position_monitor import PositionMonitor
    position = {"ticket": 1, "symbol": "EURUSD", "direction": "BUY", "entry": 1.1000, "stop_loss": 1.0950, "opened_at": "2026-08-29T10:00:00+00:00"}
    result = PositionMonitor.evaluate_position(position, {"price": 1.1100, "data_quality": "stale", "data_quality_reason": "old candles"})
    assert result["action"] == "HOLD"
    assert result["management_status"] == "DATA_UNAVAILABLE"


def test_closed_candle_validation_rejects_forming_candle():
    from skills.trading_skill.data_quality import assess_candles
    result = assess_candles(_series(25) + [_candle(999, 1.1, 1.2, 1.0, 1.15, closed=False)], "M5", minimum_candles=20, require_closed=True)
    assert result["status"] == "invalid"


def test_safety_gate_rejects_noncanonical_risk_percent():
    from skills.trading_skill.safety import validate_trade_setup
    result = validate_trade_setup(symbol="EURUSD", direction="BUY", entry=1.1, stop_loss=1.09, take_profit=1.13, risk_amount=5, risk_percent=0.5, volume=0.1, margin_required=10, free_margin_after=990, minimum_free_margin=0, projected_margin_level=1000, spread_pips=0.8, minimum_rr=2.0, maximum_spread_pips=1.5)
    assert not result["valid"]
    assert any("requires 1.00%" in reason for reason in result["reasons"])

def test_next_swing_target_is_chronological_not_closest_price():
    from skills.trading_skill.trade_levels import calculate_trade_levels
    structure = {
        "swing_highs": [(10, 1.1100), (30, 1.1150), (50, 1.1300), (70, 1.1180)],
        "swing_lows": [(12, 1.0900), (32, 1.0950), (48, 1.1000)],
        "structural_points": [
            *[{"index": i, "timestamp": i, "type": "swing_high", "strength": 2, "valid": True} for i in (10, 30, 50, 70)],
            *[{"index": i, "timestamp": i, "type": "swing_low", "strength": 2, "valid": True} for i in (12, 32, 48)],
        ],
    }
    analysis = {"smc": {"M15": {"structure": structure}}}
    profile = SimpleNamespace(structure_timeframe="M15", minimum_rr=1.0)
    result = calculate_trade_levels(
        symbol="EURUSD", direction="BUY", strategy="SMC", analysis=analysis,
        timeframes={}, specs=_specs(), profile=profile, entry=1.1050,
    )
    assert result["valid"]
    # 1.1300 is the first valid upside swing after the relevant 1.1000 low;
    # 1.1180 is numerically closer to entry but occurs later and is not the next swing.
    assert result["target_swing"]["index"] == 50
    assert result["take_profit"] == 1.1300
