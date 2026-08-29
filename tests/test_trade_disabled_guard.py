from types import SimpleNamespace
from unittest.mock import patch
from skills.trading_skill.wine_server import execute


def test_execute_fails_closed_when_terminal_trading_disabled():
    mt5 = SimpleNamespace(
        ORDER_TYPE_BUY=0, ORDER_TYPE_SELL=1,
        SYMBOL_TRADE_MODE_DISABLED=0,
        TRADE_RETCODE_DONE=10009,
        TRADE_RETCODE_PLACED=10008,
        TRADE_RETCODE_DONE_PARTIAL=10010,
        ORDER_TIME_GTC=0,
        ORDER_FILLING_FOK=0,
        ORDER_FILLING_IOC=1,
        ORDER_FILLING_RETURN=2,
        SYMBOL_FILLING_FOK=1,
        SYMBOL_FILLING_IOC=2,
        SYMBOL_TRADE_EXECUTION_MARKET=2,
        terminal_info=lambda: SimpleNamespace(trade_allowed=False),
        account_info=lambda: SimpleNamespace(trade_allowed=True),
        symbol_select=lambda *a: True,
        symbol_info=lambda *_: None,
        symbol_info_tick=lambda *_: None,
    )
    request = {"account_mode": "demo", "order": {"symbol": "EURUSD", "mt5_symbol": "EURUSD", "direction": "BUY", "volume": 0.01, "stop_loss": 1.0, "take_profit": 2.0}}
    import skills.trading_skill.wine_server as ws
    with patch("importlib.import_module", return_value=mt5), patch.object(ws, "_connect", return_value=True):
        result = execute(request)
    assert result["success"] is False
    assert result["failure_stage"] == "trading_disabled"
