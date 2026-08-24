from gui.trading_hub_controller import TradingHubController
from skills.trading_skill.profiles import DAY_PROFILE, SWING_PROFILE, TradingMode, get_trading_profile


def test_day_profile_matches_specification():
    assert DAY_PROFILE.mode is TradingMode.DAY
    assert DAY_PROFILE.required_timeframes == ("H4", "H1", "M15", "M5")
    assert DAY_PROFILE.risk_per_trade == 0.5
    assert DAY_PROFILE.max_spread_pips == 1.5
    assert DAY_PROFILE.minimum_score == 7


def test_swing_profile_matches_specification():
    assert SWING_PROFILE.mode is TradingMode.SWING
    assert SWING_PROFILE.required_timeframes == ("D1", "H4", "H1")
    assert SWING_PROFILE.risk_per_trade == 1.0
    assert SWING_PROFILE.max_spread_pips == 3.0
    assert SWING_PROFILE.minimum_score == 7


def test_controller_mode_persists_until_changed():
    controller = TradingHubController()
    assert controller.trading_mode == "DAY_TRADING"
    profile = controller.set_trading_mode("SWING")
    assert controller.trading_mode == "SWING_TRADING"
    assert profile["entry_timeframe"] == "H1"
    assert controller.get_trading_profile()["mode"] == "SWING_TRADING"


def test_profile_aliases_are_explicit():
    assert get_trading_profile("day").mode is TradingMode.DAY
    assert get_trading_profile("SWING_TRADING").mode is TradingMode.SWING