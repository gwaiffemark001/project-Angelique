# skills/trading/engine/connection_manager.py
import asyncio
import json
import os
import threading
import time

try:
    import websockets
except ImportError as e:
    print(f"⚠️ [MT5] websockets is not installed: {e}")
    websockets = None

from core import config


class MT5ConnectionManager:
    def __init__(self, host=None, port=None):
        self.host = host or config.MT5_BRIDGE_HOST
        self.port = int(port or config.MT5_BRIDGE_PORT)
        self.ws = None
        self._is_connected = False
        self._last_error = None
        self._loop = None
        self._thread = None
        self._lock = threading.Lock()
        self._stop_reconnect = threading.Event()

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
            self._thread.start()
            for _ in range(int(config.MT5_BRIDGE_CONNECT_TIMEOUT / 0.1)):
                if self._is_connected:
                    return True
                time.sleep(0.1)
        return self._is_connected

    def connect(self):
        with self._lock:
            if self._is_connected:
                return True
            if self._loop is None or self._loop.is_closed():
                self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
                self._thread.start()
                for _ in range(int(config.MT5_BRIDGE_CONNECT_TIMEOUT / 0.1)):
                    if self._is_connected:
                        return True
                    time.sleep(0.1)
        return self._is_connected

    def _run_event_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._reconnect_loop())
        except Exception as e:
            print(f"⚠️ [MT5 Client] Connection loop failed: {e}")
            self._is_connected = False

    async def _reconnect_loop(self):
        while not self._stop_reconnect.is_set():
            if not self._is_connected:
                await self._connect_async()
            await asyncio.sleep(config.MT5_BRIDGE_RECONNECT_INTERVAL)

    async def _connect_async(self):
        if websockets is None:
            self._is_connected = False
            print("⚠️ [MT5 Client] websockets is unavailable; cannot connect to MT5 bridge.")
            return

        try:
            self.ws = await asyncio.wait_for(
                websockets.connect(
                    f"ws://{self.host}:{self.port}",
                    open_timeout=config.MT5_BRIDGE_CONNECT_TIMEOUT,
                ),
                timeout=config.MT5_BRIDGE_CONNECT_TIMEOUT,
            )
            self._is_connected = True
            print("🟢 [MT5 Client] Connected to Wine Bridge.")
        except Exception as e:
            self._is_connected = False
            self._last_error = str(e)
            print(f"⚠️ [MT5 Client] Connect failed, retrying in {config.MT5_BRIDGE_RECONNECT_INTERVAL}s: {e}")

    def send_command(self, action: str, params: dict | None = None) -> dict:
        if not self._is_connected:
            if not self.connect():
                self._last_error = "Not connected to MT5 bridge"
                return {"error": "Not connected to MT5 bridge"}

        payload = {"action": action}
        if params:
            payload.update(params)

        if self._loop is None:
            self._last_error = "Event loop not available"
            return {"error": "Event loop not available"}

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._send_async(json.dumps(payload)),
                self._loop,
            )
            result = future.result(timeout=config.MT5_BRIDGE_CONNECT_TIMEOUT)
            if "error" in result and "WebSocket" in result.get("error", ""):
                self._is_connected = False
                if self.connect():
                    future2 = asyncio.run_coroutine_threadsafe(
                        self._send_async(json.dumps(payload)),
                        self._loop,
                    )
                    result = future2.result(timeout=config.MT5_BRIDGE_CONNECT_TIMEOUT)
            return result
        except Exception as e:
            self._last_error = str(e)
            if not self._is_connected:
                self.connect()
            return {"error": str(e)}

    async def _send_async(self, message: str) -> dict:
        if self.ws is None:
            self._is_connected = False
            return {"error": "WebSocket not connected"}
        try:
            check = getattr(self.ws, "closed", None)
            if check is not None and check:
                self._is_connected = False
                return {"error": "WebSocket not connected"}
        except Exception:
            pass
        try:
            await self.ws.send(message)
            response = await asyncio.wait_for(self.ws.recv(), timeout=10.0)
            return json.loads(response)
        except asyncio.TimeoutError:
            self._is_connected = False
            return {"error": "WebSocket response timed out"}
        except Exception as e:
            self._is_connected = False
            self._last_error = f"WebSocket error: {e}"
            return {"error": f"WebSocket error: {e}"}

    def get_status(self) -> bool:
        return self._is_connected

    def get_last_error(self) -> str | None:
        return self._last_error

    def send_request(self, request: dict) -> dict:
        """Send a request to MT5 bridge and get response."""
        return self.send_command(request.get("command", ""), request)


bridge_manager = MT5ConnectionManager()