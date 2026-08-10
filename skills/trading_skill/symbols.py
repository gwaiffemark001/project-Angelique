from __future__ import annotations
import re


def canonical(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def resolve(requested: str, available: list[str]) -> str | None:
    key = canonical(requested)
    names = [str(item) for item in available if str(item).strip()]
    exact = next((name for name in names if canonical(name) == key), None)
    if exact:
        return exact
    matches = [name for name in names if canonical(name).startswith(key)]
    return sorted(matches, key=lambda name: (len(name), name))[0] if matches else None
