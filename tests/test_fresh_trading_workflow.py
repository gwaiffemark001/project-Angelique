from skills.trading_skill.account import account_snapshot
from skills.trading_skill.models import WorkflowState
from skills.trading_skill.symbols import resolve
from skills.trading_skill.workflow import TradingWorkflow


def candles(direction="bullish"):
    values = range(1, 31) if direction == "bullish" else range(30, 0, -1)
    return [{"open": value, "high": value + 0.5, "low": value - 0.5, "close": value} for value in values]


class Adapter:
    def __init__(self, direction="bullish"):
        self.direction = direction
        self.executions = []

    def account(self, mode):
        return {"login": 101, "balance": 1000, "equity": 1000, "free_margin": 900, "currency": "USD", "mode_match": True}

    def symbols(self, mode):
        return ["EURUSDm"]

    def market(self, symbol, timeframes, mode, count):
        data = candles(self.direction)
        return {"timeframes": {timeframe: data for timeframe in timeframes}, "bid": 30.0, "ask": 30.1, "symbol_specs": {"tick_size": 0.01, "tick_value": 1, "volume_min": 0.01, "volume_max": 10, "volume_step": 0.01, "margin_per_volume": 10}}

    def execute(self, order, mode):
        self.executions.append(order)
        return {"success": True, "ticket": 55}


def test_unavailable_account_is_zeroed():
    snapshot = account_snapshot({"login": None, "balance": 9999, "error": "not connected"}, "real")
    assert snapshot.connected is False
    assert snapshot.login is None
    assert snapshot.balance == 0
    assert snapshot.equity == 0


def test_symbol_resolution_uses_terminal_suffix():
    assert resolve("EUR/USD", ["GBPUSD", "EURUSDm"]) == "EURUSDm"


def test_prepare_requires_exact_approval_before_execution():
    adapter = Adapter()
    workflow = TradingWorkflow(adapter)
    prepared = workflow.prepare("EURUSD", "demo")
    assert prepared.state is WorkflowState.APPROVAL_REQUIRED
    assert adapter.executions == []
    assert workflow.execute("CONFIRM BUY wrong") .state is WorkflowState.REJECTED
    executed = workflow.execute(prepared.plan.confirmation_phrase)
    assert executed.state is WorkflowState.EXECUTED
    assert len(adapter.executions) == 1


def test_conflicting_timeframe_is_rejected():
    adapter = Adapter("bullish")
    original_market = adapter.market

    def conflicting_market(symbol, timeframes, mode, count):
        response = original_market(symbol, timeframes, mode, count)
        response["timeframes"]["M5"] = candles("bearish")
        return response

    adapter.market = conflicting_market
    result = TradingWorkflow(adapter).prepare("EURUSD")
    assert result.state is WorkflowState.REJECTED
    assert "conflict" in result.message.lower()
