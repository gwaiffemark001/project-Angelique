from datetime import datetime, timezone
from types import SimpleNamespace


def test_period_loss_excludes_entries_and_balance_operations():
    from skills.trading_skill.wine_server import _period_loss_percent
    class MT5:
        DEAL_TYPE_BUY=0; DEAL_TYPE_SELL=1; DEAL_ENTRY_IN=0; DEAL_ENTRY_OUT=1; DEAL_ENTRY_OUT_BY=2
        def account_info(self): return SimpleNamespace(balance=975.0)
        def history_deals_get(self,start,end):
            return [SimpleNamespace(type=0, entry=0, profit=-10, commission=0, swap=0),
                    SimpleNamespace(type=0, entry=1, profit=-5, commission=-1, swap=0)]
    value=_period_loss_percent(MT5(),1000,1)
    assert round(value,4)==round(6/981*100,4)


def test_accepted_order_does_not_require_immediate_position_readback():
    from skills.trading_skill.workflow import TradingWorkflow
    from skills.trading_skill.models import WorkflowState
    class Adapter:
        def execute(self, order, mode):
            return {'success':True,'accepted':True,'retcode':10009,'position_verified':False,'verification':'accepted_no_position_readback'}
    wf=TradingWorkflow(Adapter(),risk_percent=0.5,minimum_rr=2.5)
    plan=SimpleNamespace(mt5_symbol='EURUSD',account_mode='demo',confirmation_phrase='x',expires_at='2999-01-01T00:00:00+00:00',as_dict=lambda:{'mt5_symbol':'EURUSD'})
    wf._plans['x']=plan; wf._active_plans['EURUSD:demo']=plan; wf._revalidate_plan=lambda p:(True,'ok')
    result=wf._execute_locked('x')
    assert result.state is WorkflowState.EXECUTED
    assert result.details['verification']=='accepted_no_position_readback'


def test_position_risk_from_sl_can_be_used_by_portfolio_gate():
    from skills.trading_skill.risk import validate_profile_limits
    from skills.trading_skill.profiles import get_trading_profile
    profile=get_trading_profile('DAY_TRADING')
    result=validate_profile_limits({'equity':1000,'daily_loss_percent':0,'weekly_loss_percent':0},[{'symbol':'EURUSD','risk_percent':0.8}],profile,new_risk_percent=0.5,symbol='GBPUSD')
    assert not result['valid']
    assert result['open_risk_percent']==0.8


def test_live_auto_execution_is_explicitly_configured():
    from core import config
    assert isinstance(config.TRADING_LIVE_AUTO_EXECUTION,bool)


def test_account_snapshot_fails_closed_when_loss_metrics_missing():
    from skills.trading_skill.account import account_snapshot
    snapshot = account_snapshot({"mode": "demo", "login": 1, "equity": 1000, "balance": 1000}, "demo")
    assert not snapshot.connected
    assert "loss" in (snapshot.error or "").lower()
