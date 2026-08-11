from __future__ import annotations

from skills.trading_skill.bridge import WineBridgeClient


class BridgeFacade:
    def __init__(self):
        self.client = WineBridgeClient()
        self._connected = False
        self._last_error = None
        self._last_status_check = 0.0

    def connect(self):
        response = self.client.request("ping", {})
        self._connected = response.get("status") in {"pong", "connected"}
        self._last_error = response.get("error")
        return self._connected

    def start(self):
        return self.connect()

    def get_status(self):
        import time
        if time.monotonic() - self._last_status_check < 2.0:
            return self._connected
        self._last_status_check = time.monotonic()
        response = self.client.request("ping", {})
        self._connected = response.get("status") == "pong" or response.get("status") == "connected"
        self._last_error = response.get("error")
        return self._connected

    def ping(self):
        return {"status": "connected"} if self.connect() else {"status": "error", "error": self._last_error}

    def get_last_error(self):
        return self._last_error

    def request(self, operation, payload=None):
        response = self.client.request(operation, payload or {})
        self._connected = response.get("status") != "error"
        self._last_error = response.get("error")
        return response

    def send_command(self, action, payload=None):
        operations = {"get_account_info": "account", "list_instruments": "symbols", "get_symbols": "symbols", "get_rates": "market", "close_position": "close_position"}
        operation = operations.get(action, action)
        return self.request(operation, payload)

    def get_account_info(self, account_mode="demo"):
        return self.request("account", {"account_mode": account_mode})


bridge = BridgeFacade()
