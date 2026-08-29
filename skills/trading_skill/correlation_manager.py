from __future__ import annotations

from typing import Any
import math
from core.price_units import is_metal_symbol
from core import config


def normalize_symbol(symbol: Any) -> str:
    return "".join(ch for ch in str(symbol or "").upper() if ch.isalnum())


def split_fx_symbol(symbol: Any) -> tuple[str | None, str | None]:
    key = normalize_symbol(symbol)
    for suffix in (".A", ".M", "_A", "_M"):
        key = key.replace(suffix, "")
    if len(key) < 6:
        return None, None
    majors = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"}
    for start in range(0, len(key) - 5):
        base, quote = key[start:start + 3], key[start + 3:start + 6]
        if base in majors and quote in majors:
            return base, quote
    return None, None


def currency_exposure(symbol: Any, direction: str, volume: float = 1.0) -> dict[str, float]:
    base, quote = split_fx_symbol(symbol)
    if not base or not quote:
        return {}
    amount = abs(float(volume or 0) or 1.0)
    sign = 1.0 if str(direction).upper() in {"BUY", "LONG", "0"} else -1.0
    return {base: sign * amount, quote: -sign * amount}


def _returns(values: list[float]) -> list[float]:
    clean = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v)) and float(v) > 0]
    return [math.log(clean[i] / clean[i - 1]) for i in range(1, len(clean)) if clean[i - 1] > 0]


def rolling_correlation(prices_a: list[float], prices_b: list[float], lookback: int = 100) -> float | None:
    ra, rb = _returns(prices_a)[-lookback:], _returns(prices_b)[-lookback:]
    n = min(len(ra), len(rb))
    if n < 20:
        return None
    ra, rb = ra[-n:], rb[-n:]
    mean_a = sum(ra) / n
    mean_b = sum(rb) / n
    covariance = sum((a - mean_a) * (b - mean_b) for a, b in zip(ra, rb))
    var_a = sum((a - mean_a) ** 2 for a in ra)
    var_b = sum((b - mean_b) ** 2 for b in rb)
    if var_a <= 0 or var_b <= 0:
        return None
    return covariance / math.sqrt(var_a * var_b)


def check_shared_currency(
    candidate_symbol: str,
    candidate_direction: str,
    positions: list[dict[str, Any]],
    strict: bool = True,
) -> dict[str, Any]:
    candidate = currency_exposure(candidate_symbol, candidate_direction)
    conflicts: list[dict[str, Any]] = []
    for pos in positions:
        exposure = currency_exposure(pos.get("symbol"), pos.get("type", pos.get("direction", "BUY")), pos.get("volume", 1.0))
        shared = sorted(set(candidate) & set(exposure))
        if shared and strict:
            conflicts.append({
                "symbol": pos.get("symbol"),
                "ticket": pos.get("ticket"),
                "shared_currencies": shared,
                "candidate_exposure": {c: candidate.get(c, 0.0) for c in shared},
                "existing_exposure": {c: exposure.get(c, 0.0) for c in shared},
            })
    return {
        "valid": not conflicts,
        "candidate_exposure": candidate,
        "conflicts": conflicts,
        "shared_currencies": sorted({c for item in conflicts for c in item["shared_currencies"]}),
    }


def evaluate_portfolio(
    candidate_symbol: str,
    candidate_direction: str,
    candidate_risk_percent: float,
    positions: list[dict[str, Any]],
    *,
    max_positions: int,
    max_open_risk: float,
    strict_shared_currency: bool = True,
) -> dict[str, Any]:
    reasons: list[str] = []
    known_risk = 0.0
    unknown_risk: list[dict[str, Any]] = []
    for pos in positions:
        risk = pos.get("risk_percent")
        if risk is None:
            unknown_risk.append(pos)
        else:
            try:
                known_risk += max(0.0, float(risk))
            except (TypeError, ValueError):
                unknown_risk.append(pos)
    if unknown_risk:
        reasons.append("Existing position risk cannot be verified because at least one open position has unknown SL risk.")
    if len(positions) >= max_positions:
        reasons.append(f"Maximum positions reached ({len(positions)}/{max_positions}).")
    if known_risk + candidate_risk_percent > max_open_risk + 1e-9:
        reasons.append(f"Open risk would exceed {max_open_risk:.2f}% ({known_risk:.2f}% existing + {candidate_risk_percent:.2f}% candidate).")
    shared = check_shared_currency(candidate_symbol, candidate_direction, positions, strict_shared_currency)
    if not shared["valid"]:
        reasons.append("Candidate shares currency exposure with an existing position.")
    if is_metal_symbol(candidate_symbol):
        metal_positions = [pos for pos in positions if is_metal_symbol(pos.get("symbol"))]
        max_metals = int(getattr(config, "TRADING_MAX_METAL_POSITIONS", 1))
        if len(metal_positions) >= max_metals:
            reasons.append(f"Maximum metal positions reached ({len(metal_positions)}/{max_metals}).")
    return {
        "valid": not reasons,
        "reasons": reasons,
        "known_open_risk_percent": known_risk,
        "unknown_risk_positions": unknown_risk,
        "candidate_risk_percent": candidate_risk_percent,
        "aggregate_risk_percent": known_risk + candidate_risk_percent,
        "shared_currency": shared,
    }
