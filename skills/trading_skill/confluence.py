from __future__ import annotations

from typing import Any


def evaluate_confluence(direction: str, trends: dict[str, str], indicator_data: dict[str, dict[str, Any]], smc_data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    agree: list[str] = []
    disagree: list[str] = []
    total_checks = 0
    total_agrees = 0

    for timeframe, values in indicator_data.items():
        if values.get("status") != "ready":
            continue
        last_close = float(values["last_close"])
        ema_ok = last_close >= float(values["ema_20"]) >= float(values["ema_50"]) if direction == "BUY" else last_close <= float(values["ema_20"]) <= float(values["ema_50"])
        macd_ok = float(values["macd"]) >= 0 if direction == "BUY" else float(values["macd"]) <= 0
        rsi_ok = float(values["rsi_14"]) >= 50 if direction == "BUY" else float(values["rsi_14"]) <= 50
        middle = float(values["bollinger_middle"])
        upper = float(values["bollinger_upper"])
        lower = float(values["bollinger_lower"])
        band_valid = lower <= last_close <= upper
        checks = {
            "EMA": ema_ok,
            "RSI": rsi_ok,
            "MACD": macd_ok,
            "BOLLINGER": band_valid,
        }
        for name, passed in checks.items():
            total_checks += 1
            if passed:
                total_agrees += 1
                agree.append(f"AGREES: {timeframe} {name} supports {direction} bias.")
            else:
                disagree.append(f"DISAGREES: {timeframe} {name} is mixed against {direction} bias.")

    for timeframe, values in smc_data.items():
        smc_checks = [
            ("liquidity sweep", bool(values.get("liquidity_sweep"))),
            ("structural shift", bool(values.get("structure_shift"))),
            ("fair value gap", bool(values.get("fair_value_gaps"))),
            ("order block", bool(values.get("order_block"))),
            ("location", values.get("location") in {"discount" if direction == "BUY" else "premium"}),
        ]
        for label, passed in smc_checks:
            total_checks += 1
            if passed:
                total_agrees += 1
                agree.append(f"AGREES: {timeframe} {label} supports the {direction} setup.")
            else:
                disagree.append(f"DISAGREES: {timeframe} {label} is not confirming the {direction} setup.")

    score = 0.0 if total_checks == 0 else total_agrees / total_checks
    return {
        "score": round(score, 3),
        "minimum_score": 0.6,
        "ready": score >= 0.6,
        "agree": agree,
        "disagree": disagree,
        "summary": f"Confluence score {score:.2f}/{1.0:.2f} - {len(agree)} supporting checks and {len(disagree)} conflicting checks.",
    }
