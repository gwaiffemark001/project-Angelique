from skills.trading_skill.bridge import WineBridgeClient
from skills.trading_skill.symbols import resolve


class MarketFacade:
    def get_candles_and_indicators(self, symbol, timeframe="H1", account_mode="demo"):
        client = WineBridgeClient()
        available = client.request("symbols", {"account_mode": account_mode}).get("symbols", [])
        resolved = resolve(symbol, available) or symbol
        response = client.request("market", {"symbol": resolved, "timeframes": [timeframe], "account_mode": account_mode, "count": 200})
        candles = response.get("timeframes", {}).get(timeframe, [])
        return {"symbol": response.get("mt5_symbol", resolved), "requested_symbol": symbol, "candles": candles, "latest_candle": candles[-1] if candles else {}, "indicators": {}, **({"error": response["error"]} if response.get("error") else {})}


market = MarketFacade()
