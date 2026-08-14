import pytest
from core.tool_registry import GLOBAL_TOOL_REGISTRY, ToolSchema, ValidationError


def test_register_and_get():
    tr = GLOBAL_TOOL_REGISTRY
    # ensure unique test tool name
    name = "__test_tool_registry_dummy__"
    # unregister if present
    try:
        existing = tr.get(name)
        if existing:
            # cannot easily remove; skip test
            return
    except Exception:
        pass

    schema = ToolSchema(
        name=name,
        description="dummy",
        parameters={"path": "file path", "recursive": "bool"},
        required=["path"],
        param_types={"path": "string", "recursive": "bool"},
    )
    tr.register(schema)
    fetched = tr.get(name)
    assert fetched is not None
    valid, errors = tr.validate_call(name, {"path": "/tmp", "recursive": True})
    assert valid and not errors
    valid2, errors2 = tr.validate_call(name, {"path": "/tmp", "unknown": 1})
    assert not valid2 and any("Unknown parameter" in e for e in errors2)
