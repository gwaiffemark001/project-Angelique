# skills/trading/engine/mt5_bridge.py
from skills.trading.engine.connection_manager import bridge_manager

class MT5Bridge:
    @staticmethod
    def ensure_connected():
        if not bridge_manager.get_status():
            bridge_manager.connect()
        return bridge_manager.get_status()

    @staticmethod
    def get_account_info() -> dict:
        if not MT5Bridge.ensure_connected():
            return {"error": "Not connected"}
        return bridge_manager.send_command("get_account_info")

    @staticmethod
    def ping() -> dict:
        if not MT5Bridge.ensure_connected():
            return {"error": "Not connected"}
        return bridge_manager.send_command("ping")

bridge = MT5Bridge()
