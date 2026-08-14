import time
import json
import os
import pytest

from core.tool_registry import ToolSchema, GLOBAL_TOOL_REGISTRY
from core import execution_gateway
from core import tools as legacy_tools
from core import audit
from core import pending_actions

import brain.llm_interface as llm_interface
import brain.cognitive_loop as cog


def setup_module(module):
    # clear any existing test tools
    for k in list(GLOBAL_TOOL_REGISTRY.list()):
        if k.startswith("test."):
            # naive removal by reassigning internal dict
            GLOBAL_TOOL_REGISTRY._tools.pop(k, None)
    for k in list(legacy_tools.TOOL_REGISTRY.keys()):
        if k.startswith("test."):
            legacy_tools.TOOL_REGISTRY.pop(k, None)


def test_safe_tool_execution_and_audit(tmp_path):
    outputs = []

    def echo(msg):
        return f"echo:{msg}"

    schema = ToolSchema(name="test.echo", description="echo tool", parameters={"msg": "string"}, required=["msg"], param_types={"msg": "string"}, executor=echo)
    GLOBAL_TOOL_REGISTRY.register(schema)
    legacy_tools.TOOL_REGISTRY["test.echo"] = {"description": "echo", "parameters": {"msg": "string"}, "function": echo}

    res = execution_gateway.GATEWAY.execute("test.echo", {"msg": "hello"}, user_request="say hello", session_id="s1")
    assert res.success
    assert res.output == "echo:hello"

    # Check audit log contains an execute entry
    log = None
    try:
        with open(audit.AUDIT_LOG, "r", encoding="utf-8") as f:
            lines = f.read().strip().splitlines()
            log = lines[-1]
    except Exception:
        log = None
    assert log is not None and "execute" in log


def test_unknown_tool_and_validation_errors():
    # Unknown
    res = execution_gateway.GATEWAY.execute("test.unknown", {})
    assert not res.success
    assert "Unknown tool" in (res.error or "")

    # Missing required arg
    # reuse test.echo
    res2 = execution_gateway.GATEWAY.execute("test.echo", {})
    assert not res2.success
    assert "Missing required parameter" in (res2.error or "")

    # Type error
    res3 = execution_gateway.GATEWAY.execute("test.echo", {"msg": 123})
    assert not res3.success
    assert "must be string" in (res3.error or "")


def test_sensitive_tool_pending_and_confirmation(monkeypatch):
    # Define a sensitive tool
    def sensitive_action(code: str):
        return f"done:{code}"

    schema = ToolSchema(name="test.sensitive", description="sensitive", parameters={"code": "string"}, required=["code"], param_types={"code": "string"}, executor=sensitive_action, risk_level="SENSITIVE")
    GLOBAL_TOOL_REGISTRY.register(schema)
    legacy_tools.TOOL_REGISTRY["test.sensitive"] = {"description": "sensitive", "parameters": {"code": "string"}, "function": sensitive_action, "requires_confirmation": True}

    # Mock LLM to return a plan requesting the sensitive tool
    monkeypatch.setattr(llm_interface, "query_llm", lambda *a, **k: json.dumps({"tool": "test.sensitive", "args": {"code": "42"}}))

    resp = cog.resolve_user_query("please run sensitive task", session_id="sess_confirm")
    assert resp["source"] == "confirmation_required"
    plan_id = resp["details"]["plan_id"]

    # Confirm with wrong session should not execute
    resp_fail = cog.resolve_user_query("yes", session_id="other_session")
    assert resp_fail["source"] == "user" or resp_fail["source"] == "error"

    # Confirm with correct session
    resp2 = cog.resolve_user_query("yes", session_id="sess_confirm")
    assert resp2["source"] == "tool"
    outputs = resp2["answer"]
    assert isinstance(outputs, list)
    assert outputs[0]["success"] is True
    assert outputs[0]["output"] == "done:42"


def test_cancellation_and_expiry(monkeypatch):
    # Create a pending plan directly
    pid = "temp-plan-123"
    plan = {"id": pid, "calls": [{"tool": "test.echo", "args": {"msg": "bye"}}], "user_request": "do bye", "session_id": "sess_cancel"}
    pending_actions.add_pending(pid, plan, ttl_seconds=1)
    # Cancel
    resp = cog.resolve_user_query("no", session_id="sess_cancel")
    assert resp["source"] == "user"

    # Create and let expire
    pid2 = "temp-expire-1"
    plan2 = {"id": pid2, "calls": [{"tool": "test.echo", "args": {"msg": "later"}}], "user_request": "later", "session_id": "sess_exp"}
    pending_actions.add_pending(pid2, plan2, ttl_seconds=1)
    time.sleep(1.1)
    resp = cog.resolve_user_query("yes", session_id="sess_exp")
    # no pending to confirm -> error or no-op
    assert resp["source"] in ("error", "user")


def test_multi_tool_order_and_exception(monkeypatch):
    # register step tools
    def step1(x: str):
        return f"s1:{x}"

    def step2(x: str):
        return f"s2:{x}"

    def explode(x: str):
        raise RuntimeError("boom")

    GLOBAL_TOOL_REGISTRY.register(ToolSchema(name="test.step1", parameters={"x": "str"}, required=["x"], param_types={"x": "string"}, executor=step1))
    GLOBAL_TOOL_REGISTRY.register(ToolSchema(name="test.step2", parameters={"x": "str"}, required=["x"], param_types={"x": "string"}, executor=step2))
    GLOBAL_TOOL_REGISTRY.register(ToolSchema(name="test.explode", parameters={"x": "str"}, required=["x"], param_types={"x": "string"}, executor=explode))
    legacy_tools.TOOL_REGISTRY.update({
        "test.step1": {"description": "s1", "parameters": {"x": "str"}, "function": step1},
        "test.step2": {"description": "s2", "parameters": {"x": "str"}, "function": step2},
        "test.explode": {"description": "boom", "parameters": {"x": "str"}, "function": explode},
    })

    # Mock LLM to return multi-step plan without sensitive tools
    monkeypatch.setattr(llm_interface, "query_llm", lambda *a, **k: json.dumps([{"tool": "test.step1", "args": {"x": "a"}}, {"tool": "test.step2", "args": {"x": "b"}}]))
    resp = cog.resolve_user_query("run steps", session_id="sess_multi")
    assert resp["source"] == "tool"
    # include outputs ordered
    assert "s1:a" in resp["details"]["outputs"][0]["output"] or resp["details"]["outputs"][0]["output"] == "s1:a"

    # Plan with exception
    monkeypatch.setattr(llm_interface, "query_llm", lambda *a, **k: json.dumps([{"tool": "test.explode", "args": {"x": "now"}}]))
    resp2 = cog.resolve_user_query("explode", session_id="sess_ex")
    assert resp2["source"] == "tool"
    outputs = resp2["details"]["outputs"]
    assert outputs[0]["success"] is False
    assert "boom" in (outputs[0]["error"] or "")
