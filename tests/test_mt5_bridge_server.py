import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

module_path = ROOT / 'skills' / 'trading' / 'engine' / 'mt5_bridge_server.py'
spec = importlib.util.spec_from_file_location('mt5_bridge_server', module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_initialize_mt5_without_mt5_module_returns_error_payload():
    module.mt5 = None
    result = module.initialize_mt5()
    assert result['error'].startswith('MetaTrader5 module is not available')


def test_get_rates_for_symbol_returns_correct_rate_count_and_timeframe():
    rates = module.get_rates_for_symbol('EURUSD', 'M15', count=20, seed=123)
    assert isinstance(rates, list)
    assert len(rates) == 20
    assert all('time' in rate and 'open' in rate and 'high' in rate and 'low' in rate and 'close' in rate for rate in rates)

    # verify timeframe spacing uses 15-minute intervals
    from datetime import datetime
    times = [datetime.fromisoformat(rate['time'].replace('Z', '')) for rate in rates]
    intervals = [(times[i] - times[i - 1]).total_seconds() / 60 for i in range(1, len(times))]
    assert all(abs(interval - 15) < 0.001 for interval in intervals)


def test_normalize_timeframe_accepts_lowercase_and_invalid_values():
    assert module._normalize_timeframe('m1') == 'M1'
    assert module._normalize_timeframe('h4') == 'H4'
    assert module._normalize_timeframe('invalid') == 'H1'
    assert module._normalize_timeframe(None) == 'H1'


def test_place_order_returns_success_payload_for_valid_request():
    result = module.place_order({
        'symbol': 'EURUSD',
        'type': 'BUY',
        'volume': 0.01,
        'sl': 1.0950,
        'tp': 1.1050,
        'comment': 'Angelique test',
    })

    assert result['success'] is True
    assert result['ticket']
    assert result['symbol'] == 'EURUSD'
    assert result['type'] == 'BUY'
    assert result['price'] > 0


def test_get_account_info_reports_selected_mode():
    result = module.get_account_info({'account_mode': 'demo'})

    # When MetaTrader5 is available this should return real account info with mode
    # When MT5 is not installed, the bridge will return an error payload — accept either.
    if 'error' in result:
        assert isinstance(result['error'], str)
    else:
        assert result['mode'] == 'demo'
        assert result['balance'] >= 0


def test_get_rates_for_symbol_rejects_live_mode_when_connected_to_demo(monkeypatch):
    class DummyAccountInfo:
        def __init__(self):
            self.server = 'DemoServer'
            self.trade_mode = 1

    class DummyMT5:
        TIMEFRAME_M1 = 1
        TIMEFRAME_H1 = 2

        def initialize(self):
            return True

        def account_info(self):
            return DummyAccountInfo()

        def symbol_select(self, symbol, flag):
            return True

        def copy_rates_from(self, symbol, timeframe, utc_from, count):
            from collections import namedtuple
            Rate = namedtuple('Rate', ['time', 'open', 'high', 'low', 'close', 'tick_volume'])
            return [Rate(time='2024-01-01T00:00:00Z', open=1.0, high=1.1, low=0.9, close=1.05, tick_volume=100)] * count

    monkeypatch.setitem(sys.modules, 'MetaTrader5', DummyMT5())
    result = module.get_rates_for_symbol('EURUSD', 'H1', count=5, account_mode='real')
    assert isinstance(result, dict)
    assert result['status'] == 'error'
    assert 'Requested live account mode but MT5 is connected to demo account' in result['error']


def test_get_rates_for_symbol_treats_non_zero_trade_mode_as_live(monkeypatch):
    class DummyAccountInfo:
        def __init__(self):
            self.server = 'LiveServer'
            self.trade_mode = 2

    class DummyMT5:
        TIMEFRAME_M1 = 1
        TIMEFRAME_H1 = 2

        def initialize(self):
            return True

        def account_info(self):
            return DummyAccountInfo()

        def symbol_select(self, symbol, flag):
            return True

        def copy_rates_from(self, symbol, timeframe, utc_from, count):
            from collections import namedtuple
            Rate = namedtuple('Rate', ['time', 'open', 'high', 'low', 'close', 'tick_volume'])
            return [Rate(time='2024-01-01T00:00:00Z', open=1.0, high=1.1, low=0.9, close=1.05, tick_volume=100)] * count

    monkeypatch.setitem(sys.modules, 'MetaTrader5', DummyMT5())
    result = module.get_rates_for_symbol('EURUSD', 'H1', count=20, account_mode='real')
    assert isinstance(result, list)
    assert len(result) == 20


def test_get_account_info_detects_demo_from_server_name(monkeypatch):
    class DummyAccountInfo:
        def __init__(self):
            self.server = 'DemoServer'
            self.login = 123456
            self.balance = 500.0
            self.equity = 500.0
            self.margin_free = 500.0
            self.margin_level = 0.0
            self.leverage = 2000
            self.currency = 'USD'

    class DummyMT5:
        def initialize(self):
            return True

        def account_info(self):
            return DummyAccountInfo()

    monkeypatch.setitem(sys.modules, 'MetaTrader5', DummyMT5())
    result = module.get_account_info({'account_mode': 'demo'})
    assert result['mode'] == 'demo'
    assert result['requested_mode'] == 'demo'
    assert result['mode_match'] is True


def test_get_account_info_initializes_requested_mode_before_account_detection(monkeypatch):
    class DummyAccountInfo:
        def __init__(self):
            self.server = 'LiveServer'
            self.trade_mode = None
            self.login = 123456
            self.balance = 1000.0
            self.equity = 1000.0
            self.margin_free = 1000.0
            self.margin_level = 100.0
            self.leverage = 200
            self.currency = 'USD'

    class DummyMT5:
        def initialize(self):
            return True

        def account_info(self):
            return DummyAccountInfo()

    monkeypatch.setitem(sys.modules, 'MetaTrader5', DummyMT5())
    result = module.get_account_info({'account_mode': 'real'})
    assert result['requested_mode'] == 'live'
    assert result['mode'] == 'live'
    assert result['mode_match'] is True


def test_get_account_info_detects_demo_from_trial_server_name(monkeypatch):
    class DummyAccountInfo:
        def __init__(self):
            self.server = 'Exness-MT5Trial9'
            self.login = 987654
            self.balance = 100000.0
            self.equity = 100000.0
            self.margin_free = 100000.0
            self.margin_level = 100.0
            self.leverage = 500
            self.currency = 'USD'

    class DummyMT5:
        def initialize(self):
            return True

        def account_info(self):
            return DummyAccountInfo()

    monkeypatch.setitem(sys.modules, 'MetaTrader5', DummyMT5())
    result = module.get_account_info({'account_mode': 'real'})
    assert result['mode'] == 'demo'
    assert result['requested_mode'] == 'live'
    assert result['mode_match'] is False


def test_get_account_summary_zeroes_requested_account_on_mode_mismatch(monkeypatch):
    from skills.trading.engine import mt5_bridge

    monkeypatch.setattr(
        mt5_bridge.bridge,
        'get_account_info',
        lambda account_mode='demo': {
            'login': None,
            'balance': 500.0,
            'equity': 500.0,
            'free_margin': 500.0,
            'margin_level': 0.0,
            'leverage': 2000,
            'currency': 'USD',
            'mode': 'live',
            'requested_mode': 'real',
            'mode_match': False,
            'status': 'connected',
            'error': 'Requested live account mode does not match connected MT5 account mode (demo).',
        },
    )

    from skills.trading.engine.account import get_account_summary
    summary = get_account_summary(account_mode='real')
    assert summary['mode_match'] is False
    assert summary['mode'] == 'live'
    assert summary['display_mode'] == 'real'
    assert summary['requested_mode'] == 'live'
    assert summary['balance'] == 0
    assert summary['equity'] == 0
    assert summary['free_margin'] == 0
    assert summary['margin_level'] == 0
    assert summary['login'] is None


def test_get_account_summary_zeroes_requested_mode_on_mismatch(monkeypatch):
    from skills.trading.engine import mt5_bridge

    monkeypatch.setattr(
        mt5_bridge.bridge,
        'get_account_info',
        lambda account_mode='live': {
            'login': None,
            'balance': 1000.0,
            'equity': 1000.0,
            'free_margin': 1000.0,
            'margin_level': 0.0,
            'leverage': 1000,
            'currency': 'USD',
            'mode': 'demo',
            'requested_mode': 'real',
            'mode_match': False,
            'status': 'connected',
            'error': 'Requested live account mode does not match connected MT5 account mode (demo).',
        },
    )

    from skills.trading.engine.account import get_account_summary
    summary = get_account_summary(account_mode='real')
    assert summary['mode_match'] is False
    assert summary['mode'] == 'demo'
    assert summary['display_mode'] == 'real'
    assert summary['requested_mode'] == 'live'
    assert summary['balance'] == 0
    assert summary['equity'] == 0
    assert summary['free_margin'] == 0
    assert summary['margin_level'] == 0
    assert summary['login'] is None


def test_get_account_summary_preserves_requested_mode_on_bridge_error(monkeypatch):
    from skills.trading.engine import mt5_bridge

    monkeypatch.setattr(
        mt5_bridge.bridge,
        'get_account_info',
        lambda account_mode='demo': {
            'error': 'MT5 bridge unavailable',
            'status': 'error',
        },
    )

    from skills.trading.engine.account import get_account_summary
    summary = get_account_summary(account_mode='real')
    assert summary['balance'] == 0
    assert summary['login'] is None
    assert summary['requested_mode'] == 'live'
    assert summary['display_mode'] == 'real'
    assert summary['mode'] == 'live'
    assert summary['mode_match'] is True
    assert summary['error'] == 'MT5 bridge unavailable'


def test_get_account_summary_zeros_when_login_is_unavailable(monkeypatch):
    from skills.trading.engine import mt5_bridge

    monkeypatch.setattr(
        mt5_bridge.bridge,
        'get_account_info',
        lambda account_mode='demo': {
            'login': None,
            'balance': 10000.0,
            'equity': 10000.0,
            'free_margin': 10000.0,
            'margin_level': 0.0,
            'leverage': 100,
            'currency': 'USD',
            'mode': 'demo',
            'requested_mode': 'demo',
            'mode_match': True,
            'status': 'connected',
            'error': 'No MT5 account logged in',
        },
    )

    from skills.trading.engine.account import get_account_summary
    summary = get_account_summary(account_mode='demo')
    assert summary['balance'] == 0
    assert summary['equity'] == 0
    assert summary['free_margin'] == 0
    assert summary['margin_level'] == 0
    assert summary['login'] is None
    assert summary['error'] == 'No MT5 account logged in'
