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
        "risk_percent": plan.get("risk_percent"),
        "risk_amount": plan.get("risk_amount"),
        "reward_to_risk": plan.get("reward_to_risk"),
        "execution": execution,
    }
    trades = read_trades(limit=1000)
    trades.append(entry)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trades, indent=2), encoding="utf-8")
    return entry
