"""Persistent store for pending plans that require explicit confirmation.

The pending-plan service owns the pending plan state, TTL enforcement, session
ownership checks, and revalidation before execution. The cognitive loop should
not maintain this state itself.
"""
import json
import os
import time
from typing import Any, Dict, Optional

STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "pending_plans.json")


def _ensure_store_dir():
    d = os.path.dirname(STORE_PATH)
    if d and not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


def _read_store() -> Dict[str, Any]:
    _ensure_store_dir()
    try:
        if not os.path.exists(STORE_PATH):
            return {}
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_store(data: Dict[str, Any]):
    _ensure_store_dir()
    try:
        with open(STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def add_pending(plan_id: str, plan: Dict[str, Any], ttl_seconds: int = 3600):
    store = _read_store()
    store[plan_id] = {"plan": plan, "ts": int(time.time()), "ttl": ttl_seconds}
    _write_store(store)


def get_pending(plan_id: str) -> Optional[Dict[str, Any]]:
    store = _read_store()
    entry = store.get(plan_id)
    if not entry:
        return None
    if int(time.time()) - entry.get("ts", 0) >= entry.get("ttl", 0):
        store.pop(plan_id, None)
        _write_store(store)
        return None
    return entry["plan"]


def confirm_and_remove(plan_id: str) -> Optional[Dict[str, Any]]:
    store = _read_store()
    entry = store.pop(plan_id, None)
    _write_store(store)
    if not entry:
        return None
    return entry.get("plan")


def find_pending_for_session(session_id: str) -> Dict[str, Dict[str, Any]]:
    store = _read_store()
    results = {}
    changed = False
    for pid, entry in list(store.items()):
        if int(time.time()) - entry.get("ts", 0) >= entry.get("ttl", 0):
            store.pop(pid, None)
            changed = True
            continue
        plan = entry.get("plan") or {}
        if plan.get("session_id") == session_id:
            results[pid] = plan
    if changed:
        _write_store(store)
    return results


class PendingPlanService:
    def create(self, session_id: str, user_request: str, tool_steps: list, risk_info: dict | None = None, ttl_seconds: int = 600):
        plan_id = str(int(time.time() * 1000)) + "-" + str(len(tool_steps))
        plan = {
            "plan_id": plan_id,
            "session_id": session_id,
            "user_request": user_request,
            "steps": tool_steps,
            "created_at": time.time(),
            "expires_at": time.time() + ttl_seconds,
            "risk_info": risk_info or {},
            "confirmation_status": "pending",
        }
        add_pending(plan_id, plan, ttl_seconds=ttl_seconds)
        return plan

    def get_for_session(self, session_id: str):
        return find_pending_for_session(session_id)

    def get(self, plan_id: str):
        return get_pending(plan_id)

    def confirm(self, plan_id: str, session_id: str):
        plan = get_pending(plan_id)
        if not plan:
            return None
        if plan.get("session_id") != session_id:
            return None
        expires_at = plan.get("expires_at")
        if expires_at is not None and time.time() > float(expires_at):
            self.delete(plan_id)
            return None
        plan["confirmation_status"] = "approved"
        return plan

    def delete(self, plan_id: str):
        store = _read_store()
        store.pop(plan_id, None)
        _write_store(store)


PENDING_PLAN_SERVICE = PendingPlanService()

