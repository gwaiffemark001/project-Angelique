"""Central ExecutionGateway for validated, auditable tool execution.

This is the only runtime execution boundary. Execution must validate the tool
call against GLOBAL_TOOL_REGISTRY before any executor runs, and it must enforce
confirmation policy centrally.
"""
import inspect
import threading
import time
from typing import Any, Dict, Optional, Tuple

from core.tool_registry import GLOBAL_TOOL_REGISTRY
from core import audit
from core.pending_actions import PENDING_PLAN_SERVICE


class ExecutionResult:
    def __init__(self, success: bool, output: Any = None, error: Optional[str] = None, timed_out: bool = False):
        self.success = success
        self.output = output
        self.error = error
        self.timed_out = timed_out


class ExecutionGateway:
    def __init__(self):
        self.registry = GLOBAL_TOOL_REGISTRY

    def _validate(self, name: str, args: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        valid, errors = self.registry.validate_call(name, args or {})
        return valid, {"errors": errors}

    def _permission_check(self, name: str, args: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        schema = self.registry.get(name)
        info = {"requires_confirmation": False, "permission": "allowed", "risk_level": "SAFE"}
        if schema:
            info["risk_level"] = schema.risk_level
            info["requires_confirmation"] = schema.requires_confirmation()
            info["permission"] = "allowed" if schema.permissions in (None, []) else "granted"
        return True, info

    def _run_callable(self, func, args: Dict[str, Any], result_container: Dict[str, Any]):
        try:
            if args is None:
                args = {}
            try:
                sig = inspect.signature(func)
                accepts_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values())
                valid_args = args if accepts_kwargs else {k: v for k, v in (args or {}).items() if k in sig.parameters}
            except Exception:
                valid_args = args
            result_container["output"] = func(**(valid_args or {}))
            result_container["success"] = True
        except Exception as e:
            result_container["success"] = False
            result_container["error"] = str(e)

    def create_pending(self, session_id: str, user_request: str, steps: list, risk_info: dict | None = None, ttl_seconds: int = 600):
        return PENDING_PLAN_SERVICE.create(session_id, user_request, steps, risk_info=risk_info or {}, ttl_seconds=ttl_seconds)

    def confirm(self, plan_id: str, session_id: str):
        plan = PENDING_PLAN_SERVICE.confirm(plan_id, session_id)
        if not plan:
            return None
        steps = plan.get("calls", plan.get("steps", []))
        outputs = []
        for step in steps:
            name = step.get("tool")
            args = step.get("args", {}) or {}
            result = self.execute(name, args, user_request=plan.get("user_request"), session_id=session_id)
            outputs.append({"tool": name, "success": result.success, "output": result.output, "error": result.error})
        # Remove the pending plan after successful confirmation+execution
        try:
            PENDING_PLAN_SERVICE.delete(plan_id)
        except Exception:
            pass
        return {"plan_id": plan_id, "session_id": session_id, "outputs": outputs, "status": "approved_and_executed"}

    def execute(self, name: str, args: Optional[Dict[str, Any]] = None, user_request: Optional[str] = None, session_id: Optional[str] = None, timeout: Optional[float] = None) -> ExecutionResult:
        args = args or {}
        schema = self.registry.get(name)
        if schema is None:
            audit.record({"action": "tool_not_found", "tool": name, "session_id": session_id, "user_request": user_request})
            return ExecutionResult(False, error=f"Unknown tool: {name}")

        valid, validation = self._validate(name, args)
        if not valid:
            audit.record({
                "action": "validate_fail",
                "tool": name,
                "args": args,
                "validation": validation,
                "session_id": session_id,
                "user_request": user_request,
            })
            return ExecutionResult(False, error=f"Validation failed: {validation.get('errors')}")

        allowed, permission = self._permission_check(name, args)
        if not allowed:
            audit.record({"action": "permission_denied", "tool": name, "permission": permission, "session_id": session_id, "user_request": user_request})
            return ExecutionResult(False, error="PermissionDenied")

        func = schema.executor
        if not callable(func):
            audit.record({"action": "executor_not_found", "tool": name, "session_id": session_id, "user_request": user_request})
            return ExecutionResult(False, error=f"Executor for tool '{name}' not found")

        container = {}
        thread = threading.Thread(target=self._run_callable, args=(func, args, container), daemon=True)
        thread.start()
        start = time.time()
        thread.join(timeout)
        timed_out = False
        if thread.is_alive():
            timed_out = True
            audit.record({"action": "timeout", "tool": name, "args": args, "session_id": session_id, "user_request": user_request, "timeout": timeout})
            return ExecutionResult(False, error="ExecutionTimeout", timed_out=True)

        duration = time.time() - start
        success = bool(container.get("success"))
        output = container.get("output")
        error = container.get("error")

        audit.record({
            "action": "execute",
            "tool": name,
            "args": args,
            "session_id": session_id,
            "user_request": user_request,
            "validation": validation,
            "permission": permission,
            "success": success,
            "error": error,
            "duration": duration,
        })
        return ExecutionResult(success, output=output, error=error, timed_out=timed_out)


GATEWAY = ExecutionGateway()
