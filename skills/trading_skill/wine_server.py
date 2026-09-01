from __future__ import annotations

import importlib
import json
import os
import socket
import time
import sys
from threading import RLock
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

_MT5_SESSION_LOCK = RLock()

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
    """Ensure the process-global MetaTrader5 session is on the requested mode.

    MT5's Python binding is process-global: one Python process cannot hold a
    demo and real terminal session simultaneously. We therefore verify the
    currently attached account first, cleanly shut it down when the requested
    mode differs, initialize the requested environment, and verify the result.
    The public bridge operations are serialized with _MT5_SESSION_LOCK so an
    old/background request cannot switch the session mid-operation.
    """
    requested = _mode(mode)
    prefix = "ANGELIQUE_MT5_LIVE" if requested == "live" else "ANGELIQUE_MT5_DEMO"
    values = {name: os.getenv(f"{prefix}_{name}") for name in ("PATH", "LOGIN", "PASSWORD", "SERVER")}

    try:
        current = mt5.account_info()
    except Exception:
        current = None

    if current is not None:
        current_raw = _raw(current)
        current_mode = _account_mode(current_raw)
        if current_mode == requested:
            return True
        # The attached terminal is the wrong environment. Do not let the
        # caller accidentally use it for the requested mode.
        try:
            mt5.shutdown()
        except Exception:
            pass

    path = values.get("PATH")
    if path:
        path = path.replace("\\\\", "\\")

    initialized = False
    if path:
        try:
            initialized = bool(mt5.initialize(path=path))
        except (TypeError, RuntimeError):
            initialized = False

    if not initialized:
        options: dict[str, Any] = {name.lower(): value for name, value in values.items() if value}
        if "login" in options:
            try:
                options["login"] = int(options["login"])
            except (TypeError, ValueError):
                return False
        try:
            initialized = bool(mt5.initialize(**options)) if options else bool(mt5.initialize())
        except TypeError:
            initialized = bool(mt5.initialize())
        except Exception:
            initialized = False

    if not initialized:
        return False

    try:
        info = mt5.account_info()
        if info is None:
            return False
        actual = _account_mode(_raw(info))
        if actual != requested:
            try:
                mt5.shutdown()
            except Exception:
                pass
            return False
        return True
    except Exception:
        return False


def _connect_error(mt5: Any, mode: str) -> str:
    prefix = "ANGELIQUE_MT5_LIVE" if mode == "live" else "ANGELIQUE_MT5_DEMO"
    configured = any(os.getenv(f"{prefix}_{name}") for name in ("PATH", "LOGIN", "PASSWORD", "SERVER"))
    detail = "MT5.initialize() returned false"
    try:
        last_error = mt5.last_error()
        if last_error:
            detail = f"MT5.initialize() failed: {last_error}"
    except Exception:
        pass
    if not configured:
        detail += f"; configure {prefix}_PATH or start the Valetax MT5 terminal first"
    return detail


def _mt5_session_locked(fn):
    """Serialize the entire bridge operation, not merely initialization."""
    def wrapped(request: dict[str, Any]) -> dict[str, Any]:
        with _MT5_SESSION_LOCK:
            return fn(request)
    wrapped.__name__ = getattr(fn, "__name__", "wrapped")
    return wrapped


def _expected_broker_matches(expected: str | None, raw: dict[str, Any]) -> bool:
    if not expected:
        return True
    expected_key = str(expected).strip().upper()
    identity = " ".join(str(raw.get(field) or "") for field in ("company", "server")).upper()
    if expected_key == "VALETAX":
        return "VALETAX" in identity
    return False

def _broker_guard_error(mt5: Any, expected_broker: str | None) -> str | None:
    if not expected_broker:
        return None
    try:
        info = mt5.account_info()
        raw = _raw(info) if info is not None else {}
        if not _expected_broker_matches(expected_broker, raw):
            actual = raw.get("company") or raw.get("server") or "unknown broker"
            return f"Broker mismatch: expected {expected_broker}, connected to {actual}."
    except Exception as exc:
        return f"Broker identity check failed: {exc}"
    return None


def _account_guard_error(mt5: Any, requested_mode: str, expected_broker: str | None = None) -> str | None:
    broker_error = _broker_guard_error(mt5, expected_broker)
    if broker_error:
        return broker_error
    try:
        info = mt5.account_info()
        if info is None:
            return "Account identity check failed: no MT5 account is logged in."
        actual_mode = _account_mode(_raw(info))
        if actual_mode != requested_mode:
            return f"Requested {requested_mode} account mode but MT5 is connected to {actual_mode} account"
    except Exception as exc:
        return f"Account identity check failed: {exc}"
    return None

def _account_mode(raw: dict[str, Any]) -> str:
    # MT5's ACCOUNT_TRADE_MODE constants: DEMO=0, CONTEST=1, REAL=2.
    # Only an explicit REAL (2) account is ever treated as live; demo (0),
    # contest (1), and anything unrecognized default to demo. Getting this
    # backwards (treating trade_mode==1 as demo) misclassifies real demo
    # accounts as "live", which fails the requested-vs-actual mode check
    # on every single call and silently kills the pipeline before any
    # market analysis ever runs.
    trade_mode = raw.get("trade_mode")
    if trade_mode in (0, 1, 2):
        return "live" if trade_mode == 2 else "demo"
    server = str(raw.get("server") or "").lower()
    if any(word in server for word in ("demo", "trial", "test", "sandbox")):
        return "demo"
    if any(word in server for word in ("live", "real")):
        return "live"
    return "demo"


def _period_loss_percent(mt5: Any, equity: float, days: int) -> float | None:
    """Calculate realized trading loss against the period opening balance.

    Balance/deposit/withdrawal operations and entry deals are excluded. The
    denominator is reconstructed from current balance minus the period's net
    realized trading result, preventing the limit from moving merely because
    the current equity has changed.
    """
    if equity <= 0 or not hasattr(mt5, "history_deals_get"):
        return None
    try:
        now=datetime.now(timezone.utc); start=now-timedelta(days=days)
        deals=mt5.history_deals_get(start,now) or []
        buy=getattr(mt5,"DEAL_TYPE_BUY",None); sell=getattr(mt5,"DEAL_TYPE_SELL",None)
        out=getattr(mt5,"DEAL_ENTRY_OUT",None); out_by=getattr(mt5,"DEAL_ENTRY_OUT_BY",None)
        net=0.0
        for deal in deals:
            deal_type=getattr(deal,"type",None); deal_entry=getattr(deal,"entry",None)
            if buy is not None and sell is not None and deal_type not in {buy,sell}: continue
            if out is not None and out_by is not None and deal_entry not in {out,out_by}: continue
            net += float(getattr(deal,"profit",0) or 0)+float(getattr(deal,"commission",0) or 0)+float(getattr(deal,"swap",0) or 0)
        info=mt5.account_info(); balance=float(getattr(info,"balance",0) or 0) if info is not None else equity
        opening=max(0.0,balance-net)
        return max(0.0,-net/opening*100) if opening>0 else 0.0
    except Exception:
        return None

def _choose_filling_mode(mt5: Any, symbol_info: Any) -> int:
    """Choose a filling policy supported by the symbol, without retrying a sent order."""
    flags=int(getattr(symbol_info,"filling_mode",0) or 0)
    fok_flag=int(getattr(mt5,"SYMBOL_FILLING_FOK",1))
    ioc_flag=int(getattr(mt5,"SYMBOL_FILLING_IOC",2))
    order_fok=getattr(mt5,"ORDER_FILLING_FOK",0)
    order_ioc=getattr(mt5,"ORDER_FILLING_IOC",1)
    order_return=getattr(mt5,"ORDER_FILLING_RETURN",2)
    trade_exemode=getattr(symbol_info,"trade_exemode",None)
    market_execution=getattr(mt5,"SYMBOL_TRADE_EXECUTION_MARKET",2)
    if trade_exemode == market_execution:
        if flags & ioc_flag: return order_ioc
        if flags & fok_flag: return order_fok
        return order_ioc
    if flags & ioc_flag: return order_ioc
    if flags & fok_flag: return order_fok
    return order_return


@_mt5_session_locked
def account(request: dict[str, Any]) -> dict[str, Any]:
    expected_broker = str(request.get("expected_broker") or "").upper() or None
    requested = _mode(request.get("account_mode"))
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested):
            return {"status": "error", "mode": requested, "mode_match": False, "login": None, "error": _connect_error(mt5, requested)}
        broker_error = _broker_guard_error(mt5, expected_broker)
        if broker_error:
            return {"status": "error", "mode": requested, "mode_match": False, "login": None, "error": broker_error}
        info = mt5.account_info()
        if info is None:
            return {"status": "unavailable", "mode": requested, "mode_match": False, "login": None, "error": "No MT5 account is logged in"}
        raw = _raw(info)
        actual = _account_mode(raw)
        used_margin = float(raw.get("margin", 0) or 0)
        equity = float(raw.get("equity", 0) or 0)
        margin_level = float(raw.get("margin_level", 0) or 0)
        daily_loss = _period_loss_percent(mt5, equity, 1)
        weekly_loss = _period_loss_percent(mt5, equity, 7)
        if daily_loss is None or weekly_loss is None:
            return {
                "status": "error",
                "mode": requested,
                "mode_match": False,
                "login": raw.get("login"),
                "error": "MT5 realized-loss history is unavailable; trading is blocked until daily/weekly loss metrics can be verified.",
            }
        if margin_level <= 0 and used_margin > 0:
            margin_level = equity / used_margin * 100
        result = {"status": "connected", "mode": actual, "requested_mode": requested, "mode_match": actual == requested, "login": raw.get("login"), "balance": float(raw.get("balance", 0) or 0), "equity": equity, "used_margin": used_margin, "margin": used_margin, "free_margin": float(raw.get("margin_free", 0) or 0), "margin_level": margin_level, "leverage": int(raw.get("leverage", 0) or 0), "currency": raw.get("currency", "USD"), "broker": raw.get("company", raw.get("server", "")), "platform": "MT5", "daily_loss_percent": daily_loss, "weekly_loss_percent": weekly_loss}
        if actual != requested:
            result["error"] = f"MT5 is connected to {actual}; requested {requested}."
        return result
    except Exception as exc:
        return {"status": "error", "mode": requested, "mode_match": False, "login": None, "error": str(exc)}


@_mt5_session_locked
def symbols(request: dict[str, Any]) -> dict[str, Any]:
    expected_broker = str(request.get("expected_broker") or "").upper() or None
    requested = _mode(request.get("account_mode"))
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested):
            return {"status": "error", "symbols": [], "error": _connect_error(mt5, requested)}
        broker_error = _broker_guard_error(mt5, expected_broker)
        if broker_error:
            return {"status": "error", "symbols": [], "error": broker_error}
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


@_mt5_session_locked
def market(request: dict[str, Any]) -> dict[str, Any]:
    expected_broker = str(request.get("expected_broker") or "").upper() or None
    requested_mode = _mode(request.get("account_mode"))
    requested_symbol = str(request.get("symbol") or "")
    timeframes = tuple(str(item).upper() for item in request.get("timeframes", ("H4", "H1", "M15", "M5")))
    count = min(max(int(request.get("count", 200)), 50), 1000)
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"status": "error", "error": _connect_error(mt5, requested_mode), "timeframes": {}}
        broker_error = _broker_guard_error(mt5, expected_broker)
        if broker_error:
            return {"status": "error", "error": broker_error, "timeframes": {}}
        symbol = _resolve(mt5, str(requested_symbol))
        account_info = mt5.account_info()
        if account_info is not None:
            actual_mode = _account_mode(_raw(account_info))
            if actual_mode != requested_mode:
                return {"status": "error", "error": f"Requested {requested_mode} account mode but MT5 is connected to {actual_mode} account", "timeframes": {}}
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
            # MT5 bar index 0 is the current/forming candle. Trading analysis
            # must use completed candles only, so request from position 1.
            if hasattr(mt5, "copy_rates_from_pos"):
                rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 1, count)
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
        point = float(info.get("point", 0) or 0)
        digits = int(info.get("digits", 0) or 0)
        # Compute spread in pips when tick_size is available. Pip definition:
        # - For most FX pairs a pip = 0.0001 (4th decimal) but brokers may use
        #   fractional pricing; use tick_size to normalize.
        spread_pips = None
        try:
            from core.price_units import pip_size_from_specs
            if tick_size:
                pip_unit = pip_size_from_specs(symbol, {"point": point, "digits": digits})
                spread_pips = raw_spread / pip_unit if pip_unit > 0 else None
        except Exception:
            spread_pips = None

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
            "symbol_specs": _symbol_specs_payload(info, margin_per_volume=margin_per_volume),
            "spread_pips": spread_pips,
            "analysis_uses_closed_candles_only": True,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "timeframes": {}}


@_mt5_session_locked
def execute(request: dict[str, Any]) -> dict[str, Any]:
    expected_broker=str(request.get("expected_broker") or "").upper() or None
    requested_mode=_mode(request.get("account_mode")); order=request.get("order") or {}
    try:
        mt5=importlib.import_module("MetaTrader5")
        if not _connect(mt5,requested_mode): return {"success":False,"error":_connect_error(mt5,requested_mode)}
        broker_error=_broker_guard_error(mt5,expected_broker)
        if broker_error: return {"success":False,"error":broker_error}
        # Fail closed before symbol resolution or order submission when MT5
        # explicitly disables trading. This check must happen early so a
        # disabled terminal cannot generate repeated, pointless attempts.
        terminal = mt5.terminal_info() if hasattr(mt5, "terminal_info") else None
        if terminal is not None and hasattr(terminal, "trade_allowed") and not bool(getattr(terminal, "trade_allowed")):
            return {"success":False,"failure_stage":"trading_disabled","error":"MT5 terminal trading is disabled. Enable AutoTrading in the terminal before execution."}
        account_info = mt5.account_info()
        if account_info is not None and hasattr(account_info, "trade_allowed") and not bool(getattr(account_info, "trade_allowed")):
            return {"success":False,"failure_stage":"trading_disabled","error":"MT5 account trading is disabled."}

        symbol=str(order.get("mt5_symbol") or order.get("symbol") or "").strip()
        resolved=_resolve(mt5,symbol)
        if not resolved or resolved != symbol: return {"success":False,"error":"The plan symbol is no longer available in MT5."}
        direction=str(order.get("direction","" )).upper()
        if direction not in {"BUY", "SELL"}: return {"success":False,"error":"Invalid direction."}
        info=mt5.symbol_info(symbol); tick=mt5.symbol_info_tick(symbol)
        if info is None or tick is None: return {"success":False,"error":"MT5 symbol information/tick is unavailable."}
        if hasattr(info, "trade_mode") and int(getattr(info, "trade_mode") or 0) == int(getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", 0)):
            return {"success":False,"failure_stage":"symbol_trading_disabled","error":f"Trading is disabled for MT5 symbol {symbol}."}
        digits=int(getattr(info,"digits",5) or 5)
        price=float(getattr(tick,"ask",0) if direction=="BUY" else getattr(tick,"bid",0))
        if price<=0: return {"success":False,"error":"Current executable price is unavailable."}
        volume=float(order.get("volume",0) or 0)
        sl=float(order.get("stop_loss",0) or 0); tp=float(order.get("take_profit",0) or 0)
        if volume<=0 or sl<=0 or tp<=0: return {"success":False,"error":"Volume, stop loss and take profit must be positive."}
        comment=str(order.get("comment") or f"Angelique:{order.get('plan_id','')}")[:31]
        request_data={"action":mt5.TRADE_ACTION_DEAL,"symbol":symbol,"volume":volume,"type":action,"price":round(price,digits),"sl":round(sl,digits),"tp":round(tp,digits),"deviation":int(order.get("deviation",20) or 20),"type_time":getattr(mt5,"ORDER_TIME_GTC",0),"type_filling":_choose_filling_mode(mt5,info),"comment":comment}
        if hasattr(mt5,"order_check"):
            checked=mt5.order_check(request_data); raw_check=_raw(checked) if checked is not None else {}
            check_code=getattr(checked,"retcode",None) if checked is not None else None
            if checked is None or (check_code is not None and check_code not in {0,getattr(mt5,"TRADE_RETCODE_DONE",10009)}):
                return {"success":False,"failure_stage":"order_check","retcode":check_code,"error":raw_check.get("comment") or "MT5 order_check rejected the request.","order_check":raw_check}
        result=mt5.order_send(request_data); raw=_raw(result) if result is not None else {}
        retcode=getattr(result,"retcode",None) if result is not None else None
        accepted_codes={getattr(mt5,"TRADE_RETCODE_DONE",10009),getattr(mt5,"TRADE_RETCODE_PLACED",10008),getattr(mt5,"TRADE_RETCODE_DONE_PARTIAL",10010)}
        if result is None or retcode not in accepted_codes:
            return {"success":False,"failure_stage":"mt5_order_send","retcode":retcode,"order":raw.get("order"),"deal":raw.get("deal"),"error":raw.get("comment") or "MT5 rejected the order."}
        # Never resend after an accepted order. Reconciliation is read-only and may be delayed by MT5.
        deal_ticket=raw.get("deal"); order_ticket=raw.get("order")
        verified=False; verification="accepted_no_position_readback"
        try:
            positions=mt5.positions_get(symbol=symbol) or []
            expected_ticket=raw.get("position")
            for pos in positions:
                same_ticket=expected_ticket and int(getattr(pos,"ticket",0) or 0)==int(expected_ticket)
                same_comment=str(getattr(pos,"comment","") or "") == comment
                same_side=getattr(pos,"type",None)==getattr(mt5,"POSITION_TYPE_BUY",0 if direction=="BUY" else -1) if direction=="BUY" else getattr(pos,"type",None)==getattr(mt5,"POSITION_TYPE_SELL",1)
                same_volume=abs(float(getattr(pos,"volume",0) or 0)-volume)<=max(1e-9,volume*1e-8)
                if same_ticket or (same_comment and same_side and same_volume): verified=True; verification="position_verified"; break
        except Exception:
            pass
        return {"success":True,"accepted":True,"retcode":retcode,"order":order_ticket,"deal":deal_ticket,"position_verified":verified,"verification":verification,"requested_price":round(price,digits),"fill_mode":request_data["type_filling"],"error":None}
    except Exception as exc:
        return {"success":False,"failure_stage":"bridge_exception","error":str(exc)}


@_mt5_session_locked
def positions(request: dict[str, Any]) -> dict[str, Any]:
    expected_broker=str(request.get("expected_broker") or "").upper() or None
    requested_mode=_mode(request.get("account_mode")); symbol=str(request.get("symbol") or "").strip()
    try:
        mt5=importlib.import_module("MetaTrader5")
        if not _connect(mt5,requested_mode): return {"status":"error","error":_connect_error(mt5,requested_mode),"positions":[]}
        guard=_account_guard_error(mt5,requested_mode,expected_broker)
        if guard: return {"status":"error","error":guard,"positions":[]}
        positions=(mt5.positions_get(symbol=_resolve(mt5,symbol) or symbol) if symbol else mt5.positions_get()) or []
        info=mt5.account_info(); equity=float(getattr(info,"equity",0) or 0) if info else 0.0
        rows=[]
        for pos in positions:
            sym=str(getattr(pos,"symbol","") or ""); ptype="BUY" if getattr(pos,"type",None)==getattr(mt5,"POSITION_TYPE_BUY",0) else "SELL"
            volume=float(getattr(pos,"volume",0) or 0); entry=float(getattr(pos,"price_open",0) or 0); sl=float(getattr(pos,"sl",0) or 0)
            risk_amount=None; risk_percent=None
            if sl>0 and entry>0 and volume>0 and hasattr(mt5, "order_calc_profit"):
                order_type = getattr(mt5, "ORDER_TYPE_BUY") if ptype == "BUY" else getattr(mt5, "ORDER_TYPE_SELL")
                try:
                    calc = mt5.order_calc_profit(order_type, sym, volume, entry, sl)
                    if calc is not None:
                        risk_amount=abs(float(calc))
                except Exception:
                    risk_amount=None
            if risk_amount is None:
                sinfo=mt5.symbol_info(sym)
                ts=float(getattr(sinfo,"trade_tick_size",0) or 0) if sinfo else 0.0; tv=float(getattr(sinfo,"trade_tick_value",0) or 0) if sinfo else 0.0
                if sl>0 and entry>0 and volume>0 and ts>0 and tv>0:
                    risk_amount=abs(entry-sl)/ts*tv*volume
            if equity>0 and risk_amount is not None:
                risk_percent=risk_amount/equity*100
            opened_ts=getattr(pos, "time", None)
            rows.append({"ticket":int(getattr(pos,"ticket",0) or 0),"identifier":int(getattr(pos,"identifier",0) or 0),"symbol":sym,"type":ptype,"volume":volume,"price_open":entry,"sl":sl,"tp":float(getattr(pos,"tp",0) or 0),"profit":float(getattr(pos,"profit",0) or 0),"risk_amount":risk_amount,"risk_percent":risk_percent,"comment":str(getattr(pos,"comment","") or ""),"magic":int(getattr(pos,"magic",0) or 0),"opened_at":opened_ts,"time_open":opened_ts})
        return {"status":"connected","positions":rows}
    except Exception as exc:
        return {"status":"error","error":str(exc),"positions":[]}


@_mt5_session_locked
def recent_deals(request: dict[str, Any]) -> dict[str, Any]:
    expected_broker = str(request.get("expected_broker") or "").upper() or None
    requested_mode = _mode(request.get("account_mode"))
    minutes = max(1, int(request.get("minutes", 60)))
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"status": "error", "deals": [], "error": "MT5 initialization failed"}
        guard_error = _account_guard_error(mt5, requested_mode, expected_broker)
        if guard_error:
            return {"status": "error", "deals": [], "error": guard_error}
        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now - timedelta(minutes=minutes), now) or []
        return {"status": "connected", "deals": [_raw(deal) for deal in deals]}
    except Exception as exc:
        return {"status": "error", "deals": [], "error": str(exc)}


@_mt5_session_locked
def calculate_profit(request: dict[str, Any]) -> dict[str, Any]:
    expected_broker = str(request.get("expected_broker") or "").upper() or None
    requested_mode = _mode(request.get("account_mode"))
    symbol = str(request.get("symbol") or "").strip()
    direction = str(request.get("direction") or "BUY").upper()
    volume = float(request.get("volume", 0) or 0)
    price_open = float(request.get("price_open", 0) or 0)
    price_close = float(request.get("price_close", 0) or 0)
    if not symbol or volume <= 0 or price_open <= 0 or price_close <= 0:
        return {"status": "error", "error": "symbol, volume, price_open and price_close are required."}
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"status": "error", "error": "MT5 initialization failed"}
        guard_error = _account_guard_error(mt5, requested_mode, expected_broker)
        if guard_error:
            return {"status": "error", "error": guard_error}
        resolved = _resolve(mt5, symbol) or symbol
        order_type = getattr(mt5, "ORDER_TYPE_BUY") if direction == "BUY" else getattr(mt5, "ORDER_TYPE_SELL")
        value = mt5.order_calc_profit(order_type, resolved, volume, price_open, price_close)
        if value is None:
            return {"status": "error", "error": "MT5 order_calc_profit returned no value."}
        return {"status": "connected", "profit": float(value), "symbol": resolved, "direction": direction, "volume": volume, "price_open": price_open, "price_close": price_close}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


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


@_mt5_session_locked
def close_position(request: dict[str, Any]) -> dict[str, Any]:
    expected_broker = str(request.get("expected_broker") or "").upper() or None
    requested_mode = _mode(request.get("account_mode"))
    symbol = str(request.get("symbol") or "").strip()
    requested_ticket = request.get("ticket")

    def _normalize(value: str) -> str:
        return "".join(char for char in value.upper() if char.isalnum())

    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"success": False, "status": "error", "error": "MT5 initialization failed"}
        guard_error = _account_guard_error(mt5, requested_mode, expected_broker)
        if guard_error:
            return {"success": False, "status": "error", "error": guard_error}

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
            "type_filling": _choose_filling_mode(mt5, mt5.symbol_info(position.symbol)),
            "comment": "Angelique manual exit"
        }
        result = mt5.order_send(close_request)
        raw = _raw(result) if result is not None else {}
        success = result is not None and getattr(result, "retcode", None) in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
        if not success:
            return {"success": False, "status": "error", "symbol": position.symbol, "ticket": int(position.ticket), "message": raw.get("comment", "MT5 rejected the manual exit."), "error": raw.get("comment", "MT5 rejected the manual exit.")}
        deadline = time.monotonic() + config.TRADING_POSITION_CLOSE_VERIFY_SECONDS
        while time.monotonic() < deadline:
            remaining = mt5.positions_get(ticket=int(position.ticket)) or []
            if not remaining:
                return {"success": True, "status": "closed", "symbol": position.symbol, "ticket": int(position.ticket), "message": "Position close confirmed by MT5.", "retcode": getattr(result, "retcode", None)}
            time.sleep(config.TRADING_POSITION_CLOSE_VERIFY_INTERVAL)
        return {"success": True, "status": "verification_pending", "symbol": position.symbol, "ticket": int(position.ticket), "message": "Close request accepted; position closure verification is still pending.", "retcode": getattr(result, "retcode", None)}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": str(exc)}


@_mt5_session_locked
def modify_position(request: dict[str, Any]) -> dict[str, Any]:
    expected_broker = str(request.get("expected_broker") or "").upper() or None
    """Move a position's stop loss (and optionally take profit) without
    closing it. This is how break-even and trailing-stop management
    actually take effect on the broker side, instead of only being
    calculated and never applied."""
    requested_mode = _mode(request.get("account_mode"))
    symbol = str(request.get("symbol") or "").strip()
    ticket = request.get("ticket")

    def _normalize(value: str) -> str:
        return "".join(char for char in value.upper() if char.isalnum())

    try:
        ticket = int(ticket)
    except (TypeError, ValueError):
        return {"success": False, "status": "error", "error": "Position ticket must be an integer."}

    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"success": False, "status": "error", "error": "MT5 initialization failed"}
        guard_error = _account_guard_error(mt5, requested_mode, expected_broker)
        if guard_error:
            return {"success": False, "status": "error", "error": guard_error}

        positions = mt5.positions_get(ticket=ticket) or []
        if not positions and symbol:
            resolved_symbol = _resolve(mt5, symbol) or symbol
            candidates = mt5.positions_get(symbol=resolved_symbol) or []
            if not candidates:
                all_positions = mt5.positions_get() or []
                normalized_target = _normalize(symbol)
                candidates = [pos for pos in all_positions if _normalize(str(getattr(pos, "symbol", ""))) == normalized_target]
            positions = [pos for pos in candidates if int(getattr(pos, "ticket", 0)) == ticket]
        if not positions:
            return {"success": False, "status": "error", "error": f"Position ticket {ticket} was not found."}

        position = positions[0]
        stop_loss = request.get("stop_loss")
        take_profit = request.get("take_profit")
        modify_request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": position.symbol,
            "position": int(position.ticket),
            "sl": float(stop_loss) if stop_loss is not None else float(getattr(position, "sl", 0) or 0),
            "tp": float(take_profit) if take_profit is not None else float(getattr(position, "tp", 0) or 0),
        }
        result = mt5.order_send(modify_request)
        raw = _raw(result) if result is not None else {}
        success = result is not None and getattr(result, "retcode", None) in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
        if not success:
            return {"success": False, "status": "error", "symbol": position.symbol, "ticket": int(position.ticket), "sl": modify_request["sl"], "tp": modify_request["tp"], "message": raw.get("comment", "MT5 rejected the stop update."), "error": raw.get("comment", "MT5 rejected the stop update.")}
        current = mt5.positions_get(ticket=int(position.ticket)) or []
        if current:
            updated = current[0]
            sl_ok = abs(float(getattr(updated, "sl", 0) or 0) - modify_request["sl"]) <= max(float(getattr(mt5.symbol_info(position.symbol), "point", 0) or 0) * 2, 1e-9)
            tp_ok = take_profit is None or abs(float(getattr(updated, "tp", 0) or 0) - modify_request["tp"]) <= max(float(getattr(mt5.symbol_info(position.symbol), "point", 0) or 0) * 2, 1e-9)
            if sl_ok and tp_ok:
                return {"success": True, "status": "modified", "symbol": position.symbol, "ticket": int(position.ticket), "sl": modify_request["sl"], "tp": modify_request["tp"], "message": "Position stop update confirmed by MT5."}
        return {"success": True, "status": "verification_pending", "symbol": position.symbol, "ticket": int(position.ticket), "sl": modify_request["sl"], "tp": modify_request["tp"], "message": "Stop update accepted; readback verification is pending."}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": str(exc)}


def _close_single_position(mt5: Any, position: Any) -> dict[str, Any]:
    closing_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
    close_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": float(position.volume),
        "type": closing_type,
        "position": int(position.ticket),
        "deviation": 20,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _choose_filling_mode(mt5, mt5.symbol_info(str(getattr(position, "symbol", "")))),
        "comment": "Angelique emergency exit",
    }
    result = mt5.order_send(close_request)
    raw = _raw(result) if result is not None else {}
    success = result is not None and getattr(result, "retcode", None) in {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED}
    if not success:
        return {"success": False, "status": "error", "symbol": position.symbol, "ticket": int(position.ticket), "error": raw.get("comment", "MT5 rejected the exit.")}
    deadline = time.monotonic() + config.TRADING_POSITION_CLOSE_VERIFY_SECONDS
    while time.monotonic() < deadline:
        if not (mt5.positions_get(ticket=int(position.ticket)) or []):
            return {"success": True, "status": "closed", "symbol": position.symbol, "ticket": int(position.ticket), "error": None}
        time.sleep(config.TRADING_POSITION_CLOSE_VERIFY_INTERVAL)
    return {"success": True, "status": "verification_pending", "symbol": position.symbol, "ticket": int(position.ticket), "error": None}


@_mt5_session_locked
def close_all_positions(request: dict[str, Any]) -> dict[str, Any]:
    expected_broker = str(request.get("expected_broker") or "").upper() or None
    """Flatten every open position on the account. Used by the daily-loss
    kill switch and by manual 'stop trading now' requests. Best-effort:
    keeps closing remaining positions even if one fails, and reports
    every individual result so nothing fails silently."""
    requested_mode = _mode(request.get("account_mode"))
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"success": False, "status": "error", "error": "MT5 initialization failed", "closed": [], "failed": []}
        guard_error = _account_guard_error(mt5, requested_mode, expected_broker)
        if guard_error:
            return {"success": False, "status": "error", "error": guard_error, "closed": [], "failed": []}
        open_positions = mt5.positions_get() or []
        if not open_positions:
            return {"success": True, "status": "no_positions", "closed": [], "failed": []}
        closed, pending, failed = [], [], []
        for position in open_positions:
            outcome = _close_single_position(mt5, position)
            if not outcome["success"]:
                failed.append(outcome)
            elif outcome.get("status") == "verification_pending":
                pending.append(outcome)
            else:
                closed.append(outcome)
        if pending and not failed:
            status = "pending_verification"
        elif failed:
            status = "partial"
        else:
            status = "flattened"
        return {"success": not failed and not pending, "status": status, "closed": closed, "verification_pending": pending, "failed": failed}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "closed": [], "failed": []}



# --------------------------------------------------------------------------
# Symbol specification payload
# --------------------------------------------------------------------------
#: Every MT5 symbol property the trading engine needs. Instrument
#: classification, pip semantics, volume normalisation, stops/freeze validation
#: and margin all depend on these, so they are returned as one complete object
#: rather than the partial subset the bridge used to send.
_SPEC_FIELDS = (
    "point", "digits", "spread", "spread_float",
    "trade_tick_size", "trade_tick_value", "trade_tick_value_profit", "trade_tick_value_loss",
    "trade_contract_size", "trade_calc_mode", "trade_mode", "trade_exemode",
    "trade_stops_level", "trade_freeze_level",
    "volume_min", "volume_max", "volume_step", "volume_limit",
    "currency_base", "currency_profit", "currency_margin",
    "margin_initial", "margin_maintenance", "margin_hedged",
    "filling_mode", "order_mode", "expiration_mode",
    "swap_long", "swap_short", "swap_mode", "swap_rollover3days",
    "session_deals", "session_buy_orders", "session_sell_orders",
    "path", "description", "visible", "select", "category", "exchange",
)


def _symbol_specs_payload(info: dict[str, Any], margin_per_volume: Any = None) -> dict[str, Any]:
    """Return the complete broker specification for a symbol."""
    payload: dict[str, Any] = {field: info.get(field) for field in _SPEC_FIELDS}
    # Aliases kept for existing consumers.
    payload.update({
        "tick_size": info.get("trade_tick_size"),
        "tick_value": info.get("trade_tick_value"),
        "tick_value_profit": info.get("trade_tick_value_profit"),
        "tick_value_loss": info.get("trade_tick_value_loss"),
        "contract_size": info.get("trade_contract_size"),
        "stops_level": info.get("trade_stops_level"),
        "freeze_level": info.get("trade_freeze_level"),
        "commission_per_lot": info.get("commission_per_lot", info.get("trade_commission")),
        "margin_per_volume": margin_per_volume,
    })
    return payload


@_mt5_session_locked
def symbol_specs(request: dict[str, Any]) -> dict[str, Any]:
    """READ-ONLY full symbol specification. Never sends an order."""
    expected_broker = str(request.get("expected_broker") or "").upper() or None
    requested_mode = _mode(request.get("account_mode"))
    requested = request.get("symbols") or ([request.get("symbol")] if request.get("symbol") else [])
    requested = [str(item).strip() for item in requested if str(item or "").strip()]
    if not requested:
        return {"status": "error", "error": "At least one symbol is required."}
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"status": "error", "error": "MT5 initialization failed"}
        guard_error = _account_guard_error(mt5, requested_mode, expected_broker)
        if guard_error:
            return {"status": "error", "error": guard_error}
        account_info = mt5.account_info()
        out: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for name in requested:
            resolved = _resolve(mt5, name)
            if not resolved:
                errors[name] = "Symbol could not be resolved on this broker."
                continue
            if not mt5.symbol_select(resolved, True):
                errors[name] = "symbol_select failed; the symbol is not available in Market Watch."
                continue
            info = mt5.symbol_info(resolved)
            if info is None:
                errors[name] = "symbol_info returned None."
                continue
            data = info._asdict() if hasattr(info, "_asdict") else dict(info)
            tick = mt5.symbol_info_tick(resolved)
            tick_data = (tick._asdict() if hasattr(tick, "_asdict") else dict(tick)) if tick else {}
            margin_per_volume = None
            try:
                probe = float(data.get("volume_min") or 0.01)
                reference = float(tick_data.get("ask") or tick_data.get("bid") or 0)
                if reference > 0:
                    value = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, resolved, probe, reference)
                    if value is not None and probe > 0:
                        margin_per_volume = float(value) / probe
            except Exception:
                margin_per_volume = None
            out[name] = {
                "mt5_symbol": resolved,
                "specs": _symbol_specs_payload(data, margin_per_volume=margin_per_volume),
                "tick": {"bid": tick_data.get("bid"), "ask": tick_data.get("ask"),
                         "last": tick_data.get("last"), "time": tick_data.get("time")},
            }
        return {
            "status": "connected",
            "symbols": out,
            "errors": errors,
            "account_currency": getattr(account_info, "currency", None),
            "account_leverage": getattr(account_info, "leverage", None),
            "margin_mode": getattr(account_info, "margin_mode", None),
            "read_only": True,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@_mt5_session_locked
def calculate_margin(request: dict[str, Any]) -> dict[str, Any]:
    """Broker-authoritative margin via MT5 order_calc_margin."""
    expected_broker = str(request.get("expected_broker") or "").upper() or None
    requested_mode = _mode(request.get("account_mode"))
    symbol = str(request.get("symbol") or "").strip()
    direction = str(request.get("direction") or "BUY").upper()
    volume = float(request.get("volume", 0) or 0)
    price = float(request.get("price", 0) or 0)
    if not symbol or volume <= 0 or price <= 0:
        return {"status": "error", "error": "symbol, volume and price are required."}
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"status": "error", "error": "MT5 initialization failed"}
        guard_error = _account_guard_error(mt5, requested_mode, expected_broker)
        if guard_error:
            return {"status": "error", "error": guard_error}
        resolved = _resolve(mt5, symbol) or symbol
        # order_calc_margin fails on symbols that are not selected.
        mt5.symbol_select(resolved, True)
        order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
        value = mt5.order_calc_margin(order_type, resolved, volume, price)
        if value is None:
            error = mt5.last_error() if hasattr(mt5, "last_error") else None
            return {"status": "error",
                    "error": f"MT5 order_calc_margin returned no value ({error})."}
        account_info = mt5.account_info()
        return {
            "status": "connected", "margin": float(value), "symbol": resolved,
            "direction": direction, "volume": volume, "price": price,
            "account_currency": getattr(account_info, "currency", None),
            "free_margin": getattr(account_info, "margin_free", None),
            "margin_level": getattr(account_info, "margin_level", None),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@_mt5_session_locked
def order_preflight(request: dict[str, Any]) -> dict[str, Any]:
    """Broker-side OrderCheck. Validates an order WITHOUT sending it."""
    expected_broker = str(request.get("expected_broker") or "").upper() or None
    requested_mode = _mode(request.get("account_mode"))
    symbol = str(request.get("symbol") or "").strip()
    direction = str(request.get("direction") or "BUY").upper()
    volume = float(request.get("volume", 0) or 0)
    price = float(request.get("price", 0) or 0)
    stop_loss = float(request.get("stop_loss", 0) or 0)
    take_profit = float(request.get("take_profit", 0) or 0)
    if not symbol or volume <= 0:
        return {"status": "error", "error": "symbol and a positive volume are required."}
    try:
        mt5 = importlib.import_module("MetaTrader5")
        if not _connect(mt5, requested_mode):
            return {"status": "error", "error": "MT5 initialization failed"}
        guard_error = _account_guard_error(mt5, requested_mode, expected_broker)
        if guard_error:
            return {"status": "error", "error": guard_error}
        resolved = _resolve(mt5, symbol) or symbol
        mt5.symbol_select(resolved, True)
        info = mt5.symbol_info(resolved)
        tick = mt5.symbol_info_tick(resolved)
        if info is None or tick is None:
            return {"status": "error", "error": f"No live quote available for {resolved}."}
        if price <= 0:
            price = float(tick.ask if direction == "BUY" else tick.bid)

        filling = getattr(mt5, "ORDER_FILLING_FOK")
        modes = int(getattr(info, "filling_mode", 0) or 0)
        if modes & 2:
            filling = getattr(mt5, "ORDER_FILLING_IOC")
        elif modes & 1:
            filling = getattr(mt5, "ORDER_FILLING_FOK")

        order_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": resolved,
            "volume": volume,
            "type": mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": price,
            "deviation": int(request.get("deviation", 20) or 20),
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        }
        if stop_loss > 0:
            order_request["sl"] = stop_loss
        if take_profit > 0:
            order_request["tp"] = take_profit

        result = mt5.order_check(order_request)
        if result is None:
            error = mt5.last_error() if hasattr(mt5, "last_error") else None
            return {"status": "error", "error": f"MT5 order_check returned no result ({error})."}
        data = result._asdict() if hasattr(result, "_asdict") else dict(result)
        data.pop("request", None)
        return {
            "status": "connected",
            "retcode": int(data.get("retcode", -1)),
            "comment": data.get("comment"),
            "balance": data.get("balance"), "equity": data.get("equity"),
            "profit": data.get("profit"), "margin": data.get("margin"),
            "margin_free": data.get("margin_free"), "margin_level": data.get("margin_level"),
            "symbol": resolved, "direction": direction, "volume": volume,
            "price": price, "stop_loss": stop_loss or None, "take_profit": take_profit or None,
            "order_sent": False,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


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
                "close_all_positions": "close_all_positions",
                "modify_position": "modify_position",
                "recent_deals": "recent_deals",
                "get_symbol_specs": "symbol_specs",
                "order_check": "order_preflight",
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
        elif operation == "modify_position":
            result = modify_position(payload)
        elif operation == "close_all_positions":
            result = close_all_positions(payload)
        elif operation == "recent_deals":
            result = recent_deals(payload)
        elif operation == "calculate_profit":
            result = calculate_profit(payload)
        elif operation == "calculate_margin":
            result = calculate_margin(payload)
        elif operation == "symbol_specs":
            result = symbol_specs(payload)
        elif operation == "order_preflight":
            result = order_preflight(payload)
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
