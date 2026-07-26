# skills/trading/engine/connection_manager.py
import asyncio
import json
import os
import threading
import time
import websockets

from core import config

class MT5ConnectionManager:
    def __init__(self, host=None, port=None):
        self.host = host or config.MT5_BRIDGE_HOST
        self.port = int(port or config.MT5_BRIDGE_PORT)
        self.ws = None
        self._is_connected = False
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
        try:
            self.ws = await websockets.connect(
                f"ws://{self.host}:{self.port}",
                open_timeout=config.MT5_BRIDGE_CONNECT_TIMEOUT,
            )
            self._is_connected = True
            print("🟢 [MT5 Client] Connected to Wine Bridge.")
        except Exception as e:
            self._is_connected = False
            print(f"⚠️ [MT5 Client] Connect failed, retrying in {config.MT5_BRIDGE_RECONNECT_INTERVAL}s: {e}")

    def send_command(self, action: str, params: dict | None = None) -> dict:
        if not self._is_connected:
            self.connect()
            return {"error": "Not connected"}

        payload = {"action": action}
        if params:
            payload.update(params)

        if self._loop is None:
            return {"error": "Event loop not available"}

        try:
            future = asyncio.run_coroutine_threadsafe(
                self._send_async(json.dumps(payload)),
                self._loop
            )
            return future.result(timeout=config.MT5_BRIDGE_CONNECT_TIMEOUT)
        except Exception as e:
            self._is_connected = False
            return {"error": str(e)}

    async def _send_async(self, message: str) -> dict:
        if self.ws is None or self.ws.closed:
            self._is_connected = False
            return {"error": "WebSocket not connected"}
        await self.ws.send(message)
        response = await self.ws.recv()
        return json.loads(response)

    def get_status(self) -> bool:
        return self._is_connected

    def send_request(self, request: dict) -> dict:
        """Send a request to MT5 bridge and get response."""
        return self.send_command(request.get("command", ""), request)


bridge_manager = MT5ConnectionManager()

