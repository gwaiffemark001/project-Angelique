from __future__ import annotations

import importlib
import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
for path_entry in [SCRIPT_DIR, ""]:
    while path_entry in sys.path:
        sys.path.remove(path_entry)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import asyncio
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
    # Keep the bridge's internal vocabulary aligned with MT5's detected mode.
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


def _period_loss_percent(mt5: Any, equity: float, days: int) -> float:
    if equity <= 0 or not hasattr(mt5, "history_deals_get"):
        return 0.0
    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days)
        deals = mt5.history_deals_get(start, now) or []
        net = sum(
            float(getattr(deal, field, 0) or 0)
            for deal in deals
            for field in ("profit", "commission", "swap")
        )
        return max(0.0, -net / equity * 100)
    except Exception:
        return 0.0


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
        result = {"status": "connected", "mode": actual, "requested_mode": requested, "mode_match": actual == requested, "login": raw.get("login"), "balance": float(raw.get("balance", 0) or 0), "equity": equity, "used_margin": used_margin, "margin": used_margin, "free_margin": float(raw.get("margin_free", 0) or 0), "margin_level": margin_level, "leverage": int(raw.get("leverage", 0) or 0), "currency": raw.get("currency", "USD"), "daily_loss_percent": _period_loss_percent(mt5, equity, 1), "weekly_loss_percent": _period_loss_percent(mt5, equity, 7)}
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
            # Use position zero to request the newest bars. copy_rates_from()
            # with a timestamp in the past returns bars up to that timestamp,
            # which made the chart lag by one complete request window.
            if hasattr(mt5, "copy_rates_from_pos"):
                rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, count)
            else:
                rates = mt5.copy_rates_from(symbol, mt5_timeframe, datetime.now(timezone.utc), count)
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
        raw_spread = ask - bid
        tick_size = info.get("trade_tick_size")
        tick_value = info.get("trade_tick_value")
        # Compute spread in pips when tick_size is available. Pip definition:
        # - For most FX pairs a pip = 0.0001 (4th decimal) but brokers may use
        #   fractional pricing; use tick_size to normalize.
        spread_pips = None
        try:
            if tick_size:
                tick = float(tick_size)
                # pips = raw_spread / pip_size, where pip_size is tick * (10 if tick has extra precision)
                # A robust approach: pip_size = 10**(-int(round(abs(math.log10(tick)))))? Avoid math; use ratio to 0.0001/0.01 for JPY.
                # Simpler: define a pip reference for common pairs: if tick < 0.001 -> pip_unit = 0.0001 else 0.01
                pip_unit = 0.0001 if float(tick) < 0.001 else 0.01
                spread_pips = raw_spread / pip_unit
        except Exception:
            spread_pips = None

        point = float(info.get("point", 0) or 0)
        digits = int(info.get("digits", 0) or 0)
        spread_points = raw_spread / point if point > 0 else None
        return {
            "status": "connected",
            "requested_symbol": requested_symbol,
            "mt5_symbol": symbol,
            "timeframes": candles,
            "bid": bid,
            "ask": ask,
            "spread": raw_spread,
            "spread_price": raw_spread,
            "spread_points": spread_points,
            "symbol_specs": {
                "tick_size": info.get("trade_tick_size"),
                "tick_value": info.get("trade_tick_value"),
                "volume_min": info.get("volume_min"),
                "volume_max": info.get("volume_max"),
                "volume_step": info.get("volume_step"),
                "margin_per_volume": margin_per_volume,
                "point": point,
                "digits": digits,
                "swap_long": info.get("swap_long"),
                "swap_short": info.get("swap_short"),
                "swap_mode": info.get("swap_mode"),
                "trade_stops_level": info.get("trade_stops_level"),
                "trade_freeze_level": info.get("trade_freeze_level"),
                "trade_mode": info.get("trade_mode"),
            },
            "spread_pips": spread_pips,
        }
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


def positions(request: dict[str, Any]) -> dict[str, Any]:
    requested_mode = _mode(request.get("account_mode"))
    symbol = str(request.get("symbol") or "").strip()
    requested_ticket = request.get("ticket")

    def _normalize(value: str) -> str:
        return "".join(char for char in value.upper() if char.isalnum())

    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"status": "error", "error": "MT5 initialization failed", "positions": []}

        if symbol:
            resolved_symbol = _resolve(mt5, symbol) or symbol
            positions_result = mt5.positions_get(symbol=resolved_symbol) or []
            if not positions_result:
                all_positions = mt5.positions_get() or []
                normalized_target = _normalize(symbol)
                positions_result = [pos for pos in all_positions if _normalize(str(getattr(pos, "symbol", ""))) == normalized_target]
        else:
            positions_result = mt5.positions_get() or []

        return {
            "status": "connected",
            "positions": [
                {
                    "ticket": int(getattr(pos, "ticket", 0)),
                    "symbol": str(getattr(pos, "symbol", "")),
                    "type": "BUY" if getattr(pos, "type", None) == mt5.POSITION_TYPE_BUY else "SELL",
                    "volume": float(getattr(pos, "volume", 0) or 0),
                    "price_open": float(getattr(pos, "price_open", 0) or 0),
                    "sl": float(getattr(pos, "sl", 0) or 0),
                    "tp": float(getattr(pos, "tp", 0) or 0),
                    "profit": float(getattr(pos, "profit", 0) or 0),
                    "expected_profit": _expected_position_profit(mt5, pos),
                }
                for pos in positions_result
            ],
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "positions": []}


def _expected_position_profit(mt5: Any, position: Any) -> float | None:
    """Estimate money earned at TP using the broker's symbol tick specification."""
    take_profit = float(getattr(position, "tp", 0) or 0)
    entry = float(getattr(position, "price_open", 0) or 0)
    volume = float(getattr(position, "volume", 0) or 0)
    if not take_profit or not entry or not volume:
        return None
    info = mt5.symbol_info(str(getattr(position, "symbol", "")))
    tick_size = float(getattr(info, "trade_tick_size", 0) or 0) if info else 0
    tick_value = float(getattr(info, "trade_tick_value", 0) or 0) if info else 0
    if tick_size <= 0 or tick_value <= 0:
        return None
    return round(abs(take_profit - entry) / tick_size * tick_value * volume, 2)


def close_position(request: dict[str, Any]) -> dict[str, Any]:
    requested_mode = _mode(request.get("account_mode"))
    symbol = str(request.get("symbol") or "").strip()

    def _normalize(value: str) -> str:
        return "".join(char for char in value.upper() if char.isalnum())

    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"success": False, "status": "error", "error": "MT5 initialization failed"}

        positions = []
        if symbol:
            resolved_symbol = _resolve(mt5, symbol) or symbol
            positions = mt5.positions_get(symbol=resolved_symbol) or []
            if not positions:
                all_positions = mt5.positions_get() or []
                normalized_target = _normalize(symbol)
                positions = [pos for pos in all_positions if _normalize(str(getattr(pos, "symbol", ""))) == normalized_target]
        else:
            positions = mt5.positions_get() or []

        if not positions:
            return {"success": False, "status": "error", "error": f"No open position found for {symbol or 'current account'}"}

        if requested_ticket is not None:
            try:
                requested_ticket = int(requested_ticket)
            except (TypeError, ValueError):
                return {"success": False, "status": "error", "error": "Position ticket must be an integer."}
            positions = [position for position in positions if int(getattr(position, "ticket", 0)) == requested_ticket]
            if not positions:
                return {"success": False, "status": "error", "error": f"Position ticket {requested_ticket} was not found."}

        position = positions[0]
        closing_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
        close_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": float(position.volume),
            "type": closing_type,
            "position": int(position.ticket),
            "deviation": 20,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "comment": "Angelique manual exit"
        }
        result = mt5.order_send(close_request)
        raw = _raw(result) if result is not None else {}
        success = result is not None and getattr(result, "retcode", None) in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
        return {
            "success": success,
            "status": "closed" if success else "error",
            "symbol": position.symbol,
            "ticket": int(position.ticket),
            "message": "Position closed successfully." if success else raw.get("comment", "MT5 rejected the manual exit."),
            "error": None if success else raw.get("comment", "MT5 rejected the manual exit."),
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": str(exc)}


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
                "get_positions": "positions",
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
        elif operation == "positions":
            result = positions(payload)
        elif operation == "close_position":
            result = close_position(payload)
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
