from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core import config


def _path() -> Path:
    return Path(config.TRADING_JOURNAL_PATH)


def read_trades(limit: int = 20) -> list[dict[str, Any]]:
    path = _path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data[-limit:] if isinstance(data, list) else []


def record_trade(plan: dict[str, Any], execution: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "symbol": plan.get("mt5_symbol", plan.get("symbol")),
        "direction": plan.get("direction"),
        "entry": plan.get("entry"),
        "stop_loss": plan.get("stop_loss"),
        "take_profit": plan.get("take_profit"),
        "volume": plan.get("volume"),
        "actual_volume": execution.get("volume", execution.get("actual_volume", plan.get("volume"))),
        "risk_percent": plan.get("risk_percent"),
        "risk_amount": plan.get("risk_amount"),
        "reward_to_risk": plan.get("reward_to_risk"),
        "trading_mode": plan.get("trading_mode", "DAY_TRADING"),
        "profile": plan.get("profile", {}),
        "smc_analysis": plan.get("smc_analysis", {}),
        "news_context": plan.get("news_context", {}),
        "risk": {
            "risk_percent": plan.get("risk_percent"),
            "risk_amount": plan.get("risk_amount"),
            "margin_required": plan.get("margin_required"),
            "actual_risk_amount": plan.get("actual_risk_amount"),
        },
        "equity_at_decision": plan.get("equity_at_decision", plan.get("equity")),
        "estimated_swap_cost": plan.get("estimated_swap_cost"),
        "weekend_exposure": plan.get("weekend_exposure", False),
        "expected_hold_days": plan.get("expected_hold_days", 1),
        "spread": {
            "price": plan.get("spread_price"),
            "points": plan.get("spread_points"),
            "pips": plan.get("spread_pips"),
        },
        "result": execution.get("result", execution.get("status")),
        "reason": execution.get("reason", execution.get("message")),
        "execution": execution,
    }
    trades = read_trades(limit=1000)
    trades.append(entry)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trades, indent=2), encoding="utf-8")
    return entry
