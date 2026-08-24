from skills.trading.engine.trading_status import (
    build_trading_status_banner,
    get_bridge_status_label,
    get_mt5_data_badge_text,
    get_trading_status_state,
)


def test_live_mode_connected_banner_is_explicit():
    state = get_trading_status_state("live", True, None)
    assert state["label"] == "REAL MT5 CONNECTED"
    assert state["tone"] == "success"


def test_real_mode_connected_banner_is_explicit():
    state = get_trading_status_state("real", True, None)
    assert state["label"] == "REAL MT5 CONNECTED"
    assert state["tone"] == "success"


def test_demo_mode_offline_banner_is_explicit():
    state = get_trading_status_state("demo", False, "bridge offline")
    assert state["label"] == "DEMO MODE ACTIVE"
    assert state["tone"] == "warning"


def test_banner_text_includes_status_and_mode():
    text = build_trading_status_banner("real", True, None, balance=1250.0)
    assert "REAL MT5 CONNECTED" in text
    assert "Balance" in text


def test_real_mode_offline_uses_danger_color():
    state = get_trading_status_state("real", False, "bridge offline")
    assert state["tone"] == "danger"
    assert state["color"] == "#dc2626"


def test_mode_mismatch_connected_banner_shows_account_mode_mismatch():
    state = get_trading_status_state(
        "real",
        True,
        "Bridge is connected to DEMO account, not REAL.",
        mode_match=False,
    )
    assert state["label"] == "ACCOUNT MODE MISMATCH"
    assert state["tone"] == "warning"
    assert "Bridge is connected to DEMO account" in state["detail"]


def test_bridge_status_marks_offline_when_disconnected():
    assert get_bridge_status_label(False, None) == "Bridge unavailable: MT5 connection is offline."
    assert get_bridge_status_label(True, None) == "Bridge connected and ready."


def test_mt5_badge_is_unavailable_without_account_login():
    assert get_mt5_data_badge_text("real", "real", True, False, None, False) == "MT5 unavailable"
    assert get_mt5_data_badge_text("real", "real", True, True, None, True) == "Using real MT5 data"
    assert get_mt5_data_badge_text("demo", "demo", True, True, None, True) == "Using demo MT5 data"
