"""Audit logging for tool executions.

Writes JSON lines to `logs/tool_audit.log` with structured entries.
"""
import json
import os
import time
from typing import Any, Dict
from core import config

AUDIT_LOG = os.path.join(getattr(config, "LOG_DIR", "."), "tool_audit.log")


def _ensure_log_dir():
    d = os.path.dirname(AUDIT_LOG)
    if d and not os.path.isdir(d):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


def record(entry: Dict[str, Any]):
    _ensure_log_dir()
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": int(time.time()), **entry}, ensure_ascii=False) + "\n")
    except Exception:
        # avoid raising during audit
        pass


def sample_entry(user_request: str, tool: str, args: Dict[str, Any], validation: Dict[str, Any], permission: Dict[str, Any], result: Dict[str, Any]):
    return {
        "user_request": user_request,
        "tool": tool,
        "args": args,
        "validation": validation,
        "permission": permission,
        "result": result,
    }
