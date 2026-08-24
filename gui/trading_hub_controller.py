"""Trading Hub orchestration independent from Tk widget rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TradingRefreshResult:
    """Data contract returned by a background Trading Hub refresh."""

    symbol: str
    account: dict
    market_data: dict
    bridge_active: bool
    bridge_error: str | None
    account_mode: str
    instruments: Any = None
    health: dict[str, Any] | None = None
    positions: dict[str, Any] | None = None


class TradingHubController:
    """Coordinates trading services while leaving presentation to the desktop view."""

    def __init__(self, trading_mode: str = "DAY_TRADING"):
        from skills.trading_skill.profiles import get_trading_profile

        self._trading_mode = get_trading_profile(trading_mode).mode

    @property
    def trading_mode(self) -> str:
        return self._trading_mode.value

    def set_trading_mode(self, mode: str) -> dict[str, object]:
        from skills.trading_skill.profiles import get_trading_profile
        from skills.trading_skill import service

        self._trading_mode = get_trading_profile(mode).mode
        service.set_trading_mode(self._trading_mode.value)
        return get_trading_profile(self._trading_mode).as_dict()

    def get_trading_profile(self) -> dict[str, object]:
        from skills.trading_skill.profiles import get_trading_profile

        return get_trading_profile(self._trading_mode).as_dict()

    def load_refresh(self, symbol: str, timeframe: str, account_mode: str) -> TradingRefreshResult:
        from skills.trading.engine.account import get_account_summary
        from skills.trading.engine.connection_manager import bridge_manager
        from skills.trading.market.market_data import market

        active = bridge_manager.get_status()
        if not active:
            bridge_manager.connect()
            active = bridge_manager.get_status()
        account = get_account_summary(account_mode=account_mode)
        bridge_error = account.get("error")
        if not bridge_error and not active:
            bridge_error = bridge_manager.get_last_error()
        market_data = market.get_candles_and_indicators(symbol, timeframe, account_mode=account_mode)
        from skills.trading_skill.service import get_open_positions

        positions = get_open_positions(account_mode)
        candles = market_data.get("candles", []) if isinstance(market_data, dict) else []
        account_connected = bool(account.get("login")) and not bool(account.get("error"))
        market_live = bool(candles) and not bool(market_data.get("stale"))
        try:
            quotes_ready = float(market_data.get("bid") or 0) > 0 and float(market_data.get("ask") or 0) > 0
        except (TypeError, ValueError):
            quotes_ready = False
        health = {
            "mt5": "CONNECTED" if active else "DISCONNECTED",
            "bridge": "CONNECTED" if active else "DISCONNECTED",
            "account": "CONNECTED" if account_connected else "DISCONNECTED",
            "market_data": "LIVE" if market_live and quotes_ready else "STALE/UNAVAILABLE",
            "symbol": "RESOLVED" if not market_data.get("error") else "UNRESOLVED",
            "last_tick": market_data.get("last_tick") or market_data.get("timestamp") or "unknown",
            "monitor": "RUNNING",
            "trading_enabled": bool(active and account_connected and market_live and quotes_ready and not market_data.get("error")),
        }

        instruments = None
        try:
            instruments = bridge_manager.send_command("list_instruments", {"account_mode": account_mode})
        except Exception:
            pass

        return TradingRefreshResult(
            symbol=symbol,
            account=account,
            market_data=market_data,
            bridge_active=active,
            bridge_error=bridge_error,
            account_mode=account_mode,
            instruments=instruments,
            health=health,
            positions=positions,
        )

    def monitor_opportunities(self, account_mode: str, allowed_symbols: list[str] | None = None) -> dict:
        from skills.trading_skill import service

        service.set_trading_mode(self.trading_mode)
        if allowed_symbols is None:
            return service.monitor_universe(account_mode, trading_mode=self.trading_mode)
        return service.monitor_universe(
            account_mode,
            trading_mode=self.trading_mode,
            allowed_symbols=allowed_symbols,
        )
