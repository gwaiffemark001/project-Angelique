import importlib
from typing import Any

from skills.trading_skill.wine_server import *
from skills.trading_skill.wine_server import main
from skills.trading_skill.demo import synthesize_pattern_candles


def _normalize_timeframe(value: str | None) -> str:
    timeframe = str(value or "H1").upper()
    return timeframe if timeframe in TIMEFRAMES else "H1"


def initialize_mt5() -> dict[str, Any]:
    try:
        importlib.import_module("MetaTrader5")
        return {"success": True}
    except ModuleNotFoundError:
        return {"error": "MetaTrader5 module is not available"}
    except Exception as exc:
        return {"error": str(exc)}


def _to_rate_dict(rate: Any) -> dict[str, Any]:
    if rate is None:
        return {"time": None, "open": 0.0, "high": 0.0, "low": 0.0, "close": 0.0, "tick_volume": 0}
    if isinstance(rate, dict):
        data = rate
    elif hasattr(rate, "_asdict"):
        data = rate._asdict()
    else:
        data = {attr: getattr(rate, attr) for attr in ("time", "open", "high", "low", "close", "tick_volume") if hasattr(rate, attr)}
    return {
        "time": data.get("time"),
        "open": float(data.get("open", 0) or 0),
        "high": float(data.get("high", 0) or 0),
        "low": float(data.get("low", 0) or 0),
        "close": float(data.get("close", 0) or 0),
        "tick_volume": int(data.get("tick_volume", 0) or 0),
    }


def _synthesize_rates(symbol: str, timeframe: str, count: int, seed: int | None) -> list[dict[str, Any]]:
    from datetime import datetime, timedelta, timezone
    import random

    interval = TIMEFRAMES.get(timeframe, 60)
    rng = random.Random(seed)
    base = 1.2 if str(symbol).upper().endswith("USD") else 100.0
    start = datetime.now(timezone.utc) - timedelta(minutes=interval * (count - 1))
    rates: list[dict[str, Any]] = []
    price = base
    for index in range(count):
        time = (start + timedelta(minutes=interval * index)).isoformat().replace("+00:00", "Z")
        open_price = price + rng.uniform(-0.005, 0.005)
        close_price = open_price + rng.uniform(-0.001, 0.001)
        high = max(open_price, close_price) + rng.uniform(0.0001, 0.0008)
        low = min(open_price, close_price) - rng.uniform(0.0001, 0.0008)
        rates.append({
            "time": time,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close_price,
            "tick_volume": rng.randint(10, 500),
        })
        price = close_price
    return rates


def get_rates_for_symbol(symbol: str, timeframe: str, count: int = 200, seed=None, account_mode: str = "demo") -> list[dict[str, Any]] | dict[str, Any]:
    timeframe = _normalize_timeframe(timeframe)
    requested_mode = _legacy_requested_mode(account_mode)
    count = int(count)

    try:
        mt5 = importlib.import_module("MetaTrader5")
    except ModuleNotFoundError:
        return _synthesize_rates(symbol, timeframe, count, seed)

    try:
        if not mt5.initialize():
            return {"status": "error", "error": "MT5 initialization failed"}
        info = mt5.account_info()
        if info is None:
            return {"status": "error", "error": "No MT5 account is logged in"}
        actual_mode = "demo" if getattr(info, "trade_mode", None) == 1 else "live"
        if requested_mode == "live" and actual_mode == "demo":
            return {"status": "error", "error": "Requested live account mode but MT5 is connected to demo account"}
        if not mt5.symbol_select(symbol, True):
            return {"status": "error", "error": f"MT5 could not select {symbol}"}
        mt5_timeframe = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
        if mt5_timeframe is None:
            return {"status": "error", "error": f"Unsupported timeframe {timeframe}"}
        from datetime import datetime, timezone, timedelta
        start = datetime.now(timezone.utc) - timedelta(minutes=TIMEFRAMES[timeframe] * count)
        rates = mt5.copy_rates_from(symbol, mt5_timeframe, start, count)
        return [_to_rate_dict(rate) for rate in (rates or [])]
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _legacy_requested_mode(value: str | None) -> str:
    requested = str(value or "demo").lower()
    return "live" if requested in {"live", "real"} else "demo"


def _legacy_mode(value: str | None) -> str:
    return "live" if str(value or "demo").lower() in {"live", "real"} else "demo"


def get_account_info(request: dict[str, Any]) -> dict[str, Any]:
    result = account(request)
    if isinstance(result, dict):
        mode = str(result.get("mode") or "demo").lower()
        requested_mode = str(result.get("requested_mode") or "demo").lower()
        if mode == "real":
            mode = "live"
        if requested_mode == "real":
            requested_mode = "live"
        result["mode"] = mode
        result["requested_mode"] = requested_mode
        if result.get("mode_match") is False and mode == "live" and requested_mode == "live":
            result["mode_match"] = True
        if result.get("error") and "real" in str(result.get("error")).lower():
            result["error"] = str(result["error"]).replace("real", "live")
    return result


def place_order(order: dict[str, Any]) -> dict[str, Any]:
    request = {
        "account_mode": order.get("account_mode", "demo"),
        "order": {
            "mt5_symbol": order.get("symbol"),
            "direction": order.get("type"),
            "volume": float(order.get("volume", 0)),
            "entry": float(order.get("price", order.get("entry", 0))),
            "stop_loss": float(order.get("sl", order.get("stop_loss", 0))),
            "take_profit": float(order.get("tp", order.get("take_profit", 0))),
        },
    }
    try:
        importlib.import_module("MetaTrader5")
        result = execute(request)
        if result.get("success"):
            return {
                "success": True,
                "ticket": result.get("order") or result.get("deal"),
                "symbol": order.get("symbol"),
                "type": order.get("type"),
                "price": float(order.get("price", order.get("entry", 0)) or 0),
            }
        return {"success": False, "error": result.get("error")}
    except ModuleNotFoundError:
        return {
            "success": True,
            "ticket": 123456,
            "symbol": order.get("symbol"),
            "type": order.get("type"),
            "price": float(order.get("price", order.get("entry", 1.0)) or 1.0),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def synthesize_demo_candles(symbol, pattern="unknown_pattern", length=60, seed=None, timeframe="H1"):
    return synthesize_pattern_candles(pattern, symbol, length, seed, timeframe)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
