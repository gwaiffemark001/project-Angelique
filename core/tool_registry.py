"""Central ToolRegistry for Angelique.

The registry is the single source of truth for tool metadata, validation,
permission policy, and confirmation policy. The runtime execution flow must
validate against this registry before any tool invocation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
import time

RISK_LEVELS = ("SAFE", "LOW_RISK", "SENSITIVE", "DESTRUCTIVE", "FINANCIAL")
CONFIRMATION_POLICIES = ("automatic", "required", "never", "conditional")


class ValidationError(Exception):
    pass


class ToolSchema:
    def __init__(self, name: str, description: str = "", parameters: Optional[Dict[str, Dict]] = None,
                 required: Optional[List[str]] = None, param_types: Optional[Dict[str, str]] = None,
                 enums: Optional[Dict[str, List[Any]]] = None,
                 risk_level: str = "SAFE", permissions: Optional[List[str]] = None,
                 executor: Optional[Any] = None, timeout: Optional[int] = None,
                 category: str = "general", examples: Optional[List[Dict[str, Any]]] = None,
                 confirmation_policy: str = "automatic"):
        self.name = str(name)
        self.description = description or ""
        self.category = category or "general"
        self.parameters = parameters or {}
        self.required = required or []
        self.param_types = param_types or {}
        self.enums = enums or {}
        normalized_risk = str(risk_level or "SAFE").upper()
        self.risk_level = normalized_risk if normalized_risk in RISK_LEVELS else "SAFE"
        normalized_policy = str(confirmation_policy or "automatic").lower()
        self.confirmation_policy = normalized_policy if normalized_policy in CONFIRMATION_POLICIES else "automatic"
        self.permissions = permissions or []
        self.executor = executor
        self.timeout = int(timeout) if timeout is not None else None
        self.examples = examples or []
        self.created_at = time.time()

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "parameters": self.parameters,
            "required": self.required,
            "param_types": self.param_types,
            "enums": self.enums,
            "risk_level": self.risk_level,
            "confirmation_policy": self.confirmation_policy,
            "permissions": self.permissions,
            "examples": self.examples,
            "timeout": self.timeout,
        }

    def requires_confirmation(self) -> bool:
        if self.confirmation_policy == "required":
            return True
        if self.confirmation_policy == "automatic":
            return False
        if self.confirmation_policy == "never":
            return False
        if self.confirmation_policy == "conditional":
            return self.risk_level in {"SENSITIVE", "DESTRUCTIVE", "FINANCIAL"}
        return self.risk_level in {"SENSITIVE", "DESTRUCTIVE", "FINANCIAL"}


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolSchema] = {}

    def register(self, schema: ToolSchema):
        key = schema.name.strip()
        if not key:
            raise ValidationError("Tool must have a non-empty name")
        if key in self._tools:
            raise ValidationError(f"Tool '{key}' already registered")
        self._tools[key] = schema

    def get(self, name: str) -> Optional[ToolSchema]:
        if not name:
            return None
        return self._tools.get(name)

    def list(self) -> List[str]:
        return list(self._tools.keys())

    def validate_call(self, name: str, args: Optional[Dict[str, Any]] = None) -> (bool, List[str]):
        args = args or {}
        errors: List[str] = []
        schema = self.get(name)
        if not schema:
            errors.append(f"ToolNotFound: {name}")
            return False, errors

        for req in schema.required:
            if req not in args:
                errors.append(f"Missing required parameter: {req}")

        declared = set(schema.parameters.keys()) if schema.parameters else set()
        for k in args.keys():
            if declared and k not in declared:
                errors.append(f"Unknown parameter '{k}' for tool {name}")
                errors.append(f"InvalidArguments: unknown parameter '{k}' for tool {name}")

        for p, ptype in (schema.param_types or {}).items():
            if p in args:
                val = args[p]
                if ptype == "int":
                    if not isinstance(val, int):
                        errors.append(f"InvalidArguments: parameter '{p}' must be int")
                elif ptype == "float":
                    if not isinstance(val, (int, float)):
                        errors.append(f"InvalidArguments: parameter '{p}' must be float")
                elif ptype == "string":
                    if not isinstance(val, str):
                        errors.append(f"InvalidArguments: parameter '{p}' must be string")
                elif ptype == "bool":
                    if not isinstance(val, bool):
                        errors.append(f"InvalidArguments: parameter '{p}' must be bool")

        for p, choices in (schema.enums or {}).items():
            if p in args and args[p] not in choices:
                errors.append(f"InvalidArguments: parameter '{p}' must be one of {choices}")

        return len(errors) == 0, errors


GLOBAL_TOOL_REGISTRY = ToolRegistry()
