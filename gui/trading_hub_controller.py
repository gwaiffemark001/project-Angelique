"""Trading Hub orchestration independent from Tk widget rendering."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TradingRefreshResult:
    symbol: str
    account: dict
    market_data: dict
    bridge_active: bool
    bridge_error: str | None
    account_mode: str
    instruments: Any = None
    health: dict[str, Any] | None = None
    positions: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None


class TradingHubController:
    """Coordinates trading services without owning Tk rendering state."""

    def __init__(self, trading_mode: str = "DAY_TRADING"):
        from skills.trading_skill.profiles import get_trading_profile
        self._trading_mode = get_trading_profile(trading_mode).mode

    @property
    def trading_mode(self) -> str:
        return self._trading_mode.value

    def set_trading_mode(self, mode: str) -> dict[str, object]:
        from skills.trading_skill import service
        from skills.trading_skill.profiles import get_trading_profile
        profile = get_trading_profile(mode)
        self._trading_mode = profile.mode
        service.set_trading_mode(self._trading_mode.value)
        return profile.as_dict()

    def get_trading_profile(self) -> dict[str, object]:
        from skills.trading_skill.profiles import get_trading_profile
        return get_trading_profile(self._trading_mode).as_dict()

    def synchronize_account_mode(self, account_mode: str) -> dict[str, Any]:
        """Force-refresh and verify the exact MT5 account environment."""
        from skills.trading_skill.account_manager import account_manager
        snap = account_manager.switch_mode(account_mode)
        return {
            **snap.__dict__,
            "mode_match": bool(snap.connected and snap.actual_mode == snap.requested_mode),
        }

    def load_refresh(self, symbol: str, timeframe: str, account_mode: str) -> TradingRefreshResult:
        from skills.trading_skill.bridge import WineBridgeClient
        from skills.trading_skill.account_manager import account_manager
        from skills.trading_skill.universe import eligible_symbols
        from core import config

        # One authoritative account query for the requested environment.
        snapshot = account_manager.switch_mode(account_mode)
        account = {
            **snapshot.__dict__,
            "mode": snapshot.actual_mode,
            "requested_mode": snapshot.requested_mode,
            "display_mode": "REAL" if snapshot.actual_mode == "real" else "DEMO",
            "mode_match": bool(snapshot.connected and snapshot.actual_mode == snapshot.requested_mode),
            "status": "connected" if snapshot.connected else "unavailable",
        }

        bridge = WineBridgeClient()
        requested = str(symbol or config.DEFAULT_TRADING_SYMBOL)
        market_error = None
        market_data: dict[str, Any] = {"timeframes": {}}
        instruments = None

        if account["mode_match"]:
            try:
                symbols_response = bridge.request("symbols", {"account_mode": account_mode})
                available = symbols_response.get("symbols", []) if isinstance(symbols_response, dict) else []
                instruments = available
                resolved = None
                from skills.trading_skill.symbols import resolve
                resolved = resolve(requested, available) if available else None
                if not resolved:
                    market_error = f"Unable to resolve {requested} in the selected {account_mode.upper()} MT5 account."
                else:
                    from skills.trading_skill.profiles import get_trading_profile
                    profile = get_trading_profile(self.trading_mode)
                    required = list(profile.analysis_required_timeframes)
                    selected_tf = str(timeframe or config.DEFAULT_TRADING_TIMEFRAME).upper()
                    # The chart timeframe is a first-class request. Analysis still
                    # receives the profile-required set, while the selected chart
                    # timeframe is added when it is outside that set.
                    request_timeframes = list(dict.fromkeys([*required, selected_tf]))
                    count = max(profile.candle_count(tf) for tf in request_timeframes)
                    market_data = bridge.request("market", {
                        "symbol": resolved,
                        "account_mode": account_mode,
                        "timeframes": request_timeframes,
                        "count": count,
                    })
            except Exception as exc:
                market_error = str(exc)
        else:
            market_error = account.get("error") or (
                f"MT5 is connected to {account.get('actual_mode', 'unknown')}; "
                f"Trading Hub requested {account_mode}."
            )

        if market_error and not market_data.get("error"):
            market_data["error"] = market_error

        positions = {}
        if account["mode_match"]:
            try:
                from skills.trading_skill.service import get_open_positions
                positions = get_open_positions(account_mode)
            except Exception as exc:
                positions = {"status": "error", "error": str(exc), "positions": []}

        candles = market_data.get("timeframes", {}) if isinstance(market_data, dict) else {}
        analysis = None
        if candles:
            try:
                from skills.trading_skill.analysis import analyze_structure
                from skills.trading_skill.profiles import get_trading_profile
                profile = get_trading_profile(self.trading_mode)
                # UI diagnostics never authorize execution; the workflow remains
                # the only execution gate.
                analysis = analyze_structure(candles, profile=profile)
            except Exception as exc:
                analysis = {"valid": False, "decision": "BLOCKED", "reason": str(exc)}
        from skills.trading_skill.profiles import get_trading_profile
        from skills.trading_skill.data_quality import assess_candles
        required_profile = get_trading_profile(self.trading_mode)
        quality = {}
        for tf in required_profile.analysis_required_timeframes:
            quality[tf] = assess_candles(
                candles.get(tf, []),
                tf,
                minimum_candles=required_profile.minimum_analysis_candles(tf),
            )
        quality_states = {item.get("status") for item in quality.values()} if quality else {"missing"}
        quote_ok = float(market_data.get("bid") or 0) > 0 and float(market_data.get("ask") or 0) > 0
        base_market_ok = bool(candles) and not bool(market_data.get("error")) and quote_ok
        if "stale" in quality_states:
            market_quality_state = "STALE"
        elif "insufficient" in quality_states:
            market_quality_state = "INSUFFICIENT_HISTORY"
        elif quality_states - {"fresh"}:
            market_quality_state = "UNAVAILABLE"
        elif base_market_ok:
            market_quality_state = "LIVE"
        else:
            market_quality_state = "UNAVAILABLE"
        fresh = market_quality_state == "LIVE"
        health = {
            "mt5": "CONNECTED" if account["mode_match"] else "MODE_MISMATCH" if snapshot.connected else "DISCONNECTED",
            "bridge": "CONNECTED" if account["mode_match"] else "BLOCKED",
            "account": "CONNECTED" if account["mode_match"] else "MODE_MISMATCH" if snapshot.connected else "DISCONNECTED",
            "broker": snapshot.broker or "UNKNOWN",
            "market_data": market_quality_state,
            "data_quality": quality,
            "symbol": "RESOLVED" if not market_data.get("error") else "UNRESOLVED",
            "last_tick": market_data.get("last_tick") or market_data.get("timestamp") or "unknown",
            "monitor": "RUNNING",
            "trading_enabled": bool(account["mode_match"] and fresh),
        }

        return TradingRefreshResult(
            symbol=requested,
            account=account,
            market_data=market_data,
            bridge_active=bool(account["mode_match"]),
            bridge_error=market_error,
            account_mode=account_mode,
            instruments=instruments,
            health=health,
            positions=positions,
            analysis=analysis,
        )

    def monitor_opportunities(self, account_mode: str, allowed_symbols: list[str] | None = None) -> dict:
        from skills.trading_skill import service
        return service.monitor_universe(account_mode, trading_mode=self.trading_mode, allowed_symbols=allowed_symbols)

    def decide_and_act(self, account_mode: str, allowed_symbols: list[str] | None = None) -> dict:
        from skills.trading_skill import service
        return service.decide_and_act(account_mode, trading_mode=self.trading_mode, allowed_symbols=allowed_symbols)

    def run_position_management(self, account_mode: str) -> dict:
        from skills.trading_skill import service
        return service.run_position_management(account_mode, trading_mode=self.trading_mode)

    def close_position(self, ticket: int, symbol: str, account_mode: str) -> dict:
        from skills.trading_skill import service
        return service.close_position_manual(ticket, symbol, account_mode)

    def close_all_positions(self, account_mode: str) -> dict:
        from skills.trading_skill import service
        return service.close_all_positions_manual(account_mode)
