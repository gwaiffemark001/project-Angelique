from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from core import config

STATE_PATH = Path(config.DATA_DIR) / "trading_protection_state.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def _save(state: dict[str, Any]) -> None:
    tmp=STATE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_PATH)


def update_peak_equity(login: int, equity: float) -> dict[str, Any]:
    state=_load()
    key=str(login)
    row=state.get(key,{})
    peak=max(float(row.get("peak_equity",0) or 0), float(equity or 0))
    row["peak_equity"]=peak
    row["updated_at"]=datetime.now(timezone.utc).isoformat()
    state[key]=row
    _save(state)
    return row


def drawdown_percent(login: int, equity: float) -> float:
    if not login or equity<=0: return 0.0
    row=update_peak_equity(login,equity)
    peak=float(row.get("peak_equity",0) or 0)
    return max(0.0,(peak-equity)/peak*100) if peak>0 else 0.0


def consecutive_losses(deals: list[dict[str,Any]]) -> int:
    count=0
    for deal in sorted(deals,key=lambda d: str(d.get("time") or d.get("timestamp") or ""), reverse=True):
        profit=float(deal.get("profit",0) or 0)+float(deal.get("commission",0) or 0)+float(deal.get("swap",0) or 0)
        if profit < 0: count+=1
        elif profit > 0: break
    return count
