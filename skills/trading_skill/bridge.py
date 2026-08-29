from __future__ import annotations

import json
from typing import Any

try:
    import websocket
except Exception:
    websocket = None

try:
    from websockets.sync.client import connect as websocket_sync_connect
except Exception:
    websocket_sync_connect = None

from core import config
from core.trading_routing import broker_for_symbol, port_for_broker


class WineBridgeClient:
    """Host-side client for the MT5 bridge process launched through Wine."""

    def __init__(self, url: str | None = None, timeout: float | None = None, broker: str | None = None):
        self._explicit_url = url
        self.broker = str(broker or "").upper() or None
        self.url = url or self._default_url(self.broker)
        self.timeout = timeout or config.MT5_BRIDGE_CONNECT_TIMEOUT

    @staticmethod
    def _default_url(broker: str | None = None) -> str:
        if broker:
            port = port_for_broker(broker)
        else:
            port = config.MT5_BRIDGE_PORT
        return f"ws://{config.MT5_BRIDGE_HOST}:{port}"

    def _url_for_payload(self, payload: dict[str, Any]) -> str:
        if self._explicit_url:
            return self._explicit_url
        broker = self.broker
        symbol = payload.get("symbol") or payload.get("mt5_symbol") or payload.get("requested_symbol")
        if symbol:
            broker = broker_for_symbol(str(symbol))
        return self._default_url(broker)

    def request(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if websocket is None and websocket_sync_connect is None:
            return {"error": "No WebSocket client is available", "status": "error"}
        if websocket_sync_connect is not None:
            try:
                return self._request_once_sync(operation, payload)
            except Exception as sync_exc:
                if websocket is None:
                    return {"error": str(sync_exc), "status": "error"}
        try:
            return self._request_once(operation, payload)
        except Exception as exc:
            return {"error": str(exc), "status": "error"}

    def _request_once_sync(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        legacy_actions = {
            "account": "get_account_info",
            "symbols": "list_instruments",
            "market": "get_rates",
            "execute": "place_order",
            "positions": "positions",
            "get_positions": "positions",
            "close_position": "close_position",
            "close_all_positions": "close_all_positions",
            "modify_position": "modify_position",
            "ping": "ping",
        }
        request = {"operation": operation, "action": legacy_actions.get(operation, operation), **payload}
        routed_broker = self.broker
        routed_symbol = payload.get("symbol") or payload.get("mt5_symbol") or payload.get("requested_symbol")
        if routed_symbol:
            routed_broker = broker_for_symbol(str(routed_symbol))
        if routed_broker:
            request["expected_broker"] = routed_broker
        if operation == "market":
            request["timeframes"] = payload.get("timeframes") or [payload.get("timeframe", "H1")]
        with websocket_sync_connect(self._url_for_payload(payload), open_timeout=self.timeout, close_timeout=self.timeout) as client:
            client.send(json.dumps(request))
            response = json.loads(client.recv(timeout=self.timeout))
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

    def _request_once(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        legacy_actions = {
            "account": "get_account_info",
            "symbols": "list_instruments",
            "market": "get_rates",
            "execute": "place_order",
            "positions": "positions",
            "get_positions": "positions",
            "close_position": "close_position",
            "close_all_positions": "close_all_positions",
            "modify_position": "modify_position",
            "ping": "ping",
        }
        request = {"operation": operation, "action": legacy_actions.get(operation, operation), **payload}
        routed_broker = self.broker
        routed_symbol = payload.get("symbol") or payload.get("mt5_symbol") or payload.get("requested_symbol")
        if routed_symbol:
            routed_broker = broker_for_symbol(str(routed_symbol))
        if routed_broker:
            request["expected_broker"] = routed_broker
        if operation == "market":
            timeframes = payload.get("timeframes")
            if timeframes:
                request["timeframes"] = timeframes
            else:
                request["timeframe"] = payload.get("timeframe", "H1")
        client = websocket.create_connection(self._url_for_payload(payload), timeout=self.timeout)
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
        # propagate explicit spread_pips if provided by the MT5 side
        if operation == "market" and "spread_pips" in response:
            response.setdefault("spread_pips", response.get("spread_pips"))
        return response
