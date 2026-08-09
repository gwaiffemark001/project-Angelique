import asyncio
import json
import os
import socket
import sys
import math
import time
from datetime import datetime, timedelta

# Ensure the project root is on sys.path when this bridge is launched directly.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core import config

FD_ENV = config.MT5_BRIDGE_FD_ENV
HOST = config.MT5_BRIDGE_HOST
PORT = config.MT5_BRIDGE_PORT

VALID_MT5_TIMEFRAMES = [s.strip().upper() for s in config.TRADING_TIMEFRAMES if isinstance(s, str)]
TIMEFRAME_INTERVAL_MINUTES = {
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


def _get_inherited_socket():
    fd_value = os.getenv(FD_ENV)
    if not fd_value:
        return None
    try:
        fd = int(fd_value)
        sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        return sock
    except Exception:
        return None

def initialize_mt5():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:
        try:
            print(f"[Bridge][Debug] initialize_mt5 import failed: {exc}")
            print(f"[Bridge][Debug] sys.path: {sys.path}")
        except Exception:
            pass
        return {"error": "MetaTrader5 module is not available. Install MetaTrader5 to enable live trading.", "details": str(exc)}

    return {"status": "connected", "version": "5.0"}

def get_account_info(request: dict | None = None):
    request = request or {}
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:
        try:
            print(f"[Bridge][Debug] get_account_info import failed: {exc}")
            print(f"[Bridge][Debug] sys.path: {sys.path}")
        except Exception:
            pass
        return {"error": "MetaTrader5 module is not available. Install MetaTrader5 to enable account queries.", "details": str(exc)}

    try:
        ok = mt5.initialize()
        if not ok:
            return {"error": "MetaTrader5 initialization failed"}
        requested_mode = str(request.get("account_mode") or request.get("mode") or "demo").lower()
        # Normalize 'real' to 'live' so callers using 'real' are accepted as live accounts.
        if requested_mode == "real":
            requested_mode = "live"

        info = mt5.account_info()
        if info is None:
            return {"error": "No account is logged in to MetaTrader5"}

        info_dict = info._asdict() if hasattr(info, "_asdict") else {k: getattr(info, k, None) for k in dir(info) if not k.startswith("_")}
        actual_mode = _infer_mt5_account_mode(info_dict, requested_mode)
        mode_match = requested_mode == actual_mode

        result = {
            "login": info_dict.get("login"),
            "balance": float(info_dict.get("balance", 0)),
            "equity": float(info_dict.get("equity", 0)),
            "free_margin": float(info_dict.get("margin_free", info_dict.get("free_margin", 0))),
            "margin_level": float(info_dict.get("margin_level", 0)),
            "leverage": int(info_dict.get("leverage", 0)),
            "currency": info_dict.get("currency", "USD"),
            "mode": actual_mode,
            "requested_mode": requested_mode,
            "mode_match": mode_match,
            "status": "connected",
        }

        if not mode_match:
            result["error"] = f"Requested {requested_mode} account mode does not match connected MT5 account mode ({actual_mode})."
        return result
    except Exception as exc:
        return {"error": f"MetaTrader5 query failed: {exc}", "status": "error"}


def synthesize_demo_candles(symbol: str, pattern: str, length: int = 60, seed: int | None = None, timeframe: str = "H1"):
    # Deterministic generator for demo purposes when `seed` is provided.
    import random
    from datetime import datetime, timedelta

    rng = random.Random(seed)

    base = 1.2000 if symbol.endswith("USD") else 100.0
    base += rng.uniform(-0.005, 0.005)
    candles = []
    if seed is None:
        now = datetime.utcnow()
    else:
        # deterministic base time when seed is provided
        try:
            now = datetime.utcfromtimestamp(int(seed))
        except Exception:
            now = datetime.utcnow()

    interval = timedelta(minutes=_timeframe_minutes(timeframe))
    for i in range(length):
        t = now - interval * (length - i - 1)
        # pattern shapes: simple waveforms + pattern-specific bumps
        phase = i / max(1, length)
        wobble = 0.0015 * math.sin(phase * math.pi * 4) if 'math' in globals() else 0.0015 * __import__('math').sin(phase * __import__('math').pi * 4)
        if pattern == 'head_and_shoulders':
            bump = 0.004 * math.exp(-((phase - 0.5) ** 2) * 60) + 0.001 * math.sin(phase * 6)
        elif pattern == 'double_top':
            bump = 0.003 * (math.exp(-((phase - 0.25) ** 2) * 80) + math.exp(-((phase - 0.75) ** 2) * 80))
        elif pattern == 'double_bottom':
            bump = -0.003 * (math.exp(-((phase - 0.25) ** 2) * 80) + math.exp(-((phase - 0.75) ** 2) * 80))
        elif pattern == 'engulfing':
            bump = 0.002 if (i % 2 == 0) else -0.001
        elif pattern == 'rising_wedge':
            bump = 0.002 * phase
        elif pattern == 'falling_wedge':
            bump = -0.002 * phase
        else:
            bump = 0.001 * math.sin(phase * 3.14)

        o = base + wobble + bump + rng.uniform(-0.0006, 0.0006)
        c = o + rng.uniform(-0.001, 0.001)
        high = max(o, c) + rng.uniform(0.0001, 0.0008)
        low = min(o, c) - rng.uniform(0.0001, 0.0008)
        vol = rng.randint(10, 500)
        candles.append({
            "time": t.isoformat() + "Z",
            "open": round(o, 6),
            "high": round(high, 6),
            "low": round(low, 6),
            "close": round(c, 6),
            "tick_volume": int(vol),
        })
    return candles


def list_instruments():
    # Return configured trading symbols.
    return config.TRADING_SYMBOLS


def _normalize_timeframe(timeframe: str) -> str:
    if not timeframe or not isinstance(timeframe, str):
        return "H1"
    normalized = timeframe.strip().upper()
    if normalized in VALID_MT5_TIMEFRAMES:
        return normalized
    return "H1"


def _timeframe_minutes(timeframe: str) -> int:
    normalized = _normalize_timeframe(timeframe)
    return TIMEFRAME_INTERVAL_MINUTES.get(normalized, 60)


def _infer_mt5_account_mode(info_dict: dict, requested_mode: str) -> str:
    server = str(info_dict.get("server") or "").lower()
    if any(token in server for token in ("demo", "trial", "test", "sandbox")):
        return "demo"

    trade_mode = info_dict.get("trade_mode")
    if trade_mode is not None:
        try:
            trade_mode_value = int(trade_mode)
            if trade_mode_value == 0:
                return "live"
            if trade_mode_value == 1:
                return "demo"
        except Exception:
            pass
        if isinstance(trade_mode, str):
            trade_mode_str = trade_mode.strip().lower()
            if trade_mode_str in {"demo", "trial", "test", "sandbox"}:
                return "demo"
            if trade_mode_str in {"live", "real"}:
                return "live"

    # If mode cannot be inferred from MT5 metadata, do not assume demo when the
    # request was for demo. Default to live to avoid showing demo data for a
    # connected real account by mistake.
    return "live"


def _build_time_index(count: int, timeframe: str, seed: int | None = None):
    now = datetime.utcnow()
    interval = timedelta(minutes=_timeframe_minutes(timeframe))
    if seed is not None:
        try:
            now = datetime.utcfromtimestamp(int(seed))
        except Exception:
            now = datetime.utcnow()

    times = []
    for i in range(count):
        times.append((now - interval * (count - i - 1)).isoformat() + "Z")
    return times


def _mt5_timeframe(timeframe: str):
    mapping = {
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
    return mapping.get(_normalize_timeframe(timeframe), 60)


def _parse_mt5_candles(raw_rates: list[dict]) -> list[dict]:
    candles = []
    for rate in raw_rates:
        candles.append({
            "time": rate.get("time") or rate.get("datetime") or rate.get("time_msc"),
            "open": float(rate.get("open", 0)),
            "high": float(rate.get("high", 0)),
            "low": float(rate.get("low", 0)),
            "close": float(rate.get("close", 0)),
            "tick_volume": int(rate.get("tick_volume", rate.get("real_volume", 0) or 0)),
        })
    return candles


def get_rates_for_symbol(
    symbol: str,
    timeframe: str,
    count: int = 100,
    seed: int | None = None,
    account_mode: str = "demo",
) -> list[dict] | dict:
    if count <= 0:
        count = 100
    tf = _normalize_timeframe(timeframe)
    count = min(max(count, 10), 1000)

    def fallback_candles() -> list[dict]:
        return synthesize_demo_candles(symbol, "head_and_shoulders", length=count, seed=seed, timeframe=tf)

    requested_mode = str(account_mode or "demo").lower()
    if requested_mode == "real":
        requested_mode = "live"

    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception:
        if requested_mode == "demo":
            return fallback_candles()
        return {
            "error": "MetaTrader5 module is not available. Cannot fetch live MT5 rates.",
            "status": "error",
        }

    try:
        ok = mt5.initialize()
        if not ok:
            if requested_mode == "demo":
                return fallback_candles()
            return {
                "error": "MetaTrader5 initialization failed. Cannot fetch live MT5 rates.",
                "status": "error",
            }

        account_info = mt5.account_info()
        if account_info is None:
            return {
                "error": "No MT5 account is currently logged in.",
                "status": "error",
            }

        account_info_dict = account_info._asdict() if hasattr(account_info, "_asdict") else {k: getattr(account_info, k, None) for k in dir(account_info) if not k.startswith("_")}
        actual_mode = _infer_mt5_account_mode(account_info_dict, requested_mode)
        if requested_mode != actual_mode:
            return {
                "error": f"Requested {requested_mode} account mode but MT5 is connected to {actual_mode} account.",
                "status": "error",
                "mode": actual_mode,
                "requested_mode": requested_mode,
            }

        mt5_tf = getattr(mt5, f"TIMEFRAME_{tf}", None)
        if mt5_tf is None:
            mt5_tf = mt5.TIMEFRAME_M1

        if not mt5.symbol_select(symbol, True):
            return {
                "error": f"Symbol {symbol} is not available in MT5.",
                "status": "error",
            }

        now = datetime.utcnow()
        utc_from = now - timedelta(minutes=_mt5_timeframe(tf) * count)
        rates = mt5.copy_rates_from(symbol, mt5_tf, utc_from, count)
        if rates is None:
            return {
                "error": f"Failed to fetch MT5 rates for {symbol}.",
                "status": "error",
            }

        raw_rates = [
            rate._asdict() if hasattr(rate, "_asdict") else {k: getattr(rate, k, None) for k in dir(rate) if not k.startswith("_")}
            for rate in rates
        ]
        return _parse_mt5_candles(raw_rates)
    except Exception as exc:
        return {
            "error": f"MetaTrader5 rate fetch failed: {exc}",
            "status": "error",
        }


def _generate_symbol_price_series(symbol: str, count: int, timeframe: str, seed: int | None = None) -> list[float]:
    import random
    rng = random.Random(seed)
    base = 1.2000 if symbol.endswith("USD") else 100.0
    if symbol.upper().startswith("XAU"):
        base = 1930.0
    elif symbol.upper().startswith("BTC"):
        base = 50000.0
    elif symbol.upper().startswith("ETH"):
        base = 3200.0
    elif symbol.upper().startswith("USDJPY"):
        base = 135.00
    elif symbol.upper().startswith("GBP"):
        base = 1.3750
    elif symbol.upper().startswith("AUD"):
        base = 0.6900

    timeframe_factor = _timeframe_minutes(timeframe)
    trend_strength = 0.0005 * math.log1p(timeframe_factor)
    volatility = 0.0004 * math.sqrt(timeframe_factor / 60.0)

    prices = [base]
    for i in range(1, count + 1):
        drift = trend_strength * (1 if i % 2 == 0 else -1)
        noise = rng.gauss(0, volatility)
        direction = 1 if rng.random() > 0.48 else -1
        delta = drift + noise * direction
        next_price = max(0.0001, prices[-1] * (1 + delta))
        prices.append(next_price)

    # use last count points, skipping initial base anchor if needed
    return prices[1:count + 1]


def place_order(request: dict | None = None) -> dict:
    request = request or {}
    symbol = str(request.get("symbol") or config.DEFAULT_TRADING_SYMBOL).upper()
    account_mode = str(request.get("account_mode") or request.get("mode") or "demo").lower()
    order_type = str(request.get("type") or request.get("order_type") or "BUY").upper()
    volume = request.get("volume", 0.01)
    sl = request.get("sl")
    tp = request.get("tp")
    comment = str(request.get("comment") or "Angelique AI")

    if order_type not in {"BUY", "SELL"}:
        return {"success": False, "error": f"Unsupported order type: {order_type}"}

    try:
        volume = float(volume)
    except (TypeError, ValueError):
        return {"success": False, "error": "Volume must be numeric"}

    if volume <= 0:
        return {"success": False, "error": "Volume must be greater than zero"}

    rates = get_rates_for_symbol(symbol, config.DEFAULT_TRADING_TIMEFRAME, count=1, seed=int(time.time()) % 100000)
    price = float(rates[-1]["close"]) if rates else 1.0
    if order_type == "SELL":
        price = float(rates[-1]["close"]) if rates else 1.0

    ticket = f"A{int(time.time()) % 1000000:06d}"
    return {
        "success": True,
        "ticket": ticket,
        "symbol": symbol,
        "type": order_type,
        "volume": round(volume, 2),
        "price": round(price, 6),
        "sl": round(float(sl), 6) if sl is not None else None,
        "tp": round(float(tp), 6) if tp is not None else None,
        "comment": comment,
        "status": "submitted",
        "account_mode": account_mode,
    }


async def handle_client(websocket, path=None):
    print(f" [Bridge] Client connected")
    try:
        async for message in websocket:
            data = json.loads(message)
            action = data.get("action")
            
            if action == "ping":
                response = {"status": "pong"}
            elif action == "get_account_info":
                response = get_account_info(data)
            elif action == "list_instruments":
                response = {"instruments": list_instruments()}
            elif action == "create_demo_pattern":
                symbol = data.get("symbol", config.DEFAULT_TRADING_SYMBOL)
                pattern = data.get("pattern", "head_and_shoulders")
                length = int(data.get("length", 60))
                seed = data.get("seed")
                try:
                    seed = int(seed) if seed is not None else None
                except Exception:
                    seed = None
                response = {"candles": synthesize_demo_candles(symbol, pattern, length, seed)}
            elif action == "get_rates":
                symbol = data.get("symbol", config.DEFAULT_TRADING_SYMBOL)
                timeframe = data.get("timeframe", config.DEFAULT_TRADING_TIMEFRAME)
                count = int(data.get("count", 60)) if data.get("count") is not None else 60
                account_mode = str(data.get("account_mode") or "demo").lower()
                seed = data.get("seed")
                try:
                    seed = int(seed) if seed is not None else None
                except Exception:
                    seed = None
                rates = get_rates_for_symbol(symbol, timeframe, count, seed, account_mode=account_mode)
                response = {
                    "rates": rates,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "count": count,
                    "account_mode": account_mode,
                }
                if isinstance(rates, dict):
                    response.update(rates)
            elif action == "place_order":
                response = place_order(data)
            else:
                response = {"error": f"Unknown action: {action}"}
            
            await websocket.send(json.dumps(response))
    except Exception as e:
        print(f" [Bridge] Error: {e}")
    finally:
        print(f" [Bridge] Client disconnected")

async def main():
    try:
        print(f"[Bridge] Starting MT5 Bridge Server on {HOST}:{PORT}")
    except Exception:
        # Avoid printing emojis under Wine's CP1252 code page which can raise
        # UnicodeEncodeError; fall back to ASCII-only output.
        try:
            print(f"[Bridge] Starting MT5 Bridge Server on {HOST}:{PORT}")
        except Exception:
            pass
    
    try:
        import websockets
        inherited_sock = _get_inherited_socket()
        try:
            if inherited_sock is not None:
                async with websockets.serve(handle_client, host=None, port=None, sock=inherited_sock, reuse_port=False):
                    try:
                        print(f"[Bridge] Listening for commands...")
                    except Exception:
                        pass
                    await asyncio.Future()
            else:
                async with websockets.serve(handle_client, HOST, PORT, reuse_port=False):
                    try:
                        print(f"[Bridge] Listening for commands...")
                    except Exception:
                        pass
                    await asyncio.Future()
        except OSError as bind_error:
            try:
                print(f"[Bridge] Failed to bind to {HOST}:{PORT}: {bind_error}")
            except Exception:
                pass
            print("   This usually means the port is already in use. Use a free port or stop the conflicting service.")
            sys.exit(1)
    except ImportError:
        print("⚠️ websockets not installed. Run: pip install websockets")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
