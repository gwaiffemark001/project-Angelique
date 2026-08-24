from __future__ import annotations

from typing import Any

from .bridge import WineBridgeClient
from .event_logging import log_event
from .profiles import get_trading_profile


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

    @staticmethod
    def evaluate_position(position: dict[str, Any], market: dict[str, Any] | None = None) -> dict[str, Any]:
        """Calculate management state; callers decide whether a modification is authorized."""
        market = market or {}
        direction = str(position.get("direction", position.get("type", "BUY"))).upper()
        entry = float(position.get("entry", position.get("open_price", position.get("price_open", 0))) or 0)
        stop_loss = float(position.get("stop_loss", position.get("sl", 0)) or 0)
        current = float(market.get("price", position.get("current_price", entry)) or entry)
        distance = abs(entry - stop_loss)
        if distance <= 0:
            return {"ticket": position.get("ticket"), "valid": False, "action": "HOLD", "reason": "Missing structural stop distance."}

        favorable_move = current - entry if direction in {"BUY", "LONG", "0"} else entry - current
        r_multiple = favorable_move / distance
        mode = position.get("trading_mode", "DAY_TRADING")
        profile = get_trading_profile(mode)
        result = {
            "ticket": position.get("ticket"),
            "symbol": position.get("symbol"),
            "trading_mode": profile.mode.value,
            "valid": True,
            "r_multiple": round(r_multiple, 4),
            "current_price": current,
            "floating_profit": position.get("profit", position.get("floating_profit")),
            "swap": position.get("swap"),
            "spread_pips": market.get("spread_pips"),
            "action": "HOLD",
            "reason": "Position remains within its management policy.",
        }
        if r_multiple >= 2.0:
            atr_value = float(market.get("atr", 0) or 0)
            structure_level = market.get("structure_stop")
            if structure_level is not None or atr_value > 0:
                result.update(
                    action="TRAIL",
                    reason="Position reached +2R; trail using structure and ATR.",
                    suggested_stop=structure_level if structure_level is not None else (
                        current - atr_value * profile.sl_atr_multiplier
                        if direction in {"BUY", "LONG", "0"}
                        else current + atr_value * profile.sl_atr_multiplier
                    ),
                )
        elif r_multiple >= 1.0:
            result.update(
                action="BREAK_EVEN",
                reason="Position reached +1R; move stop approximately to break-even.",
                suggested_stop=entry,
            )
        return result

    def monitor_once(self, account_mode: str = "demo", symbol: str | None = None, market_by_symbol: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        response = self.get_open_positions(account_mode, symbol)
        if response.get("status") == "error":
            return response
        market_by_symbol = market_by_symbol or {}
        decisions = [
            self.evaluate_position(position, market_by_symbol.get(position.get("symbol"), {}))
            for position in response.get("positions", [])
        ]
        return {**response, "decisions": decisions}


position_monitor = PositionMonitor()
