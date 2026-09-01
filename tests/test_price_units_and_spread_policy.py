from core.price_units import instrument_class, normalize_spread, pip_size_from_specs, spread_policy
from skills.trading_skill.safety import validate_trade_setup


def test_fx_major_and_cross_use_fx_pips():
    specs = {"point": 0.00001, "digits": 5, "tick_size": 0.00001}
    assert instrument_class("EURUSD.VX", specs) == "FX_MAJOR"
    assert instrument_class("GBPJPY.VX", {**specs, "point": 0.001, "digits": 3}) == "FX_CROSS"
    assert pip_size_from_specs("EURUSD.VX", specs) == 0.0001
    assert pip_size_from_specs("GBPJPY.VX", {"point": 0.001, "digits": 3}) == 0.01
    norm = normalize_spread("EURUSD.VX", 0.00012, specs)
    assert norm["spread_pips"] == 1.2
    assert norm["spread_unit"] == "pips"


def test_metals_use_ticks_not_fx_pips():
    specs = {"point": 0.01, "digits": 2, "tick_size": 0.01}
    assert instrument_class("XAUUSD", specs) == "METAL"
    assert pip_size_from_specs("XAUUSD", specs) == 0.0
    norm = normalize_spread("XAUUSD", 0.35, specs)
    assert norm["spread_pips"] is None
    assert norm["spread_ticks"] == 35.0
    assert norm["spread_unit"] == "ticks"
    policy = spread_policy("XAUUSD", specs, "DAY_TRADING")
    assert policy["max_unit"] == "ticks"
    assert policy["max_price"] == 0.40


def test_crypto_uses_price_percentage_policy():
    specs = {"point": 0.01, "digits": 2, "tick_size": 0.01, "bid": 100000.0, "ask": 100001.0}
    assert instrument_class("BTCUSD", specs) == "CRYPTO"
    norm = normalize_spread("BTCUSD", 1.0, specs)
    assert norm["spread_pips"] is None
    assert norm["spread_unit"] == "price"
    policy = spread_policy("BTCUSD", specs, "DAY_TRADING")
    assert policy["max_unit"] == "%"
    assert policy["max_price"] >= 100.0


def test_safety_uses_raw_price_policy_when_symbol_specs_are_available():
    specs = {"point": 0.01, "digits": 2, "tick_size": 0.01, "tick_value": 0.01, "bid": 100000.0, "ask": 100001.0, "trading_mode": "DAY_TRADING"}
    kwargs = dict(symbol="BTCUSD", direction="BUY", entry=100001.0, stop_loss=99901.0, take_profit=100201.0,
                  risk_amount=5.0, risk_percent=1.0, volume=0.01, margin_required=10.0,
                  free_margin_after=990.0, minimum_free_margin=0.0, projected_margin_level=1000.0,
                  spread=1.0, spread_ticks=100.0, symbol_specs=specs, minimum_rr=2.0)
    assert validate_trade_setup(**kwargs)["valid"]
    blocked = dict(kwargs, spread=250.0, spread_ticks=25000.0)
    assert not validate_trade_setup(**blocked)["valid"]
