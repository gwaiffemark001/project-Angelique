from __future__ import annotations

import os
import re

DEFAULT_ELIGIBLE_BASES = (
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "USDCAD",
    "AUDUSD",
    "NZDUSD",
    "XAUUSD",
    "AUDCAD",
)


def normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def eligible_bases() -> tuple[str, ...]:
    configured = os.getenv("ANGELIQUE_TRADING_UNIVERSE", "")
    values = tuple(normalize(value) for value in configured.split(",") if normalize(value)) if configured else DEFAULT_ELIGIBLE_BASES
    return values


def eligible_symbols(available: list[str]) -> list[str]:
    bases = eligible_bases()
    result: list[str] = []
    for name in available:
        normalized = normalize(name)
        if any(normalized == base or normalized.startswith(base) for base in bases):
            result.append(name)
    return sorted(set(result), key=lambda name: (bases.index(next(base for base in bases if normalize(name).startswith(base))), name) if any(normalize(name).startswith(base) for base in bases) else (len(bases), name))
