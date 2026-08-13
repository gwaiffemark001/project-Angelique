from __future__ import annotations

import json
from typing import Any

try:
    import websocket
except Exception:
    websocket = None

from core import config


class WineBridgeClient:
    """Host-side client for the MT5 bridge process launched through Wine."""

    def __init__(self, url: str | None = None, timeout: float | None = None):
        self.url = url or f"ws://{config.MT5_BRIDGE_HOST}:{config.MT5_BRIDGE_PORT}"
        self.timeout = timeout or config.MT5_BRIDGE_CONNECT_TIMEOUT

    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if websocket is None:
            return {"error": "websocket-client is unavailable", "status": "error"}
        try:
            return self._request_once(operation, payload)
        except Exception as exc:
            return {"error": str(exc), "status": "error"}

    def _request_once(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        legacy_actions = {
            "account": "get_account_info",
            "symbols": "list_instruments",
            "market": "get_rates",
            "execute": "place_order",
            "positions": "positions",
            "get_positions": "positions",
            "ping": "ping",
        }
        request = {"operation": operation, "action": legacy_actions.get(operation, operation), **payload}
        if operation == "market":
            timeframes = payload.get("timeframes")
            if timeframes:
                request["timeframes"] = timeframes
            else:
                request["timeframe"] = payload.get("timeframe", "H1")
        client = websocket.create_connection(self.url, timeout=self.timeout)
        client.send(json.dumps(request))
        response = json.loads(client.recv())
        client.close()
        response = response if isinstance(response, dict) else {"data": response}
        if operation == "symbols" and "symbols" not in response and "instruments" in response:
            response["symbols"] = response["instruments"]
        if operation == "positions" and "positions" not in response and "data" in response:
            response["positions"] = response["data"]
        if operation == "market" and "timeframes" not in response:
            candles = response.get("candles") or response.get("rates") or []
            timeframe = request.get("timeframe", "H1")
            response["timeframes"] = {timeframe: candles}
            response.setdefault("status", "connected" if candles else "error")
        return response
