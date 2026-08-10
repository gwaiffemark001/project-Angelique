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
            "ping": "ping",
        }
        request = {"operation": operation, "action": legacy_actions.get(operation, operation), **payload}
        if operation == "market":
            timeframes = payload.get("timeframes") or [payload.get("timeframe", "H1")]
            request["timeframe"] = timeframes[0]
        client = websocket.create_connection(self.url, timeout=self.timeout)
        client.send(json.dumps(request))
        response = json.loads(client.recv())
        client.close()
        response = response if isinstance(response, dict) else {"data": response}
        if operation == "symbols" and "symbols" not in response and "instruments" in response:
            response["symbols"] = response["instruments"]
        if operation == "market" and "timeframes" not in response:
            candles = response.get("candles") or response.get("rates") or []
            timeframe = request.get("timeframe", "H1")
            response["timeframes"] = {timeframe: candles}
            response.setdefault("status", "connected" if candles else "error")
            requested_timeframes = list(payload.get("timeframes") or [])
            for extra_timeframe in requested_timeframes[1:]:
                extra_payload = {**payload, "timeframe": extra_timeframe}
                extra_payload.pop("timeframes", None)
                extra = self._request_once("market", extra_payload)
                response["timeframes"][extra_timeframe] = (extra.get("candles") or extra.get("rates") or extra.get("timeframes", {}).get(extra_timeframe, []))
                if extra.get("error") and not response.get("error"):
                    response["error"] = extra["error"]
        return response
