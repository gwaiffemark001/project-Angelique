import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from skills.trading.trading_skill import analyze_and_recommend, create_trade_plan


def test_create_trade_plan_returns_dict_and_brief(monkeypatch):
    monkeypatch.setattr(
        'skills.trading.trading_skill.get_account_summary',
        lambda account_mode='demo': {
            'balance': 10000.0,
            'equity': 10000.0,
            'free_margin': 9000.0,
            'margin_level': 100.0,
            'leverage': 100,
            'currency': 'USD',
            'mode': 'demo',
            'display_mode': 'demo',
            'requested_mode': 'demo',
            'mode_match': True,
            'status': 'connected',
        },
    )

    monkeypatch.setattr(
        'skills.trading.trading_skill.market',
        type('DummyMarket', (), {
            'get_candles_and_indicators': staticmethod(lambda symbol, timeframe, account_mode='demo': {
                'candles': [
                    {'time': '2025-01-01T00:00:00Z', 'open': 1.0, 'high': 1.2, 'low': 0.9, 'close': 1.1, 'tick_volume': 100},
                    {'time': '2025-01-01T00:15:00Z', 'open': 1.1, 'high': 1.25, 'low': 1.05, 'close': 1.2, 'tick_volume': 120},
                ],
                'latest_candle': {'time': '2025-01-01T00:15:00Z', 'open': 1.1, 'high': 1.25, 'low': 1.05, 'close': 1.2, 'tick_volume': 120},
                'indicators': {'atr': 0.01, 'bb_upper': 1.25, 'bb_lower': 1.05, 'EMA_50': 1.15, 'EMA_200': 1.05, 'RSI_14': 55},
            }),
        })(),
    )

    plan = create_trade_plan('EURUSD', timeframe='H1', risk_percent=1.0, entry_price=1.2, account_mode='demo')

    assert isinstance(plan, dict)
    assert plan['symbol'] == 'EURUSD'
    assert plan['timeframe'] == 'H1'
    assert 'brief' in plan
    assert 'approved' in plan
    assert plan['analysis']['order_type'] in {'BUY', 'SELL'}
    assert plan['analysis']['entry_price'] == 1.2


def test_analyze_and_recommend_does_not_auto_execute_by_default(monkeypatch):
    monkeypatch.setattr(
        'skills.trading.trading_skill.get_account_summary',
        lambda account_mode='demo': {
            'balance': 10000.0,
            'equity': 10000.0,
            'free_margin': 9000.0,
            'margin_level': 100.0,
            'leverage': 100,
            'currency': 'USD',
            'mode': 'demo',
            'display_mode': 'demo',
            'requested_mode': 'demo',
            'mode_match': True,
            'status': 'connected',
        },
    )

    monkeypatch.setattr(
        'skills.trading.trading_skill.market',
        type('DummyMarket', (), {
            'get_candles_and_indicators': staticmethod(lambda symbol, timeframe, account_mode='demo': {
                'candles': [
                    {'time': '2025-01-01T00:00:00Z', 'open': 1.0, 'high': 1.2, 'low': 0.9, 'close': 1.1, 'tick_volume': 100},
                    {'time': '2025-01-01T00:15:00Z', 'open': 1.1, 'high': 1.25, 'low': 1.05, 'close': 1.2, 'tick_volume': 120},
                ],
                'latest_candle': {'time': '2025-01-01T00:15:00Z', 'open': 1.1, 'high': 1.25, 'low': 1.05, 'close': 1.2, 'tick_volume': 120},
                'indicators': {'atr': 0.01, 'bb_upper': 1.25, 'bb_lower': 1.05, 'EMA_50': 1.15, 'EMA_200': 1.05, 'RSI_14': 55},
            }),
        })(),
    )

    result = analyze_and_recommend('EURUSD', timeframe='H1', risk_percent=1.0, account_mode='demo')

    assert isinstance(result, str)
    assert 'AUTO-EXECUTED' not in result
    assert 'AUTO-TRADE BLOCKED' not in result
    assert 'ANGELIQUE TRADE PROPOSAL' in result or 'PROPOSED TRADE REJECTED' in result


def test_analyze_and_recommend_auto_execute_blocks_unapproved_trades(monkeypatch):
    monkeypatch.setattr(
        'skills.trading.trading_skill.get_account_summary',
        lambda account_mode='demo': {
            'balance': 100.0,
            'equity': 100.0,
            'free_margin': 50.0,
            'margin_level': 100.0,
            'leverage': 100,
            'currency': 'USD',
            'mode': 'demo',
            'display_mode': 'demo',
            'requested_mode': 'demo',
            'mode_match': True,
            'status': 'connected',
        },
    )

    monkeypatch.setattr(
        'skills.trading.trading_skill.market',
        type('DummyMarket', (), {
            'get_candles_and_indicators': staticmethod(lambda symbol, timeframe, account_mode='demo': {
                'candles': [
                    {'time': '2025-01-01T00:00:00Z', 'open': 1.0, 'high': 1.05, 'low': 0.95, 'close': 0.98, 'tick_volume': 100},
                    {'time': '2025-01-01T00:15:00Z', 'open': 0.98, 'high': 1.0, 'low': 0.95, 'close': 0.96, 'tick_volume': 120},
                ],
                'latest_candle': {'time': '2025-01-01T00:15:00Z', 'open': 0.98, 'high': 1.0, 'low': 0.95, 'close': 0.96, 'tick_volume': 120},
                'indicators': {'atr': 0.01, 'bb_upper': 1.0, 'bb_lower': 0.95, 'EMA_50': 0.98, 'EMA_200': 1.0, 'RSI_14': 25},
            }),
        })(),
    )

    result = analyze_and_recommend('EURUSD', timeframe='H1', risk_percent=1.0, auto_execute=True, account_mode='demo')

    assert isinstance(result, str)
    assert 'AUTO-TRADE BLOCKED' in result
