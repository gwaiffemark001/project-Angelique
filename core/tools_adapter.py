"""Adapter to register existing TOOL_REGISTRY entries into the new ToolRegistry.

This preserves existing skill functions while migrating to structured ToolSchema objects.
"""
from core.tool_registry import GLOBAL_TOOL_REGISTRY, ToolSchema
from core import tools as old_tools


def migrate_registry():
    # old_tools.TOOL_REGISTRY is a dict mapping names->info
    for name, info in getattr(old_tools, "TOOL_REGISTRY", {}).items():
        try:
            params = info.get("parameters") or {}
            required = [k for k, v in params.items() if isinstance(v, dict) and v.get("required")]
            schema = ToolSchema(
                name=name,
                description=info.get("description", ""),
                parameters=params,
                required=required,
                param_types=info.get("param_types", {}),
                enums=info.get("enums", {}),
                risk_level=info.get("risk_level", "SAFE") or "SAFE",
                permissions=info.get("permissions", []),
                executor=info.get("function"),
                timeout=info.get("timeout"),
            )
            GLOBAL_TOOL_REGISTRY.register(schema)
        except Exception:
            # Skip tools that fail to migrate
            continue


# Run migration on import for now (idempotent if registry already contains entries)
migrate_registry()
