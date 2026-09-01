from datetime import datetime, timezone
from unittest.mock import patch


def test_public_system_imports_and_entrypoint():
    import launcher
    from core.local_ai_router import LocalAIRouter
    from skills.trading.ict_core import calculate_ote, is_kill_zone

    assert callable(launcher.main)
    assert LocalAIRouter is not None
    assert calculate_ote(2.0, 1.0)["equilibrium"] == 1.5
    assert isinstance(is_kill_zone(datetime(2026, 8, 30, 7, 30, tzinfo=timezone.utc)), bool)


def test_auto_execution_hard_blocks_outside_kill_zone():
    from skills.trading_skill import service

    plan = {
        "confirmation_phrase": "TEST-PLAN",
        "direction": "BUY",
        "mt5_symbol": "EURUSD",
        "requires_manual_approval": False,
    }
    scan = {"state": "OPPORTUNITY_FOUND", "candidates": [plan], "opportunity": {"plan": plan}}
    with patch.object(service, "scan_universe", return_value=scan), \
         patch.object(service, "auto_execution_enabled", return_value=True), \
         patch("skills.trading.ict_core.get_kill_zone_status", return_value=("INACTIVE", "Outside ICT kill zones")):
        result = service.decide_and_act("demo", "DAY_TRADING", ["EURUSD"])
    assert result["state"] == "KILL_ZONE_BLOCKED"
    assert result["execution"]["state"] == "AUTO_BLOCKED_KILL_ZONE"
