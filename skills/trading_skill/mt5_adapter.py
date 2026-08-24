from __future__ import annotations

from typing import Any, Protocol


class MT5Adapter(Protocol):
    """The only interface the trading workflow uses for MT5/Wine."""

    def account(self, mode: str) -> dict[str, Any]: ...
    def symbols(self, mode: str) -> list[str]: ...
    def market(self, symbol: str, timeframes: tuple[str, ...], mode: str, count: int) -> dict[str, Any]: ...
    def execute(self, order: dict[str, Any], mode: str) -> dict[str, Any]: ...
    def positions(self, mode: str) -> dict[str, Any]: ...


class WineMT5Adapter:
    """Adapter boundary for the MT5 Python process running inside Wine."""

    def __init__(self, bridge_client: Any):
        self.bridge = bridge_client

    def account(self, mode: str) -> dict[str, Any]:
        return self.bridge.request("account", {"account_mode": mode})

    def symbols(self, mode: str) -> list[str]:
        response = self.bridge.request("symbols", {"account_mode": mode})
        return list(response.get("symbols", []))

    def market(self, symbol: str, timeframes: tuple[str, ...], mode: str, count: int) -> dict[str, Any]:
        return self.bridge.request("market", {"symbol": symbol, "timeframes": list(timeframes), "account_mode": mode, "count": count})

    def execute(self, order: dict[str, Any], mode: str) -> dict[str, Any]:
        return self.bridge.request("execute", {"order": order, "account_mode": mode})

    def positions(self, mode: str) -> dict[str, Any]:
        return self.bridge.request("positions", {"account_mode": mode})
