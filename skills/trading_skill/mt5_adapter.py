from __future__ import annotations

from typing import Any, Protocol


class MT5Adapter(Protocol):
    """The only interface the trading workflow uses for MT5/Wine."""

    def account(self, mode: str, symbol: str | None = None) -> dict[str, Any]: ...
    def symbols(self, mode: str, symbol: str | None = None) -> list[str]: ...
    def market(self, symbol: str, timeframes: tuple[str, ...], mode: str, count: int) -> dict[str, Any]: ...
    def execute(self, order: dict[str, Any], mode: str) -> dict[str, Any]: ...
    def positions(self, mode: str) -> dict[str, Any]: ...
    def recent_deals(self, mode: str, minutes: int = 60) -> dict[str, Any]: ...
    def calculate_profit(self, mode: str, symbol: str, direction: str, volume: float, price_open: float, price_close: float) -> dict[str, Any]: ...


class WineMT5Adapter:
    """Adapter boundary for the MT5 Python process running inside Wine."""

    def __init__(self, bridge_client: Any):
        self.bridge = bridge_client

    def account(self, mode: str, symbol: str | None = None) -> dict[str, Any]:
        payload = {"account_mode": mode}
        if symbol:
            payload["symbol"] = symbol
        return self.bridge.request("account", payload)

    def symbols(self, mode: str, symbol: str | None = None) -> list[str]:
        payload = {"account_mode": mode}
        if symbol:
            payload["symbol"] = symbol
        response = self.bridge.request("symbols", payload)
        return list(response.get("symbols", []))

    def market(self, symbol: str, timeframes: tuple[str, ...], mode: str, count: int) -> dict[str, Any]:
        return self.bridge.request("market", {"symbol": symbol, "timeframes": list(timeframes), "account_mode": mode, "count": count})

    def execute(self, order: dict[str, Any], mode: str) -> dict[str, Any]:
        return self.bridge.request("execute", {"order": order, "account_mode": mode})

    def positions(self, mode: str) -> dict[str, Any]:
        return self.bridge.request("positions", {"account_mode": mode})

    def recent_deals(self, mode: str, minutes: int = 60) -> dict[str, Any]:
        return self.bridge.request("recent_deals", {"account_mode": mode, "minutes": int(minutes)})

    def calculate_profit(self, mode: str, symbol: str, direction: str, volume: float, price_open: float, price_close: float) -> dict[str, Any]:
        return self.bridge.request("calculate_profit", {"account_mode": mode, "symbol": symbol, "direction": direction, "volume": float(volume), "price_open": float(price_open), "price_close": float(price_close)})
