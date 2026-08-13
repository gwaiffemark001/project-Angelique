from __future__ import annotations

from typing import Any

from .bridge import WineBridgeClient
from .event_logging import log_event


class PositionMonitor:
    def __init__(self, bridge_client: Any = None):
        self.bridge = bridge_client or WineBridgeClient()

    def get_open_positions(self, account_mode: str = "demo", symbol: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"account_mode": account_mode}
        if symbol:
            payload["symbol"] = symbol
        response = self.bridge.request("positions", payload)
        if response.get("status") == "error" or response.get("error"):
            log_event(30, "position_monitor.request_failed", account_mode=account_mode, symbol=symbol, error=response.get("error"))
            return {"positions": [], "status": "error", "error": response.get("error")}
        return {"positions": response.get("positions", []), "status": response.get("status", "connected")}


position_monitor = PositionMonitor()
