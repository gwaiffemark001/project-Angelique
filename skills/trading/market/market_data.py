# skills/trading/market/market_data.py
import pandas as pd
import asyncio
from core import config
from skills.trading.engine.connection_manager import bridge_manager
from skills.trading.market.indicators import calculate_all_indicators


class MarketData:
    @staticmethod
    def get_candles_and_indicators(symbol: str, timeframe: str = "H1", count: int = 100) -> dict:
        """Fetch REAL market data from MT5 bridge, calculate indicators."""
        
        # Ensure connection to MT5 bridge
        if not bridge_manager.get_status():
            bridge_manager.ensure_connected()
            if not bridge_manager.get_status():
                return {"error": "MT5 bridge disconnected", "status": "error"}
        
        try:
            # Query actual market data from MT5 bridge
            request = {
                "command": "get_rates",
                "symbol": symbol,
                "timeframe": timeframe,
                "count": count
            }
            
            # Send to bridge via async or blocking call
            import time
            import json
            
            # Try to query the bridge's API endpoint
            response = bridge_manager.send_request(request)
            
            if not response or "error" in response:
                print(f"⚠️ [Trading] MT5 bridge error: {response.get('error', 'Unknown error')}")
                return {"error": "Failed to fetch market data from MT5", "status": "error"}
            
            # Parse bridge response
            candles_raw = response.get("rates", [])
            if not candles_raw:
                return {"error": "No candles returned from MT5", "status": "error"}
            
            # Convert raw MT5 candles to our format
            candles = []
            for candle in candles_raw:
                candles.append({
                    "time": candle.get("time") or candle.get("datetime"),
                    "open": float(candle.get("open", 0)),
                    "high": float(candle.get("high", 0)),
                    "low": float(candle.get("low", 0)),
                    "close": float(candle.get("close", 0)),
                    "tick_volume": int(candle.get("tick_volume", 0))
                })
            
            # Calculate technical indicators
            df = pd.DataFrame(candles)
            if df.empty:
                return {"error": "Empty candles dataframe", "status": "error"}
            
            df = calculate_all_indicators(df)
            latest = df.iloc[-1] if not df.empty else None
            
            # Extract indicator values
            indicators = {
                "ema_fast": float(latest.get(f"EMA_{config.TRADING_EMA_FAST}", 0)) if latest is not None else 0,
                "ema_slow": float(latest.get(f"EMA_{config.TRADING_EMA_SLOW}", 0)) if latest is not None else 0,
                "rsi": float(latest.get(f"RSI_{config.TRADING_RSI_PERIOD}", 0)) if latest is not None else 0,
                "atr": float(latest.get(f"ATR_{config.TRADING_ATR_PERIOD}", 0)) if latest is not None else 0,
                "bb_upper": float(latest.get(f"BBU_{config.TRADING_BBANDS_PERIOD}_2.0", 0)) if latest is not None else 0,
                "bb_lower": float(latest.get(f"BBL_{config.TRADING_BBANDS_PERIOD}_2.0", 0)) if latest is not None else 0,
            } if latest is not None else {}
            
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": candles,
                "latest_candle": candles[-1] if candles else {},
                "indicators": indicators,
                "status": "success"
            }
            
        except Exception as e:
            print(f"❌ [Trading] Market data fetch failed: {e}")
            return {"error": f"Exception: {str(e)}", "status": "error"}


market = MarketData()
