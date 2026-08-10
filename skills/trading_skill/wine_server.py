from __future__ import annotations

import asyncio
import importlib
import json
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any

from core import config

TIMEFRAMES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
    "W1": 10080,
    "MN": 43200,
}


def _mode(value: str | None) -> str:
    return "live" if str(value or "demo").lower() in {"live", "real"} else "demo"


def _raw(value: Any) -> dict[str, Any]:
    dtype = getattr(value, "dtype", None)
    field_names = getattr(dtype, "names", None)
    if field_names:
        result = {}
        for name in field_names:
            field_value = value[name]
            result[name] = field_value.item() if hasattr(field_value, "item") else field_value
        return result
    if hasattr(value, "_asdict"):
        return value._asdict()
    return {key: getattr(value, key) for key in dir(value) if not key.startswith("_")}


def _connect(mt5: Any, mode: str) -> bool:
    prefix = "ANGELIQUE_MT5_LIVE" if mode == "live" else "ANGELIQUE_MT5_DEMO"
    values = {name: os.getenv(f"{prefix}_{name}") for name in ("PATH", "LOGIN", "PASSWORD", "SERVER")}
    options: dict[str, Any] = {name.lower(): value for name, value in values.items() if value}
    if "login" in options:
        options["login"] = int(options["login"])
    try:
        return bool(mt5.initialize(**options)) if options else bool(mt5.initialize())
    except TypeError:
        return bool(mt5.initialize())


def _account_mode(raw: dict[str, Any]) -> str:
    server = str(raw.get("server") or "").lower()
    if any(word in server for word in ("demo", "trial", "test", "sandbox")):
        return "demo"
    return "demo" if raw.get("trade_mode") == 1 else "live"


def account(request: dict[str, Any]) -> dict[str, Any]:
    requested = _mode(request.get("account_mode"))
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested):
            return {"status": "error", "mode": requested, "mode_match": False, "login": None, "error": "MT5 initialization failed"}
        info = mt5.account_info()
        if info is None:
            return {"status": "unavailable", "mode": requested, "mode_match": False, "login": None, "error": "No MT5 account is logged in"}
        raw = _raw(info)
        actual = _account_mode(raw)
        used_margin = float(raw.get("margin", 0) or 0)
        equity = float(raw.get("equity", 0) or 0)
        margin_level = float(raw.get("margin_level", 0) or 0)
        if margin_level <= 0 and used_margin > 0:
            margin_level = equity / used_margin * 100
        result = {"status": "connected", "mode": actual, "requested_mode": requested, "mode_match": actual == requested, "login": raw.get("login"), "balance": float(raw.get("balance", 0) or 0), "equity": equity, "used_margin": used_margin, "margin": used_margin, "free_margin": float(raw.get("margin_free", 0) or 0), "margin_level": margin_level, "leverage": int(raw.get("leverage", 0) or 0), "currency": raw.get("currency", "USD")}
        if actual != requested:
            result["error"] = f"MT5 is connected to {actual}; requested {requested}."
        return result
    except Exception as exc:
        return {"status": "error", "mode": requested, "mode_match": False, "login": None, "error": str(exc)}


def symbols(request: dict[str, Any]) -> dict[str, Any]:
    requested = _mode(request.get("account_mode"))
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested):
            return {"status": "error", "symbols": [], "error": "MT5 initialization failed"}
        return {"status": "connected", "symbols": sorted({str(item.name) for item in (mt5.symbols_get() or []) if getattr(item, "name", None)})}
    except Exception as exc:
        return {"status": "error", "symbols": [], "error": str(exc)}


def _resolve(mt5: Any, requested: str) -> str | None:
    names = [str(item.name) for item in (mt5.symbols_get() or []) if getattr(item, "name", None)]
    key = "".join(char for char in str(requested).upper() if char.isalnum())
    exact = [name for name in names if "".join(char for char in name.upper() if char.isalnum()) == key]
    if exact:
        return exact[0]
    matches = [name for name in names if "".join(char for char in name.upper() if char.isalnum()).startswith(key)]
    return sorted(matches, key=lambda name: (len(name), name))[0] if matches else None


def market(request: dict[str, Any]) -> dict[str, Any]:
    requested_mode = _mode(request.get("account_mode"))
    requested_symbol = str(request.get("symbol") or "")
    timeframes = tuple(str(item).upper() for item in request.get("timeframes", ("H4", "H1", "M15", "M5")))
    count = min(max(int(request.get("count", 200)), 50), 1000)
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"status": "error", "error": "MT5 initialization failed", "timeframes": {}}
        symbol = _resolve(mt5, str(requested_symbol))
        if not symbol:
            return {"status": "error", "error": f"Symbol {requested_symbol} is unavailable", "timeframes": {}, "suggestions": symbols(request).get("symbols", [])[:10]}
        if not mt5.symbol_select(symbol, True):
            return {"status": "error", "error": f"MT5 could not select {symbol}", "timeframes": {}}
        info = _raw(mt5.symbol_info(symbol))
        tick = _raw(mt5.symbol_info_tick(symbol))
        candles: dict[str, list[dict[str, Any]]] = {}
        for timeframe in timeframes:
            if timeframe not in TIMEFRAMES:
                return {"status": "error", "error": f"Unsupported timeframe {timeframe}", "timeframes": {}}
            mt5_timeframe = getattr(mt5, f"TIMEFRAME_{timeframe}")
            start = datetime.now(timezone.utc) - timedelta(minutes=TIMEFRAMES[timeframe] * count)
            rates = mt5.copy_rates_from(symbol, mt5_timeframe, start, count)
            rate_rows = rates if rates is not None else []
            candles[timeframe] = [{"time": row.get("time"), "open": float(row.get("open", 0)), "high": float(row.get("high", 0)), "low": float(row.get("low", 0)), "close": float(row.get("close", 0)), "tick_volume": int(row.get("tick_volume", 0))} for row in (_raw(rate) for rate in rate_rows)]
        ask = float(tick.get("ask", 0) or 0)
        bid = float(tick.get("bid", 0) or 0)
        margin_per_volume = 0.0
        if hasattr(mt5, "order_calc_margin"):
            margin_value = mt5.order_calc_margin(getattr(mt5, "ORDER_TYPE_BUY"), symbol, 1.0, ask)
            margin_per_volume = float(margin_value or 0)
        if margin_per_volume <= 0:
            account_info = _raw(mt5.account_info())
            leverage = float(account_info.get("leverage", 0) or 0)
            contract_size = float(info.get("trade_contract_size", 0) or 0)
            if leverage > 0 and contract_size > 0 and ask > 0:
                margin_per_volume = contract_size * ask / leverage
        return {"status": "connected", "requested_symbol": requested_symbol, "mt5_symbol": symbol, "timeframes": candles, "bid": bid, "ask": ask, "spread": ask - bid, "symbol_specs": {"tick_size": info.get("trade_tick_size"), "tick_value": info.get("trade_tick_value"), "volume_min": info.get("volume_min"), "volume_max": info.get("volume_max"), "volume_step": info.get("volume_step"), "margin_per_volume": margin_per_volume}}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "timeframes": {}}


def execute(request: dict[str, Any]) -> dict[str, Any]:
    requested_mode = _mode(request.get("account_mode"))
    order = request.get("order") or {}
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"success": False, "error": "MT5 initialization failed"}
        symbol = _resolve(mt5, str(order.get("mt5_symbol") or ""))
        if not symbol or symbol != order.get("mt5_symbol"):
            return {"success": False, "error": "The plan symbol is no longer available in MT5."}
        direction = str(order.get("direction", "")).upper()
        action = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL if direction == "SELL" else None
        if action is None:
            return {"success": False, "error": "Invalid direction"}
        request_data = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(order["volume"]), "type": action, "price": float(order["entry"]), "sl": float(order["stop_loss"]), "tp": float(order["take_profit"]), "deviation": 20, "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC, "comment": "Angelique approved plan"}
        result = mt5.order_send(request_data)
        raw = _raw(result) if result is not None else {}
        success = result is not None and getattr(result, "retcode", None) in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
        return {"success": success, "retcode": raw.get("retcode"), "order": raw.get("order"), "deal": raw.get("deal"), "error": None if success else raw.get("comment", "MT5 rejected the order")}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def handle(websocket, path=None):
    async for message in websocket:
        payload = json.loads(message)
        operation = payload.get("operation")
        if not operation:
            operation = {
                "ping": "ping",
                "get_account_info": "account",
                "list_instruments": "symbols",
                "get_symbols": "symbols",
                "get_rates": "market",
                "place_order": "execute",
            }.get(payload.get("action"))
        if operation == "ping":
            await websocket.send(json.dumps({"status": "pong"}))
            continue
        if operation == "account":
            result = account(payload)
        elif operation == "symbols":
            result = symbols(payload)
        elif operation == "market":
            result = market(payload)
        elif operation == "execute":
            result = execute(payload)
        else:
            result = {"status": "error", "error": f"Unknown operation: {operation}"}
        await websocket.send(json.dumps(result))


async def main():
    import websockets
    inherited_fd = os.getenv(config.MT5_BRIDGE_FD_ENV)
    if inherited_fd:
        sock = socket.fromfd(int(inherited_fd), socket.AF_INET, socket.SOCK_STREAM)
        async with websockets.serve(handle, sock=sock):
            await asyncio.Future()
    else:
        async with websockets.serve(handle, config.MT5_BRIDGE_HOST, config.MT5_BRIDGE_PORT):
            await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
