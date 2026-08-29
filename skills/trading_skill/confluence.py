from __future__ import annotations

from typing import Any


def evaluate_confluence(direction: str, trends: dict[str, str], indicator_data: dict[str, dict[str, Any]], smc_data: dict[str, dict[str, Any]], profile=None, ict_data: dict[str, Any] | None = None) -> dict[str, Any]:
    agree: list[str] = []
    disagree: list[str] = []
    score = 0
    max_score = 14  # Increased from 10 to account for ICT factors

    context_timeframe = getattr(profile, "context_timeframe", "H4")
    structure_timeframe = getattr(profile, "structure_timeframe", "M15")
    context_trend = trends.get(context_timeframe)
    expected_trend = "bullish" if direction == "BUY" else "bearish"
    if context_trend == expected_trend and trends.get(getattr(profile, "trend_timeframe", "H1"), context_trend) == expected_trend:
        score += 2
        agree.append(f"AGREES: higher-timeframe structure aligns with {direction}.")
    else:
        disagree.append("DISAGREES: higher-timeframe structure is not aligned.")

    smc_values = smc_data.get(structure_timeframe, {})
    expected_sweep = "sell_side_liquidity_sweep" if direction == "BUY" else "buy_side_liquidity_sweep"
    if smc_values.get("liquidity_sweep") == expected_sweep:
        score += 2
        agree.append(f"AGREES: {structure_timeframe} liquidity sweep supports {direction}.")
    else:
        disagree.append(f"DISAGREES: {structure_timeframe} has no directional liquidity sweep.")

    expected_shifts = {"bullish_BOS", "bullish_CHoCH"} if direction == "BUY" else {"bearish_BOS", "bearish_CHoCH"}
    if smc_values.get("structure_shift") in expected_shifts:
        score += 2
        agree.append(f"AGREES: {structure_timeframe} BOS/CHoCH supports {direction}.")
    else:
        disagree.append(f"DISAGREES: {structure_timeframe} has no directional BOS/CHoCH.")

    block = smc_values.get("order_block")
    gaps = smc_values.get("fair_value_gaps", [])
    quality_block = isinstance(block, dict) and block.get("type") == expected_trend and block.get("score", 0) >= 5
    quality_gap = any(gap.get("type") == expected_trend and gap.get("score", 0) >= 4 for gap in gaps if isinstance(gap, dict))
    if quality_block or quality_gap:
        score += 1
        agree.append(f"AGREES: quality {expected_trend} OB/FVG is available.")
    else:
        disagree.append("DISAGREES: no sufficiently qualified directional OB/FVG.")

    preferred_location = "discount" if direction == "BUY" else "premium"
    if smc_values.get("location") == preferred_location:
        score += 1
        agree.append(f"AGREES: price is in {preferred_location}.")
    else:
        disagree.append(f"DISAGREES: price is not in {preferred_location}.")

    # ICT Confluence Factors
    if ict_data:
        # 1. AMD Phase Alignment (Power of Three)
        amd_phase = ict_data.get("amd_phase", "unknown")
        amd_cycle = ict_data.get("amd_cycle", {})
        
        # For BUY: want to see manipulation complete (low swept) entering distribution
        # For SELL: want to see manipulation complete (high swept) entering distribution
        if direction == "BUY":
            if amd_phase == "distribution" or (amd_cycle.get("is_complete") and amd_phase == "manipulation"):
                score += 2
                agree.append(f"AGREES: AMD phase ({amd_phase}) supports bullish distribution.")
            elif amd_phase == "manipulation":
                score += 1
                agree.append("AGREES: AMD in manipulation phase - watching for bullish reversal.")
            else:
                disagree.append(f"DISAGREES: AMD phase ({amd_phase}) not optimal for bullish entry.")
        else:  # SELL
            if amd_phase == "distribution" or (amd_cycle.get("is_complete") and amd_phase == "manipulation"):
                score += 2
                agree.append(f"AGREES: AMD phase ({amd_phase}) supports bearish distribution.")
            elif amd_phase == "manipulation":
                score += 1
                agree.append("AGREES: AMD in manipulation phase - watching for bearish reversal.")
            else:
                disagree.append(f"DISAGREES: AMD phase ({amd_phase}) not optimal for bearish entry.")

        # 2. Session Timing (Kill Zones)
        is_prime = ict_data.get("is_prime_time", False)
        current_session = ict_data.get("current_session", "unknown")
        if is_prime:
            score += 2
            agree.append(f"AGREES: Trading during prime session ({current_session}).")
        else:
            disagree.append(f"DISAGREES: Outside prime trading session ({current_session}).")

        # 3. Premium/Discount Zone Confirmation
        pd_analysis = ict_data.get("premium_discount", {})
        pd_zone = pd_analysis.get("zone", "equilibrium")
        if direction == "BUY" and pd_zone == "discount":
            score += 2
            agree.append(f"AGREES: Price in discount zone ({pd_analysis.get('percentage_from_low', 0):.1f}% from low).")
        elif direction == "SELL" and pd_zone == "premium":
            score += 2
            agree.append(f"AGREES: Price in premium zone ({pd_analysis.get('percentage_from_low', 0):.1f}% from low).")
        elif pd_zone == "equilibrium":
            disagree.append("DISAGREES: Price at equilibrium - not in premium/discount.")
        else:
            disagree.append(f"DISAGREES: Price in wrong zone for {direction} ({pd_zone}).")

        # 4. OTE Zone Entry (Fibonacci 0.618-0.786)
        ote_zone = ict_data.get("ote_zone", {})
        if ote_zone:
            ote_lower = ote_zone.get("ote_lower", 0)
            ote_upper = ote_zone.get("ote_upper", 0)
            sweet_spot = ote_zone.get("sweet_spot", 0)
            
            # Check if current price is near OTE zone
            # This would need actual price comparison in real usage
            if direction == "BUY" and ote_zone.get("is_discount"):
                score += 2
                agree.append(f"AGREES: OTE zone identified (0.618-{ote_lower:.5f}, 0.786-{ote_upper:.5f}, sweet spot {sweet_spot:.5f}).")
            elif direction == "SELL" and ote_zone.get("is_premium"):
                score += 2
                agree.append(f"AGREES: OTE zone identified for sell (0.618-{ote_lower:.5f}, 0.786-{ote_upper:.5f}).")
            else:
                disagree.append("DISAGREES: OTE zone not aligned with trade direction.")
        else:
            disagree.append("DISAGREES: No clear OTE zone identified.")

    for timeframe, values in indicator_data.items():
        if values.get("status") != "ready":
            continue
        last_close = float(values["last_close"])
        ema_ok = last_close >= float(values["ema_20"]) >= float(values["ema_50"]) >= float(values["ema_200"]) if direction == "BUY" else last_close <= float(values["ema_20"]) <= float(values["ema_50"]) <= float(values["ema_200"])
        macd_ok = float(values["macd_histogram"]) >= 0 if direction == "BUY" else float(values["macd_histogram"]) <= 0
        rsi_ok = float(values["rsi_14"]) >= 50 if direction == "BUY" else float(values["rsi_14"]) <= 50
        momentum_ok = rsi_ok and macd_ok
        if momentum_ok:
            score += 1
            agree.append(f"AGREES: {timeframe} momentum confirms {direction}.")
        else:
            disagree.append(f"DISAGREES: {timeframe} momentum confirmation is mixed.")
        if ema_ok:
            score += 1
            agree.append(f"AGREES: {timeframe} EMA 20/50/200 alignment confirms {direction}.")
        else:
            disagree.append(f"DISAGREES: {timeframe} EMA alignment is mixed.")
        break

    minimum_score = getattr(profile, "minimum_score", 7)
    return {
        "score": score,
        "maximum_score": max_score,
        "minimum_score": minimum_score,
        "ready": score >= minimum_score,
        "agree": agree,
        "disagree": disagree,
        "summary": f"Confluence score {score:.2f}/{max_score:.2f} - {len(agree)} supporting checks and {len(disagree)} conflicting checks.",
    }
