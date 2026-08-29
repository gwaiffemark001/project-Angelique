from __future__ import annotations

from core import config

BROKER_NAME = "VALETAX"
SUPPORTED_SYMBOLS = {
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD",
    "XAUUSD", "XAGUSD", "BTCUSD", "ETHUSD", "AUDCAD",
    "EURGBP", "EURJPY", "GBPJPY", "GOLD"
}


def normalize_symbol(symbol: str) -> str:
    return "".join(ch for ch in str(symbol or "").upper() if ch.isalnum())


def broker_for_symbol(symbol: str) -> str:
    """Return the broker for any supported symbol. All symbols route to Valetax."""
    key = normalize_symbol(symbol)
    if not key:
        raise ValueError("Missing trading symbol; unsupported broker routing request.")
    if not any(key == supported or key.startswith(supported) for supported in SUPPORTED_SYMBOLS):
        raise ValueError(f"Unsupported trading symbol for Valetax: {symbol}")
    return BROKER_NAME


def port_for_broker(broker: str) -> int:
    name = str(broker or "").upper()
    if name == BROKER_NAME:
        return config.TRADING_VALETAX_BRIDGE_PORT
    raise ValueError(
        f"Unsupported trading broker: {broker}. Only Valetax is supported."
    )


def route_for_symbol(symbol: str) -> dict[str, object]:
    broker = broker_for_symbol(symbol)
    return {"broker": broker, "port": port_for_broker(broker), "symbol": symbol}
