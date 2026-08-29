from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

from .bridge import WineBridgeClient
from .event_logging import log_event
from .profiles import get_trading_profile
from core import config


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
        # Time-stop: after the configured holding window, a trade that has
        # not reached +1R is considered stale and is eligible for automatic
        # exit. Unknown/invalid open times never trigger a blind exit.
        opened_raw = position.get("opened_at", position.get("time_open", position.get("open_time")))
        if opened_raw is not None:
            try:
                if isinstance(opened_raw, (int, float)):
                    opened_dt = datetime.fromtimestamp(float(opened_raw), tz=timezone.utc)
                else:
                    text = str(opened_raw).replace("Z", "+00:00")
                    opened_dt = datetime.fromisoformat(text)
                    if opened_dt.tzinfo is None:
                        opened_dt = opened_dt.replace(tzinfo=timezone.utc)
                    else:
                        opened_dt = opened_dt.astimezone(timezone.utc)
                age_hours = max(0.0, (datetime.now(timezone.utc) - opened_dt).total_seconds() / 3600.0)
                max_hours = max(1, int(profile.expected_hold_days)) * 24
                if age_hours >= max_hours and r_multiple < 1.0:
                    result.update(
                        action="TIME_STOP",
                        reason=f"Position exceeded the {profile.expected_hold_days}-day holding window without reaching +1R.",
                        age_hours=round(age_hours, 2),
                        max_hold_hours=max_hours,
                    )
                    return result
                result["age_hours"] = round(age_hours, 2)
                result["max_hold_hours"] = max_hours
            except (TypeError, ValueError, OverflowError):
                result["time_stop_status"] = "UNKNOWN_OPEN_TIME"

        # The caller (service.run_position_management) re-checks structure
        # on every pass and sets this when a fresh, complete setup has
        # formed in the OPPOSITE direction -- i.e. the reason this trade
        # was taken no longer holds. This overrides trailing/break-even:
        # protecting capital comes first.
        if bool(market.get("setup_invalidated")):
            result.update(
                action="EXIT",
                reason=market.get("invalidation_reason") or "Market structure has shifted against this position; closing to protect capital.",
            )
            return result
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

    def modify_position(self, ticket: int, symbol: str, stop_loss: float, take_profit: float | None = None, account_mode: str = "demo") -> dict[str, Any]:
        """Move a position's stop (break-even / trailing). This is the
        call that actually applies what evaluate_position only suggests."""
        payload: dict[str, Any] = {"ticket": ticket, "symbol": symbol, "stop_loss": stop_loss, "account_mode": account_mode}
        if take_profit is not None:
            payload["take_profit"] = take_profit
        response = self.bridge.request("modify_position", payload)
        log_event(
            30 if not response.get("success") else 20,
            "position_monitor.modify_position",
            ticket=ticket, symbol=symbol, stop_loss=stop_loss, account_mode=account_mode,
            success=response.get("success"), error=response.get("error"),
        )
        return response

    def close_single(self, ticket: int, symbol: str, account_mode: str = "demo") -> dict[str, Any]:
        """Close exactly one position, by ticket. Used both for automatic
        invalidation exits and for the manual 'close this position' button."""
        response = self.bridge.request("close_position", {"ticket": ticket, "symbol": symbol, "account_mode": account_mode})
        log_event(
            30 if not response.get("success") else 20,
            "position_monitor.close_single",
            ticket=ticket, symbol=symbol, account_mode=account_mode,
            success=response.get("success"), error=response.get("error"),
        )
        return response

    def apply_management(self, account_mode: str = "demo", market_by_symbol: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        """Run one full pass: evaluate every open position, then actually
        act on it -- move the stop for break-even/trail, or close it
        outright on invalidation. Without this, evaluate_position's
        suggestions are advisory only and nothing changes on the broker
        side."""
        monitor = self.monitor_once(account_mode, market_by_symbol=market_by_symbol)
        if monitor.get("status") == "error":
            return monitor
        positions_by_ticket = {position.get("ticket"): position for position in monitor.get("positions", [])}
        applied = []
        for decision in monitor.get("decisions", []):
            ticket = decision.get("ticket")
            symbol = decision.get("symbol")
            action = decision.get("action")
            position = positions_by_ticket.get(ticket, {})
            if action in {"EXIT", "TIME_STOP"}:
                result = self.close_single(ticket, symbol, account_mode)
                applied.append({"ticket": ticket, "symbol": symbol, "action": action, "reason": decision.get("reason"), "result": result})
                continue
            if action in {"BREAK_EVEN", "TRAIL"} and decision.get("suggested_stop") is not None:
                current_sl = float(position.get("sl", position.get("stop_loss", 0)) or 0)
                suggested = float(decision["suggested_stop"])
                direction = str(position.get("type", position.get("direction", "BUY"))).upper()
                # Only ever move the stop in the position's favor.
                improves = (suggested > current_sl) if direction in {"BUY", "LONG", "0"} else (suggested < current_sl)
                if improves and current_sl != suggested:
                    result = self.modify_position(ticket, symbol, suggested, position.get("tp") or position.get("take_profit"), account_mode)
                    applied.append({"ticket": ticket, "symbol": symbol, "action": action, "new_stop": suggested, "result": result})
        return {**monitor, "applied": applied}

    def check_kill_switch(self, account_snapshot, trading_mode: str = "DAY_TRADING", drawdown_percent: float = 0.0, consecutive_losses: int = 0) -> dict[str, Any]:
        """Loss-prevention circuit breaker. validate_profile_limits() already
        blocks *new* plans once the daily loss cap is hit, but that does
        nothing about positions already open. This checks the same cap and
        tells the caller whether it's time to flatten everything, so a
        single bad session can't compound past the configured limit."""
        profile = get_trading_profile(trading_mode)
        daily_loss = float(getattr(account_snapshot, "daily_loss_percent", 0) or 0)
        weekly_loss = float(getattr(account_snapshot, "weekly_loss_percent", 0) or 0)
        breached = (daily_loss >= profile.max_daily_loss or weekly_loss >= profile.max_weekly_loss or drawdown_percent >= config.TRADING_MAX_DRAWDOWN_PERCENT or consecutive_losses >= config.TRADING_MAX_CONSECUTIVE_LOSSES)
        return {
            "triggered": breached,
            "daily_loss_percent": daily_loss,
            "max_daily_loss": profile.max_daily_loss,
            "weekly_loss_percent": weekly_loss,
            "max_weekly_loss": profile.max_weekly_loss,
            "drawdown_percent": drawdown_percent,
            "max_drawdown_percent": config.TRADING_MAX_DRAWDOWN_PERCENT,
            "consecutive_losses": consecutive_losses,
            "max_consecutive_losses": config.TRADING_MAX_CONSECUTIVE_LOSSES,
            "action": "FLATTEN_ALL_AND_HALT" if breached else "CONTINUE",
            "reason": (
                f"Daily loss {daily_loss:.2f}% >= limit {profile.max_daily_loss:.2f}%" if daily_loss >= profile.max_daily_loss else
                f"Weekly loss {weekly_loss:.2f}% >= limit {profile.max_weekly_loss:.2f}%" if weekly_loss >= profile.max_weekly_loss else
                f"Drawdown {drawdown_percent:.2f}% >= limit {config.TRADING_MAX_DRAWDOWN_PERCENT:.2f}%" if drawdown_percent >= config.TRADING_MAX_DRAWDOWN_PERCENT else
                f"Consecutive losses {consecutive_losses} >= limit {config.TRADING_MAX_CONSECUTIVE_LOSSES}" if consecutive_losses >= config.TRADING_MAX_CONSECUTIVE_LOSSES else
                "Within configured loss limits."
            ),
        }

    def flatten_all(self, account_mode: str = "demo") -> dict[str, Any]:
        """Close every open position immediately. Called when the kill
        switch trips, or on-demand as a manual 'stop trading now' action."""
        response = self.bridge.request("close_all_positions", {"account_mode": account_mode})
        log_event(
            40 if not response.get("success") else 30,
            "position_monitor.flatten_all",
            account_mode=account_mode,
            status=response.get("status"),
            closed=len(response.get("closed", [])),
            failed=len(response.get("failed", [])),
        )
        return response


position_monitor = PositionMonitor()
