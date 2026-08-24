from skills.trading.market.fresh_market import MarketFacade


class FakeClient:
    def __init__(self, response):
        self.response = response

    def request(self, operation, payload):
        if operation == "symbols":
            return {"symbols": ["EURUSDm"]}
        return self.response


def test_market_facade_reads_candles_and_quotes(monkeypatch):
    response = {
        "mt5_symbol": "EURUSDm",
        "timeframes": {"m1": [{"close": 1.1}]},
        "bid": 1.0999,
        "ask": 1.1001,
        "spread_pips": 2.0,
    }
    monkeypatch.setattr("skills.trading.market.fresh_market.WineBridgeClient", lambda: FakeClient(response))
    result = MarketFacade().get_candles_and_indicators("EURUSD", "M1")
    assert result["candles"] == [{"close": 1.1}]
    assert result["bid"] == 1.0999
    assert result["ask"] == 1.1001


def test_market_facade_falls_back_to_rates(monkeypatch):
    rates = [{"close": 1.2}]
    monkeypatch.setattr("skills.trading.market.fresh_market.WineBridgeClient", lambda: FakeClient({"rates": rates}))
    assert MarketFacade().get_candles_and_indicators("EURUSD", "M1")["candles"] == rates