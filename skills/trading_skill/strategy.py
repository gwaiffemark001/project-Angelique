"""Deterministic identification of supported trade setup models.

Evaluates every supported SMC model independently against its own
correct evidence (a model built on an order block must be checked
against the order block, not whichever zone happened to be nearest),
then selects the best COMPLETE model rather than guessing a single
model up front from raw evidence and only checking that one guess.
"""

from __future__ import annotations

from typing import Any


SETUP_MODELS = {
    "SWEEP_REVERSAL": {
        "required": ("directional_sweep", "structural_event", "displacement", "entry_zone", "retracement", "entry_confirmation"),
        "optional": ("fvg", "order_block", "ema", "rsi", "macd", "bollinger", "adx"),
    },
    "BOS_CONTINUATION": {
        "required": ("directional_bos", "displacement", "entry_zone", "retracement", "entry_confirmation"),
        "optional": ("liquidity_sweep", "fvg", "order_block", "ema", "rsi", "macd", "bollinger", "adx"),
    },
    "ORDER_BLOCK_RETRACEMENT": {
        "required": ("structural_event", "displacement", "order_block", "retracement", "entry_confirmation"),
        "optional": ("fvg", "liquidity_sweep", "ema", "rsi", "macd", "bollinger", "adx"),
    },
    "FVG_RETRACEMENT": {
        "required": ("structural_event", "displacement", "fvg", "retracement", "entry_confirmation"),
        "optional": ("order_block", "liquidity_sweep", "ema", "rsi", "macd", "bollinger", "adx"),
    },
}

# When more than one model is complete on the same candle, prefer the one
# with the strongest structural confirmation first.
_MODEL_PRIORITY = ("SWEEP_REVERSAL", "BOS_CONTINUATION", "ORDER_BLOCK_RETRACEMENT", "FVG_RETRACEMENT")


def _zone_for(model: str, fvg: dict | None, order_block: dict | None) -> dict | None:
    """Each model is checked against its own zone, not a shared guess."""
    if model == "FVG_RETRACEMENT":
        return fvg
    if model == "ORDER_BLOCK_RETRACEMENT":
        return order_block
    # SWEEP_REVERSAL / BOS_CONTINUATION accept either as confirming context.
    return fvg or order_block


def _evaluate_model(
    model: str,
    *,
    sweep: bool,
    structural_event: bool,
    directional_bos: bool,
    displacement: bool,
    fvg: dict | None,
    order_block: dict | None,
    entry_smc: dict[str, Any],
    expected: str,
    entry_shift: str,
) -> dict[str, Any]:
    zone = _zone_for(model, fvg, order_block)
    retracement = bool(zone and (zone.get("price_in_zone") or zone.get("retracement_status") == "CURRENT_RETRACEMENT"))
    entry_confirmation = bool(entry_smc.get("displacement")) and entry_shift.startswith(expected)
    stages = {
        "directional_sweep": sweep,
        "directional_bos": directional_bos,
        "structural_event": structural_event,
        "displacement": displacement,
        "entry_zone": zone is not None,
        "fvg": fvg is not None,
        "order_block": order_block is not None,
        "retracement": retracement,
        "entry_confirmation": entry_confirmation,
        "candle_confirmation": bool(entry_smc.get("candle_pattern", {}).get("confirmation")),
    }
    required = SETUP_MODELS[model]["required"]
    missing = [stage for stage in required if not stages.get(stage, False)]
    return {
        "model": model,
        "stages": stages,
        "missing": missing,
        "zone": zone,
        "complete": not missing,
        "confirmation_event": entry_smc.get("structure_event") if entry_confirmation else None,
    }


def identify_setup(direction: str, setup_smc: dict[str, Any], entry_smc: dict[str, Any]) -> dict[str, Any]:
    """Evaluate all supported models and return the best complete one."""
    expected = "bullish" if direction == "BUY" else "bearish"
    sweep = setup_smc.get("liquidity_sweep") == (
        "sell_side_liquidity_sweep" if direction == "BUY" else "buy_side_liquidity_sweep"
    )
    shift = str(setup_smc.get("structure_shift") or "")
    entry_shift = str(entry_smc.get("structure_shift") or "")
    structural_event = shift.startswith(expected) or entry_shift.startswith(expected)
    directional_bos = shift == f"{expected}_BOS" or entry_shift == f"{expected}_BOS"
    displacement = bool(setup_smc.get("displacement")) or bool(entry_smc.get("displacement"))

    fvg = next(
        (
            gap for gap in setup_smc.get("fair_value_gaps", [])
            if isinstance(gap, dict)
            and gap.get("type") == expected
            and gap.get("classification") in {"QUALIFIED_FVG", "TRADEABLE_FVG"}
            and gap.get("status") not in {"FULLY_MITIGATED", "INVALIDATED"}
        ),
        None,
    )
    order_block = next(
        (block for block in reversed(setup_smc.get("order_blocks", []))
         if isinstance(block, dict) and block.get("type") == expected and block.get("classification") == "TRADEABLE_OB" and block.get("status") not in {"FULLY_MITIGATED", "INVALIDATED"}),
        setup_smc.get("order_block"),
    )
    if not isinstance(order_block, dict) or order_block.get("type") != expected or order_block.get("classification") != "TRADEABLE_OB":
        order_block = None

    evaluations = {
        model: _evaluate_model(
            model,
            sweep=sweep,
            structural_event=structural_event,
            directional_bos=directional_bos,
            displacement=displacement,
            fvg=fvg,
            order_block=order_block,
            entry_smc=entry_smc,
            expected=expected,
            entry_shift=entry_shift,
        )
        for model in SETUP_MODELS
    }

    # A model can only ever be reached by its own precondition (e.g. there's
    # no point evaluating SWEEP_REVERSAL completeness if there was no sweep
    # at all) -- this keeps 'complete' meaningful rather than accidental.
    reachable = {
        "SWEEP_REVERSAL": sweep and structural_event,
        "BOS_CONTINUATION": directional_bos,
        "ORDER_BLOCK_RETRACEMENT": order_block is not None,
        "FVG_RETRACEMENT": fvg is not None,
    }

    complete_models = [model for model in _MODEL_PRIORITY if reachable[model] and evaluations[model]["complete"]]
    location_ok = setup_smc.get("location") == ("discount" if direction == "BUY" else "premium")

    if complete_models and location_ok:
        chosen = complete_models[0]
        evaluation = evaluations[chosen]
        return {
            "model": chosen,
            "direction": direction,
            "required": list(SETUP_MODELS[chosen]["required"]),
            "optional": list(SETUP_MODELS[chosen]["optional"]),
            "stages": evaluation["stages"],
            "missing": [],
            "zone": evaluation["zone"],
            "confirmation_event": evaluation["confirmation_event"],
            "complete": True,
            "alternate_models_available": complete_models[1:],
            "reason": f"{chosen} is complete.",
            "supporting_evidence": {
                "ifvg": setup_smc.get("ifvg", {}),
                "amd": setup_smc.get("amd", {}),
                "candle_pattern": entry_smc.get("candle_pattern", {}),
                "wave_context": setup_smc.get("wave_context", {}),
            },
        }

    # Nothing complete: report the model that's reachable and closest to
    # complete (fewest missing stages) so diagnostics stay useful instead
    # of a bare 'no setup'.
    reachable_models = [model for model in _MODEL_PRIORITY if reachable[model]]
    if reachable_models:
        best = min(reachable_models, key=lambda model: len(evaluations[model]["missing"]))
        evaluation = evaluations[best]
        missing = list(evaluation["missing"])
        if not location_ok:
            missing = missing + ["price_location"]
        return {
            "model": best,
            "direction": direction,
            "required": list(SETUP_MODELS[best]["required"]),
            "optional": list(SETUP_MODELS[best]["optional"]),
            "stages": evaluation["stages"],
            "missing": missing,
            "zone": evaluation["zone"],
            "confirmation_event": None,
            "complete": False,
            "alternate_models_available": [],
            "reason": f"{best} has incomplete evidence: {', '.join(missing) or 'a supported evidence relationship'}.",
            "supporting_evidence": {
                "ifvg": setup_smc.get("ifvg", {}),
                "amd": setup_smc.get("amd", {}),
                "candle_pattern": entry_smc.get("candle_pattern", {}),
                "wave_context": setup_smc.get("wave_context", {}),
            },
        }

    return {
        "model": "UNSUPPORTED",
        "direction": direction,
        "required": [],
        "optional": [],
        "stages": {
            "directional_sweep": sweep,
            "directional_bos": directional_bos,
            "structural_event": structural_event,
            "displacement": displacement,
            "fvg": fvg is not None,
            "order_block": order_block is not None,
        },
        "missing": [],
        "zone": None,
        "confirmation_event": None,
        "complete": False,
        "alternate_models_available": [],
        "reason": "No supported setup model has a reachable precondition on this candle.",
        "supporting_evidence": {
            "ifvg": setup_smc.get("ifvg", {}),
            "amd": setup_smc.get("amd", {}),
            "candle_pattern": entry_smc.get("candle_pattern", {}),
            "wave_context": setup_smc.get("wave_context", {}),
        },
    }
