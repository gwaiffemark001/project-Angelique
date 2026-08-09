# skills/trading/engine/mt5_bridge.py
from skills.trading.engine.connection_manager import bridge_manager


class MT5Bridge:
    @staticmethod
    def ensure_connected():
        if not bridge_manager.get_status():
            bridge_manager.connect()
        return bridge_manager.get_status()

    @staticmethod
    def send_command(action: str, params: dict | None = None) -> dict:
        if not MT5Bridge.ensure_connected():
            return {"error": "Not connected"}
        return bridge_manager.send_command(action, params)

    @staticmethod
    def get_account_info(account_mode: str = "demo") -> dict:
        if not MT5Bridge.ensure_connected():
            return {"error": "Not connected"}
        return bridge_manager.send_command("get_account_info", {"account_mode": account_mode})

    @staticmethod
    def ping() -> dict:
        if not MT5Bridge.ensure_connected():
            return {"error": "Not connected"}
        return bridge_manager.send_command("ping")

    @staticmethod
    def list_instruments() -> list:
        if not MT5Bridge.ensure_connected():
            return {"error": "Not connected"}
        return bridge_manager.send_command("list_instruments")

    @staticmethod
    def create_demo_pattern(symbol: str, pattern: str, length: int = 60) -> dict:
        if not MT5Bridge.ensure_connected():
            return {"error": "Not connected"}
        payload = {"symbol": symbol, "pattern": pattern, "length": length}
        return bridge_manager.send_command("create_demo_pattern", payload)


bridge = MT5Bridge()
