from __future__ import annotations

from datetime import datetime, timezone

from .account_manager import account_manager
from .compat import build_default_workflow
from .journal import record_trade
from .event_logging import log_event
from .position_monitor import position_monitor
from .profiles import get_trading_profile
from .universe import eligible_symbols
from .protection import drawdown_percent, consecutive_losses
from .trading_notifier import notify
from core import config

_workflows = {}
_current_mode = "DAY_TRADING"
_auto_execution_blocked_until = {}


def workflow(trading_mode: str | None = None):
    """Return an isolated workflow instance for the requested strategy mode.

    Separate instances prevent a DEMO/LIVE or DAY/SWING signal worker from
    mutating shared workflow state while another worker is running.
    """
    from .profiles import normalize_trading_mode
    mode = normalize_trading_mode(trading_mode or _current_mode).value
    if mode not in _workflows:
        _workflows[mode] = build_default_workflow(trading_mode=mode)
    return _workflows[mode]


def set_trading_mode(trading_mode: str):
    global _current_mode
    from .profiles import normalize_trading_mode
    mode = normalize_trading_mode(trading_mode).value
    _current_mode = mode
    return workflow(mode).profile.as_dict()


def auto_execution_enabled(account_mode: str = "demo") -> bool:
    mode = str(account_mode or "demo").strip().lower()
    if mode in {"live", "real"}:
        return bool(config.TRADING_AUTO_EXECUTION and getattr(config, "TRADING_LIVE_AUTO_EXECUTION", False))
    return bool(config.TRADING_AUTO_EXECUTION)


def get_account_snapshot(account_mode: str = "demo", force_refresh: bool = False):
    authorized, message, snapshot = account_manager.validate_authorization(account_mode)
    if force_refresh:
        snapshot = account_manager.get_snapshot(account_mode, True)
    return {"authorized": authorized, "message": message, "snapshot": snapshot}


def get_open_positions(account_mode: str = "demo", symbol: str | None = None):
    return position_monitor.get_open_positions(account_mode, symbol)


def monitor_positions(account_mode: str = "demo", symbol: str | None = None, market_by_symbol: dict | None = None):
    return position_monitor.monitor_once(account_mode, symbol, market_by_symbol)


def enforce_loss_limits(account_mode: str = "demo", trading_mode: str = "DAY_TRADING"):
    """Call this before every scan/monitor cycle. If the daily or weekly
    loss cap has been breached, this flattens every open position and
    reports what happened, instead of just quietly refusing new trades."""
    snapshot_result = get_account_snapshot(account_mode, force_refresh=True)
    snapshot = snapshot_result["snapshot"]
    if not snapshot.connected:
        return {"triggered": False, "action": "SKIPPED", "reason": "Account not connected."}
    dd = drawdown_percent(snapshot.login or 0, snapshot.equity) if snapshot.connected else 0.0
    recent = {}
    recent_reader = getattr(workflow(trading_mode).adapter, "recent_deals", None)
    if callable(recent_reader):
        try:
            recent = recent_reader(account_mode, minutes=60 * 24 * 7) or {}
        except Exception as exc:
            log_event(30, "service.kill_switch_recent_deals_failed", account_mode=account_mode, error=str(exc))
    losses = consecutive_losses(recent.get("deals", []) if isinstance(recent, dict) else [])
    check = position_monitor.check_kill_switch(snapshot, trading_mode, drawdown_percent=dd, consecutive_losses=losses)
    if not check["triggered"]:
        return check
    log_event(40, "service.kill_switch_triggered", account_mode=account_mode, reason=check["reason"])
    flatten_result = position_monitor.flatten_all(account_mode)
    return {**check, "flatten_result": flatten_result}


def close_position_manual(ticket: int, symbol: str, account_mode: str = "demo"):
    """Close exactly one open position. Backs the GUI's 'close this
    position' button."""
    return position_monitor.close_single(ticket, symbol, account_mode)


def close_all_positions_manual(account_mode: str = "demo"):
    """Close every open position immediately. Backs the GUI's
    'close all positions' button, and is the same call the daily-loss
    kill switch uses internally."""
    return position_monitor.flatten_all(account_mode)


def run_position_management(account_mode: str = "demo", trading_mode: str = "DAY_TRADING"):
    """Run one safe post-trade management pass for all open positions."""
    from .analysis import analyze_structure
    from .data_quality import assess_candles

    active = workflow(trading_mode)
    profile = get_trading_profile(trading_mode)
    loss_guard = enforce_loss_limits(account_mode, trading_mode)
    if loss_guard.get("triggered"):
        return {
            "status": "HALTED",
            "state": "KILL_SWITCH_TRIGGERED",
            "loss_guard": loss_guard,
            "positions": loss_guard.get("flatten_result", {}).get("closed", []),
            "applied": [],
        }

    positions_response = position_monitor.get_open_positions(account_mode)
    if positions_response.get("status") == "error":
        return positions_response

    market_by_symbol: dict[str, dict] = {}
    for position in positions_response.get("positions", []):
        symbol = position.get("symbol")
        if not symbol or symbol in market_by_symbol:
            continue
        entry: dict = {"data_quality": "unavailable", "data_quality_reason": "Fresh market data has not been validated."}
        direction = "SELL" if str(position.get("type", position.get("direction", "BUY"))).upper() == "SELL" else "BUY"
        try:
            required = profile.analysis_required_timeframes
            count = max(profile.candle_count(tf) for tf in required)
            raw_market = active.adapter.market(symbol, required, account_mode, count)
            timeframes = raw_market.get("timeframes", {}) or {}
            from core.price_units import normalize_spread, spread_policy
            specs = dict(raw_market.get("symbol_specs", {}) or {})
            specs.setdefault("bid", raw_market.get("bid")); specs.setdefault("ask", raw_market.get("ask")); specs.setdefault("trading_mode", profile.mode.value)
            normalized = normalize_spread(symbol, float(raw_market.get("spread") or 0), specs) if raw_market.get("spread") is not None else {}
            policy = spread_policy(symbol, specs, profile.mode.value)
            entry["price"] = raw_market.get("bid") if direction == "SELL" else raw_market.get("ask")
            entry["spread_pips"] = raw_market.get("spread_pips")
            entry["spread_points"] = raw_market.get("spread_points")
            entry["spread_unit"] = normalized.get("spread_unit") or raw_market.get("spread_unit")
            entry["spread_ticks"] = normalized.get("spread_ticks")
            entry["instrument_class"] = normalized.get("instrument_class") or policy.get("instrument_class")
            entry["maximum_spread_value"] = policy.get("max_value")
            entry["maximum_spread_unit"] = policy.get("max_unit")
            entry["maximum_spread_price"] = policy.get("max_price")

            quality = {tf: assess_candles(timeframes.get(tf, []), tf) for tf in required}
            quality_ok = bool(raw_market.get("bid") and raw_market.get("ask")) and not raw_market.get("stale") and not raw_market.get("error") and all(item.get("status") == "fresh" for item in quality.values())
            if not quality_ok:
                bad = [f"{tf}: {item.get('status')}" for tf, item in quality.items() if item.get("status") != "fresh"]
                entry["data_quality"] = "stale" if raw_market.get("stale") else "unavailable"
                entry["data_quality_reason"] = raw_market.get("error") or ("; ".join(bad) if bad else "Fresh bid/ask or candle data is unavailable.")
            else:
                analysis = analyze_structure(timeframes, profile=profile, registry=active._zone_registry)
                entry_tf = timeframes.get(profile.entry_timeframe, []) or []
                indicators = (analysis.get("indicators") or {}).get(profile.entry_timeframe, {}) if isinstance(analysis, dict) else {}
                entry["atr"] = indicators.get("atr_14")
                entry["data_quality"] = "fresh"
                entry["data_quality_reason"] = "Fresh closed-candle market data validated."

                opposite_decision = "SELL_PLAN_READY" if direction == "BUY" else "BUY_PLAN_READY"
                invalidated = bool(analysis.get("valid") and analysis.get("decision") == opposite_decision)
                entry["setup_invalidated"] = invalidated
                entry["invalidation_reason"] = (
                    f"An opposing, complete setup has formed: {analysis.get('reason', '')}" if invalidated else None
                )
                if entry["atr"] is None and len(entry_tf) >= 15:
                    ranges = []
                    previous_close = None
                    for candle in entry_tf[-30:]:
                        high = float(candle.get("high", 0) or 0)
                        low = float(candle.get("low", 0) or 0)
                        close = float(candle.get("close", 0) or 0)
                        if high <= 0 or low <= 0 or close <= 0:
                            continue
                        ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)) if previous_close is not None else high - low)
                        previous_close = close
                    entry["atr"] = sum(ranges[-14:]) / len(ranges[-14:]) if ranges[-14:] else None
        except Exception as exc:
            entry["data_quality"] = "error"
            entry["data_quality_reason"] = f"Position-management market lookup failed: {exc}"
            log_event(30, "service.position_management.market_lookup_failed", symbol=symbol, error=str(exc))
        market_by_symbol[symbol] = entry

    return position_monitor.apply_management(account_mode, market_by_symbol)


def decide_and_act(
    account_mode: str = "demo",
    trading_mode: str = "DAY_TRADING",
    allowed_symbols: list[str] | None = None,
):
    """One full autopilot cycle. Scans for a plan; every gate (setup
    completeness, risk, margin, spread, minimum RR, portfolio limits,
    daily/weekly loss caps) has already run by the time scan_universe
    returns a plan. News can require explicit approval, and automatic
    execution is restricted to configured ICT kill zones. A plan flagged
    requires_manual_approval (a
    high-impact calendar event is present), in which case it's returned as
    PENDING_APPROVAL for the GUI to surface for explicit sign-off."""
    mode_key = str(account_mode or "demo").strip().lower()
    blocked_until = float(_auto_execution_blocked_until.get(mode_key, 0.0) or 0.0)
    import time
    if blocked_until > time.time():
        return {
            "state": "BROKER_TRADING_DISABLED",
            "candidates": [],
            "opportunity": None,
            "execution": {"state": "BLOCKED", "message": "Automatic execution is temporarily paused because MT5 reported trading is disabled. Enable trading in MT5 and retry."},
        }

    scan = scan_universe(account_mode, trading_mode, allowed_symbols=allowed_symbols)
    if scan["state"] != "OPPORTUNITY_FOUND":
        return scan

    opportunity = scan["opportunity"]
    plan = opportunity["plan"]
    if plan.get("requires_manual_approval"):
        notify("MANUAL_APPROVAL_REQUIRED", plan)
        return {**scan, "state": "PENDING_APPROVAL", "execution": {"state": "MANUAL_APPROVAL_REQUIRED", "reason": plan.get("manual_approval_reason", "News interference requires approval."), "plan": plan}}

    confirmation_phrase = plan.get("confirmation_phrase")
    # Kill-zone timing is an auto-execution gate only. A human-approved plan
    # can still be executed deliberately outside the prime window.
    if getattr(config, "TRADING_KILL_ZONE_ENFORCED", True):
        try:
            from skills.trading.ict_core import get_kill_zone_status
            status, zone_name = get_kill_zone_status(datetime.now(timezone.utc))
            if status != "ACTIVE":
                return {**scan, "state": "KILL_ZONE_BLOCKED", "execution": {"state": "AUTO_BLOCKED_KILL_ZONE", "reason": "Automatic execution is restricted to an ICT kill zone.", "zone": zone_name, "plan": plan}}
        except Exception as exc:
            return {**scan, "state": "KILL_ZONE_BLOCKED", "execution": {"state": "AUTO_BLOCKED_KILL_ZONE", "reason": f"Kill-zone validation failed safely closed: {exc}", "plan": plan}}
    if not auto_execution_enabled(account_mode):
        return {**scan, "state": "PENDING_APPROVAL", "execution": {"state": "APPROVAL_REQUIRED", "reason": "Automatic execution is disabled for this account mode.", "message": f"Automatic execution is disabled for {account_mode.upper()} mode.", "plan": plan}}
    result = execute_trade(confirmation_phrase)
    failure = str(result.details.get("reason") or result.message or "").lower() if isinstance(result.details, dict) else str(result.message or "").lower()
    if result.state.value == "EXECUTED":
        _auto_execution_blocked_until.pop(mode_key, None)
    elif "trading is disabled" in failure or "trade disabled" in failure or "autotrading" in failure:
        import time
        _auto_execution_blocked_until[mode_key] = time.time() + 60.0
    return {
        **scan,
        "state": "AUTO_EXECUTED" if result.state.value == "EXECUTED" else f"AUTO_EXECUTE_FAILED:{result.state.value}",
        "execution": {
            "state": result.state.value,
            "message": result.message,
            "plan": result.plan.as_dict() if result.plan else plan,
            "details": result.details,
        },
    }


def prepare_trade(symbol: str, account_mode: str = "demo", trading_mode: str = "DAY_TRADING"):
    return workflow(trading_mode).prepare(symbol, account_mode)


def prepare_trade_payload(symbol: str, account_mode: str = "demo", risk_percent: float | None = None, trading_mode: str = "DAY_TRADING"):
    """Compatibility payload wrapper using the caller's trading mode.

    Compatibility wrapper. The trading engine enforces the single 1% risk policy;
    a caller-supplied risk_percent other than 1% is rejected by the workflow.
    """
    active = workflow(trading_mode)
    previous_risk = active.risk_percent
    if risk_percent is not None:
        active.risk_percent = risk_percent
    try:
        result = active.prepare(symbol, account_mode)
    finally:
        active.risk_percent = previous_risk
    return {
        "state": result.state.value,
        "decision_state": result.decision_state,
        "message": result.message,
        "plan": result.plan.as_dict() if result.plan else None,
        "details": result.details,
    }


def _find_workflow_for_plan(confirmation_phrase: str):
    for active in list(_workflows.values()):
        if confirmation_phrase in getattr(active, "_plans", {}):
            return active
    return None


def approve_trade(confirmation_phrase: str):
    active = _find_workflow_for_plan(confirmation_phrase)
    if active is None:
        from .models import WorkflowResult, WorkflowState
        return WorkflowResult(WorkflowState.REJECTED, "Approval rejected: no current plan matches the confirmation phrase.")
    return active.approve(confirmation_phrase)


def execute_trade(confirmation_phrase: str):
    active = _find_workflow_for_plan(confirmation_phrase)
    if active is None:
        from .models import WorkflowResult, WorkflowState
        return WorkflowResult(WorkflowState.REJECTED, "Execution rejected: no current plan matches the confirmation phrase.", details={"failure_stage": "plan_lookup"})
    result = active.execute(confirmation_phrase)
    if result.plan is not None and result.state.value in {"EXECUTED", "REJECTED", "EXPIRED", "EXECUTING"}:
        if result.state.value == "EXECUTED":
            notify("TRADE_EXECUTED", result.plan.as_dict())
        elif result.state.value == "EXECUTING" and "VERIFICATION_PENDING" in result.message:
            notify("EXECUTION_VERIFICATION_PENDING", result.plan.as_dict())
        elif result.state.value == "REJECTED":
            notify("TRADE_FAILED", result.plan.as_dict())
        record_trade(
            result.plan.as_dict(),
            {**(result.details or {}), "status": result.state.value, "message": result.message},
        )
    return result


def scan_universe(
    account_mode: str = "demo",
    trading_mode: str = "DAY_TRADING",
    allowed_symbols: list[str] | None = None,
):
    kill_switch = enforce_loss_limits(account_mode, trading_mode)
    if kill_switch.get("triggered"):
        return {
            "state": "HALTED_LOSS_LIMIT",
            "candidates": [],
            "scanned": 0,
            "kill_switch": kill_switch,
        }
    active = workflow(trading_mode)
    available = active.adapter.symbols(account_mode)
    candidates = eligible_symbols(available)
    if allowed_symbols is not None:
        allowed = {str(symbol).strip().upper() for symbol in allowed_symbols if str(symbol).strip()}
        candidates = [
            symbol for symbol in candidates
            if symbol.upper() in allowed or any(symbol.upper().startswith(a) or a.startswith(symbol.upper()) for a in allowed)
        ]
    results = []
    opportunities = []
    for symbol in candidates:
        result = active.prepare(symbol, account_mode)
        entry = {
            "symbol": symbol,
            "state": result.state.value,
            "message": result.message,
            "result": result,
        }
        results.append(entry)
        if result.plan is not None:
            analysis = (result.details or {}).get("analysis", {})
            score = float((analysis.get("confluence") or {}).get("score", 0) or 0)
            opportunities.append((score, entry, result))
    if opportunities:
        _, entry, result = max(opportunities, key=lambda item: item[0])
        return {
            "state": "OPPORTUNITY_FOUND",
            "candidates": candidates,
            "scanned": len(results),
            "opportunities_found": len(opportunities),
            "opportunities": [r.plan.as_dict() for _,_,r in opportunities],
            "results": results,
            "opportunity": {
                "state": result.state.value,
                "message": result.message,
                "plan": result.plan.as_dict(),
                "account": result.account,
                "market": result.market,
                "details": result.details,
                "candidate": entry,
            },
        }
    return {"state": "WAITING", "candidates": candidates, "scanned": len(results), "results": results, "opportunities_found": 0}


def scan_report(account_mode: str = "demo", trading_mode: str = "DAY_TRADING", allowed_symbols: list[str] | None = None):
    """Human-readable breakdown of exactly why each symbol did or didn't
    produce a trade plan on this scan: which gate stopped it (data,
    trend alignment, confluence score, news, risk) and the reason given
    at that gate. This is the diagnostic the workflow doesn't surface by
    default -- 'WAITING' alone doesn't tell you what it's waiting for."""
    scan = scan_universe(account_mode, trading_mode, allowed_symbols=allowed_symbols)
    if scan["state"] == "HALTED_LOSS_LIMIT":
        return {"state": scan["state"], "kill_switch": scan["kill_switch"], "rows": []}
    rows = []
    for entry in scan.get("results", []):
        result = entry["result"]
        details = result.details or {}
        analysis = details.get("analysis", {})
        confluence = analysis.get("confluence", {})
        rows.append({
            "symbol": entry["symbol"],
            "state": entry["state"],
            "reason": entry["message"],
            "trends": analysis.get("trends"),
            "confluence_score": confluence.get("score"),
            "confluence_minimum": confluence.get("minimum_score"),
            "setup_model": analysis.get("setup_assessment", {}).get("model"),
            "setup_missing": analysis.get("setup_assessment", {}).get("missing"),
            "data_blockers": details.get("data_blockers"),
        })
    if scan["state"] == "OPPORTUNITY_FOUND":
        opp = scan["opportunity"]
        rows.append({
            "symbol": opp["candidate"]["symbol"],
            "state": opp["state"],
            "reason": opp["message"],
            "trends": opp["details"].get("analysis", {}).get("trends"),
            "confluence_score": opp["details"].get("confluence", {}).get("score"),
            "confluence_minimum": opp["details"].get("confluence", {}).get("minimum_score"),
            "setup_model": None,
            "setup_missing": None,
            "data_blockers": None,
        })
    return {"state": scan["state"], "scanned": scan.get("scanned", 0), "rows": rows}


def monitor_universe(
    account_mode: str = "demo",
    trading_mode: str = "DAY_TRADING",
    allowed_symbols: list[str] | None = None,
):
    scan = scan_universe(account_mode, trading_mode, allowed_symbols=allowed_symbols)
    if scan["state"] != "OPPORTUNITY_FOUND":
        log_event(20, "service.monitor_universe.waiting", account_mode=account_mode, scanned=scan["scanned"])
        return scan

    opportunity = scan["opportunity"]
    from brain.cognitive_loop import review_market_opportunity

    candidate = {
        "symbol": opportunity["candidate"]["symbol"],
        "plan": opportunity["plan"],
        "market": opportunity["market"],
        "analysis": opportunity["details"].get("analysis", {}),
    }
    review = review_market_opportunity(candidate)
    if review["decision"] != "PLAN":
        log_event(20, "service.monitor_universe.review_rejected", account_mode=account_mode, symbol=candidate["symbol"], decision=review["decision"])
        opportunity["brain_review"] = review
        return {**scan, "state": "WAITING", "opportunity": opportunity}

    log_event(20, "service.monitor_universe.opportunity_confirmed", account_mode=account_mode, symbol=candidate["symbol"], decision=review["decision"])
    return {
        "state": "OPPORTUNITY_FOUND",
        "candidates": scan["candidates"],
        "scanned": scan["scanned"],
        "opportunity": {**opportunity, "brain_review": review},
    }
