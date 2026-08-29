from skills.trading_skill.bridge import WineBridgeClient
from skills.trading_skill.symbols import resolve


class MarketFacade:
    @staticmethod
    def _extract_candles(response, timeframe):
        frames = response.get("timeframes", {}) if isinstance(response, dict) else {}
        if isinstance(frames, dict):
            candles = frames.get(timeframe) or frames.get(str(timeframe).upper()) or frames.get(str(timeframe).lower())
            if isinstance(candles, list) and candles:
                return candles
        if isinstance(frames, list):
            return frames
        for key in ("candles", "rates", "data"):
            value = response.get(key) if isinstance(response, dict) else None
            if isinstance(value, list):
                return value
        return []

    def get_candles_and_indicators(self, symbol, timeframe="H1", account_mode="demo", count=200):
        client = WineBridgeClient()
        symbol_response = client.request("symbols", {"account_mode": account_mode})
        if (not isinstance(symbol_response, dict) or
                symbol_response.get("status") != "connected" or
                symbol_response.get("mode_match") is False or
                not symbol_response.get("symbols")):
            return {"symbol": symbol, "requested_symbol": symbol, "timeframe": timeframe,
                    "candles": [], "latest_candle": {}, "bid": None, "ask": None,
                    "spread": None, "spread_pips": None, "symbol_specs": {},
                    "timestamp": None, "stale": True, "indicators": {},
                    "account_mode": account_mode, "mode_match": False,
                    "error": (symbol_response.get("error") if isinstance(symbol_response, dict) else "Account mode mismatch.")}
        available = symbol_response.get("symbols", [])
        resolved = resolve(symbol, available) or symbol
        response = client.request("market", {"symbol": resolved, "timeframes": [timeframe], "account_mode": account_mode, "count": count})
        candles = self._extract_candles(response, timeframe)
        result = {
            "symbol": response.get("mt5_symbol", resolved),
            "requested_symbol": symbol,
            "timeframe": timeframe,
            "candles": candles,
            "latest_candle": candles[-1] if candles else {},
            "bid": response.get("bid"),
            "ask": response.get("ask"),
            "spread": response.get("spread"),
            "spread_pips": response.get("spread_pips"),
            "symbol_specs": response.get("symbol_specs", {}),
            "timestamp": response.get("timestamp") or response.get("last_tick"),
            "stale": bool(response.get("stale", False)),
            "indicators": response.get("indicators", {}),
            "account_mode": account_mode,
            "mode_match": response.get("mode_match", True),
        }
        if response.get("error"):
            result["error"] = response["error"]
        if response.get("suggestions"):
            result["suggestions"] = response["suggestions"]
        return result


market = MarketFacade()
