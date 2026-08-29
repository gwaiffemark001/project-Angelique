import importlib
from types import SimpleNamespace


def test_workflow_consumes_plan_on_failed_send(monkeypatch):
    from skills.trading_skill.workflow import TradingWorkflow
    from skills.trading_skill.models import TradePlan, WorkflowState

    class Adapter:
        def execute(self, order, mode):
            return {"success": False, "failure_stage": "mt5_order_send", "error": "rejected"}
    # Use a lightweight object and call the terminal block through the public method.
    wf=TradingWorkflow(Adapter(), risk_percent=1.0, minimum_rr=2.5)
    plan=SimpleNamespace(mt5_symbol="EURUSD",account_mode="demo",confirmation_phrase="x",expires_at="2999-01-01T00:00:00+00:00",as_dict=lambda:{"mt5_symbol":"EURUSD"})
    wf._plans["x"]=plan; wf._active_plans["EURUSD:demo"]=plan
    wf._revalidate_plan=lambda p:(True,"ok")
    result=wf._execute_locked("x")
    assert result.state is WorkflowState.REJECTED
    assert "x" not in wf._plans
    assert "EURUSD:demo" not in wf._active_plans


def test_whatsapp_has_no_browser_path():
    m=importlib.import_module("skills.messaging.whatsapp_tools")
    assert "webbrowser" not in m.__dict__
    assert hasattr(m,"resolve_contact")


def test_config_env_extension_does_not_remove_original_model_keys():
    from core import config
    assert config.OLLAMA_BASE_URL
    assert config.PRIMARY_MODEL
    assert config.CODER_MODEL


def test_mt5_fill_mode_helper_prefers_supported_flags():
    from skills.trading_skill.wine_server import _choose_filling_mode
    mt5=SimpleNamespace(SYMBOL_FILLING_FOK=1,SYMBOL_FILLING_IOC=2,ORDER_FILLING_FOK=0,ORDER_FILLING_IOC=1,ORDER_FILLING_RETURN=2,SYMBOL_TRADE_EXECUTION_MARKET=2)
    assert _choose_filling_mode(mt5,SimpleNamespace(filling_mode=2,trade_exemode=2))==1


def test_ui_is_original_size_and_contains_trading_hub():
    from pathlib import Path
    p=Path(__file__).resolve().parents[1]/"gui"/"angelique_desktop.py"
    assert len(p.read_text(encoding="utf-8").splitlines()) > 4000
    assert "TradingHubController" in p.read_text(encoding="utf-8")


def test_execute_tool_requires_canonical_registry(monkeypatch):
    from core.tools import execute_tool
    assert "canonical registry" in execute_tool("definitely_not_a_tool", {}).lower()


def test_blank_ollama_candidate_setting_has_safe_defaults():
    from core import config
    assert config.OLLAMA_MODEL_CANDIDATES
    assert config.CODER_MODEL in config.OLLAMA_MODEL_CANDIDATES


def test_ui_worker_rejects_stale_account_mode_before_trade():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "gui" / "angelique_desktop.py").read_text(encoding="utf-8")
    assert 'if str(account_mode).lower() != self._get_selected_account_mode().lower():' in text
