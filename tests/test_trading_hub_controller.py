from gui.trading_hub_controller import TradingHubController


def test_load_refresh_returns_stable_view_data(monkeypatch):
    from skills.trading.engine import account, connection_manager
    from skills.trading.market import market_data

    monkeypatch.setattr(account, "get_account_summary", lambda account_mode: {"login": 7, "mode": account_mode, "balance": 100})
    monkeypatch.setattr(connection_manager.bridge_manager, "get_status", lambda: True)
    monkeypatch.setattr(connection_manager.bridge_manager, "send_command", lambda name, args: {"instruments": ["EURUSD"]})
    monkeypatch.setattr(market_data.market, "get_candles_and_indicators", lambda symbol, timeframe, account_mode: {"symbol": symbol, "timeframe": timeframe, "candles": [1]})

    result = TradingHubController().load_refresh("EURUSD", "H1", "demo")

    assert result.symbol == "EURUSD"
    assert result.account["login"] == 7
    assert result.market_data["candles"] == [1]
    assert result.bridge_active is True
    assert result.instruments == {"instruments": ["EURUSD"]}


def test_monitor_is_delegated_to_trading_service(monkeypatch):
    from skills.trading_skill import service

    expected = {"state": "WAITING", "candidates": []}
    received = {}

    def monitor(account_mode, trading_mode="DAY_TRADING"):
        received["account_mode"] = account_mode
        received["trading_mode"] = trading_mode
        return expected

    monkeypatch.setattr(service, "monitor_universe", monitor)

    assert TradingHubController().monitor_opportunities("demo") == expected
    assert received == {"account_mode": "demo", "trading_mode": "DAY_TRADING"}


def test_swing_mode_is_forwarded_to_monitor(monkeypatch):
    from skills.trading_skill import service

    received = {}
    monkeypatch.setattr(
        service,
        "monitor_universe",
        lambda account_mode, trading_mode: received.update(account_mode=account_mode, trading_mode=trading_mode) or {"state": "WAITING"},
    )

    assert TradingHubController("SWING_TRADING").monitor_opportunities("demo") == {"state": "WAITING"}
    assert received["trading_mode"] == "SWING_TRADING"
