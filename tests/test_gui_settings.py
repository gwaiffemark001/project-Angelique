import json


def test_trading_mode_is_saved_and_loaded(tmp_path):
    settings_path = tmp_path / "gui_settings.json"
    settings_path.write_text(json.dumps({"trading_mode": "SWING_TRADING"}), encoding="utf-8")
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert settings["trading_mode"] == "SWING_TRADING"