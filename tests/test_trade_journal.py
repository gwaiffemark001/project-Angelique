import json

from skills.trading_skill import journal


def test_trade_journal_retains_mode_smc_and_risk(monkeypatch, tmp_path):
    path = tmp_path / "trades.json"
    monkeypatch.setattr(journal, "_path", lambda: path)
    entry = journal.record_trade(
        {
            "mt5_symbol": "EURUSDm",
            "direction": "BUY",
            "entry": 1.1,
            "stop_loss": 1.098,
            "take_profit": 1.104,
            "volume": 0.1,
            "risk_percent": 0.5,
            "risk_amount": 5,
            "reward_to_risk": 2,
            "trading_mode": "DAY_TRADING",
            "profile": {"minimum_score": 7},
            "smc_analysis": {"structure_shift": "bullish_BOS"},
            "margin_required": 10,
        },
        {"status": "EXECUTED", "ticket": 12},
    )
    stored = json.loads(path.read_text(encoding="utf-8"))[0]
    assert entry["trading_mode"] == "DAY_TRADING"
    assert stored["smc_analysis"]["structure_shift"] == "bullish_BOS"
    assert stored["risk"]["risk_percent"] == 0.5
    assert stored["result"] == "EXECUTED"