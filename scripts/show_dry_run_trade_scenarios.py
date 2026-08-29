"""Show realistic trade-plan pass/fail scenarios without contacting MT5."""

from __future__ import annotations

import tkinter as tk
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.angelique_desktop import AngeliqueDesktopApp
from skills.trading_skill.safety import validate_trade_setup


def _safety_result(*, stop_loss: float, spread_pips: float) -> dict:
    return validate_trade_setup(
        direction="BUY",
        entry=1.08420,
        stop_loss=stop_loss,
        take_profit=1.09100,
        risk_amount=5.00,
        risk_percent=0.5,
        volume=0.05,
        margin_required=42.00,
        free_margin_after=958.00,
        minimum_free_margin=100.00,
        current_margin_level=850.0,
        spread_pips=spread_pips,
        maximum_spread_pips=1.5,
        minimum_rr=2.0,
    )


def _passing_plan() -> dict:
    return {
        "mt5_symbol": "EURUSDm",
        "direction": "BUY",
        "order_type": "MARKET",
        "entry": 1.08420,
        "stop_loss": 1.08220,
        "take_profit": 1.09100,
        "volume": 0.05,
        "risk_percent": 0.5,
        "risk_amount": 5.00,
        "reward_to_risk": 3.4,
        "margin_required": 42.00,
        "free_margin_after": 958.00,
        "projected_margin_level": 850.0,
        "account_mode": "demo",
        "account_login": 123456,
        "broker": "Valetax (dry run)",
        "platform": "MT5",
        "trading_mode": "DAY_TRADING",
        "estimated_spread_cost": 0.45,
        "estimated_commission": 0.20,
        "estimated_swap_cost": 0.00,
        "spread_pips": 0.8,
        "confirmation_phrase": "DRY RUN ONLY - no execution permitted",
        "rationale": [
            "H4/H1 bullish context is aligned.",
            "Bullish BOS followed displacement into a discount zone.",
            "Price retraced to the monitored zone and M5 confirmed bullish reaction.",
            "Stop is below structural invalidation; target is opposing liquidity.",
        ],
        "smc_analysis": {
            "structure_shift": "bullish_BOS",
            "liquidity_sweep": "sell_side_liquidity_sweep",
            "location": "discount",
        },
        "profile": {
            "minimum_score": 7,
            "context_timeframe": "H4",
            "trend_timeframe": "H1",
            "setup_timeframe": "M15",
            "entry_timeframe": "M5",
        },
        "news_context": {"bias": "neutral", "reason": "No blocking news in dry-run scenario."},
    }


class DryRunApp(AngeliqueDesktopApp):
    def _approve_trade_plan(self, dialog, confirmation_phrase):
        dialog.destroy()
        self._trading_monitor_popup_open = False
        self.trading_detail_var.set("DRY RUN: approval captured; no broker execution was called.")
        self._append_console("TRADING-DRY-RUN", "Approval button intercepted. No order was sent.")


def main() -> None:
    failed = _safety_result(stop_loss=1.08500, spread_pips=2.4)
    passed = _safety_result(stop_loss=1.08220, spread_pips=0.8)
    print("FAILED SCENARIO: BUY stop is above entry and spread is too wide")
    print(f"  valid={failed['valid']} reasons={'; '.join(failed['reasons'])}")
    print("PASSING SCENARIO: structural stop, logical target, acceptable spread and margin")
    print(f"  valid={passed['valid']} checks={'; '.join(passed['checks'])}")
    if not passed["valid"]:
        raise RuntimeError("The dry-run passing scenario failed its own safety checks.")

    app = DryRunApp()
    if not app.winfo_exists():
        return
    result = {
        "message": "BUY_PLAN_READY: dry-run plan passed market safety checks.",
        "plan": _passing_plan(),
        "details": {"confluence": {"score": 8}},
        "account": {"equity": 1000.00},
        "market": {"spread_pips": 0.8},
    }
    app.after(250, lambda: app._show_trade_plan_popup(result))
    app.mainloop()


if __name__ == "__main__":
    main()