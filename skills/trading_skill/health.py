"""Read-only trading hub health diagnostics.

This module never places, modifies, or closes a trade. It checks the runtime
dependencies and reports PASS/WARN/FAIL/UNKNOWN with actionable details.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core import config


def _status(ok: bool | None, detail: str, value: Any = None) -> dict[str, Any]:
    return {"status": "PASS" if ok is True else "FAIL" if ok is False else "UNKNOWN", "detail": detail, "value": value}


def trading_hub_health(account_mode: str = "demo", symbol: str | None = None, trading_mode: str = "DAY_TRADING") -> dict[str, Any]:
    """Run safe diagnostics against the trading stack.

    No order, modify, close, or execution operation is performed.
    """
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_mode": account_mode,
        "trading_mode": trading_mode,
        "symbol": symbol or config.DEFAULT_TRADING_SYMBOL,
        "checks": {},
    }

    try:
        from .bridge import WineBridgeClient
        from .account_manager import account_manager
        from .profiles import get_trading_profile
        from .universe import eligible_symbols
        from .protection import drawdown_percent, consecutive_losses
        bridge = WineBridgeClient()
        ping = bridge.request("ping", {"account_mode": account_mode})
        report["checks"]["bridge"] = _status(bool(ping and ping.get("status") not in {"error", "disconnected"}), str(ping.get("error") or ping.get("status") or "Bridge responded."), ping)

        account_result = account_manager.get_snapshot(account_mode, force_refresh=True)
        report["checks"]["account"] = _status(account_result.connected, account_result.error or "Account connected.", account_result.login)
        report["account"] = {
            "login": account_result.login, "actual_mode": account_result.actual_mode,
            "broker": account_result.broker, "platform": account_result.platform,
            "balance": account_result.balance, "equity": account_result.equity,
            "free_margin": account_result.free_margin, "leverage": account_result.leverage,
            "daily_loss_percent": account_result.daily_loss_percent,
            "weekly_loss_percent": account_result.weekly_loss_percent,
            "drawdown_percent": account_result.drawdown_percent,
            "consecutive_losses": account_result.consecutive_losses,
        }

        requested = symbol or config.DEFAULT_TRADING_SYMBOL
        symbols = bridge.request("symbols", {"account_mode": account_mode})
        available = symbols.get("symbols", []) if isinstance(symbols, dict) else []
        report["checks"]["symbols"] = _status(bool(available), f"{len(available)} symbols returned." if available else "No broker symbols returned.", len(available))
        from .symbols import resolve
        resolved = resolve(requested, available) if available else None
        report["checks"]["symbol_resolution"] = _status(bool(resolved), f"{requested} -> {resolved}" if resolved else f"Unable to resolve {requested}.", resolved)

        profile = get_trading_profile(trading_mode)
        report["profile"] = profile.as_dict()
        report["checks"]["profile"] = _status(True, f"Loaded {profile.mode.value} profile.")

        if resolved:
            count = max(profile.candle_count(tf) for tf in profile.required_timeframes)
            market = bridge.request("market", {"symbol": resolved, "account_mode": account_mode, "timeframes": list(profile.required_timeframes), "count": count})
            timeframes = market.get("timeframes", {}) if isinstance(market, dict) else {}
            missing = [tf for tf in profile.required_timeframes if not timeframes.get(tf)]
            report["checks"]["market_data"] = _status(not missing and bool(market.get("bid")) and bool(market.get("ask")), "Required market data present." if not missing else f"Missing timeframes: {', '.join(missing)}", {"missing": missing, "bid": market.get("bid"), "ask": market.get("ask")})

            try:
                from .analysis import analyze_structure
                analysis = analyze_structure(timeframes, profile=profile)
                report["analysis"] = analysis
                report["checks"]["analysis_engine"] = _status(analysis.get("valid") is not False, str(analysis.get("reason", analysis.get("decision", "Analysis completed."))), analysis.get("decision"))
            except Exception as exc:
                report["checks"]["analysis_engine"] = _status(False, f"Analysis failed: {exc}")

        try:
            dd = drawdown_percent(account_result.login or 0, account_result.equity)
            report["checks"]["protection"] = _status(True, "Protection state readable.", {"drawdown_percent": dd, "max_drawdown_percent": config.TRADING_MAX_DRAWDOWN_PERCENT, "max_consecutive_losses": config.TRADING_MAX_CONSECUTIVE_LOSSES})
        except Exception as exc:
            report["checks"]["protection"] = _status(False, f"Protection check failed: {exc}")

    except Exception as exc:
        report["checks"]["runtime"] = _status(False, f"Health check failed: {exc}")

    critical = ["bridge", "account", "symbols", "symbol_resolution", "market_data", "analysis_engine", "protection"]
    statuses = [report["checks"].get(k, {}).get("status", "UNKNOWN") for k in critical]
    if "FAIL" in statuses:
        overall = "FAILED"
    elif "UNKNOWN" in statuses or "WARN" in statuses:
        overall = "DEGRADED"
    else:
        overall = "HEALTHY"
    report["overall"] = overall
    return report
