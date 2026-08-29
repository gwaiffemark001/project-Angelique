from __future__ import annotations
import sys, tempfile, types, subprocess
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
R=[]
def ck(name, fn):
    try:
        out=fn(); R.append((name,'PASS',str(out)[:240])); print('PASS',name,flush=True)
    except Exception as e:
        R.append((name,'FAIL',f'{type(e).__name__}: {e}')); print('FAIL',name,e,flush=True)

import skills.os_control.app_discovery as apps
with patch.object(apps,'psutil') as ps:
    ps.process_iter.return_value=[]
    ck('os.close_app',lambda:apps.close_app('validation-does-not-exist'))
import skills.os_control.desktop_control as dc
fake_py=types.SimpleNamespace(moveTo=lambda *a,**k:None,click=lambda *a,**k:None,write=lambda *a,**k:None,hotkey=lambda *a,**k:None,press=lambda *a,**k:None,screenshot=lambda:types.SimpleNamespace(save=lambda p:None))
with patch.dict(sys.modules,{'pyautogui':fake_py}): ck('os.mouse_click',lambda:dc.mouse_click(1,1))
import skills.os_control.system_cmds as sc
ck('os.list_directory',lambda:sc.list_directory('/tmp',False))
proc=subprocess.Popen(['sleep','5']); ck('os.kill_process',lambda:sc.kill_process(str(proc.pid))); 
try: proc.wait(timeout=1)
except Exception: pass

import skills.trading.engine.mt5_bridge as emb
fac=emb.BridgeFacade(); fac.client=Mock(); fac.client.start.return_value=True; fac.client.connect.return_value=True; fac.client.last_error.return_value='ok'; fac.client.get_status.return_value={'status':'connected'}
ck('trading.bridge.start',fac.start); ck('trading.bridge.get_last_error',fac.get_last_error)

import skills.trading.engine.mt5_bridge_server as srv
class MT5:
    SYMBOL_TRADE_EXECUTION_MARKET=2; SYMBOL_FILLING_FOK=1; SYMBOL_FILLING_IOC=2; ORDER_FILLING_FOK=0; ORDER_FILLING_IOC=1; ORDER_FILLING_RETURN=2
    ACCOUNT_TRADE_MODE_DEMO=0; ACCOUNT_TRADE_MODE_REAL=2; TRADE_RETCODE_DONE=10009; TRADE_RETCODE_PLACED=10008; TRADE_RETCODE_DONE_PARTIAL=10010
    TIMEFRAME_M15=15
    def initialize(self,*a,**k): return True
    def shutdown(self): pass
    def last_error(self): return (0,'ok')
    def account_info(self): return types.SimpleNamespace(trade_mode=0,login=1,balance=1000,equity=1000,margin=0,margin_free=1000,margin_level=0,leverage=100,server='demo',company='Validation')
    def symbol_select(self,*a,**k): return True
    def symbols_get(self): return [types.SimpleNamespace(name='EURUSD')]
    def symbol_info(self,*a,**k): return types.SimpleNamespace(filling_mode=2,trade_exemode=2,point=0.00001,digits=5,trade_stops_level=0,trade_tick_size=0.00001,trade_tick_value=1.0,volume_step=0.01,volume_min=0.01,volume_max=10)
    def symbol_info_tick(self,*a,**k): return types.SimpleNamespace(bid=1.1,ask=1.1002,last=1.1,time=1)
    def copy_rates_from(self,*a,**k): return [types.SimpleNamespace(time=1,open=1.1,high=1.101,low=1.099,close=1.1005,tick_volume=100)]*20
    def history_deals_get(self,*a,**k): return []
    def positions_get(self,*a,**k): return []
    def terminal_info(self): return types.SimpleNamespace(trade_allowed=False, trade_expert=False)
with patch.dict(sys.modules,{'MetaTrader5':MT5()}):
    ck('trading.server.initialize_mt5',srv.initialize_mt5)
    ck('trading.server.get_rates_for_symbol',lambda:srv.get_rates_for_symbol('EURUSD','M15',20,1,'demo'))
    ck('trading.server.place_order.disabled_guard',lambda:srv.place_order({'account_mode':'demo','symbol':'EURUSD','type':'BUY','price':1.1,'volume':0.1,'sl':1.09,'tp':1.12}))

import skills.trading.trading_skill as legacy
class DummyExec:
    success=True; output={'success':True}; error=None
with patch('core.execution_gateway.GATEWAY.execute',return_value=DummyExec()): ck('trading.legacy.execute_approved_trade',lambda:legacy.execute_approved_trade({'confirmation_phrase':'VALID'},'VALID'))

import skills.trading_skill.position_monitor as pm_mod
pm=pm_mod.PositionMonitor(Mock()); pm.bridge.request.return_value={'success':True,'closed':[],'failed':[]}
ck('trading.position.modify',lambda:pm.modify_position(1,'EURUSD',1.09,1.12,'demo'))
ck('trading.position.close_single',lambda:pm.close_single(1,'EURUSD','demo'))
ck('trading.position.flatten_all',lambda:pm.flatten_all('demo'))
with patch.object(pm,'monitor_once',return_value={'status':'connected','positions':[{'ticket':1,'symbol':'EURUSD','type':'BUY','price_open':1.1,'sl':1.09,'tp':1.12,'profit':2}], 'decisions':[{'ticket':1,'symbol':'EURUSD','action':'BREAK_EVEN','suggested_stop':1.101,'reason':'test'}]}): ck('trading.position.apply_management',lambda:pm.apply_management('demo',{}))

import skills.trading_skill.profiles as prof
ck('trading.profile.normalize',lambda:prof.normalize_trading_mode('day_trading'))
import skills.trading_skill.risk as risk
ck('trading.risk.validate_profile_limits',lambda:risk.validate_profile_limits({'equity':1000,'daily_loss_percent':0,'weekly_loss_percent':0,'margin_level':500},[],prof.get_trading_profile('DAY_TRADING'),new_risk_percent=.5,symbol='EURUSD'))
import skills.trading_skill.safety as safety
ck('trading.safety.validate_trade_setup',lambda:safety.validate_trade_setup(symbol='EURUSD',direction='BUY',entry=1.1,stop_loss=1.09,take_profit=1.13,risk_amount=5,risk_percent=.5,volume=.1,margin_required=10,free_margin_after=990,minimum_free_margin=0,projected_margin_level=1000,spread_pips=.8,minimum_rr=2,maximum_spread_pips=1.5))
import skills.trading_skill.strategy as strategy
ck('trading.strategy.identify_setup',lambda:strategy.identify_setup('BUY',{},{}))

import skills.trading_skill.wine_server as ws
# close/flatten safe path with account in demo but trade permission disabled.
with patch.dict(sys.modules,{'MetaTrader5':MT5()}):
    ck('trading.wine.close_position',lambda:ws.close_position({'account_mode':'demo','ticket':1,'symbol':'EURUSD'}))
    ck('trading.wine.close_all_positions',lambda:ws.close_all_positions({'account_mode':'demo'}))

import skills.trading_skill.service as service
ck('service.get_account_snapshot',lambda:service.get_account_snapshot('demo'))
with patch.object(service.position_monitor,'get_open_positions',return_value={'status':'connected','positions':[]}): ck('service.monitor_positions',lambda:service.monitor_positions('demo'))
with patch.object(service,'get_account_snapshot',return_value={'snapshot':types.SimpleNamespace(connected=False)}): ck('service.enforce_loss_limits',lambda:service.enforce_loss_limits('demo'))
with patch.object(service.position_monitor,'close_single',return_value={'success':True}),patch.object(service.position_monitor,'flatten_all',return_value={'success':True}):
    ck('service.close_position_manual',lambda:service.close_position_manual(1,'EURUSD','demo')); ck('service.close_all_positions_manual',lambda:service.close_all_positions_manual('demo'))
with patch.object(service,'scan_universe',return_value={'state':'WAITING','scanned':1,'results':[]}):
    ck('service.scan_report',lambda:service.scan_report('demo','DAY_TRADING',['EURUSD'])); ck('service.monitor_universe',lambda:service.monitor_universe('demo','DAY_TRADING',['EURUSD']))
with patch.object(service,'enforce_loss_limits',return_value={'triggered':False}),patch.object(service,'get_account_snapshot',return_value={'snapshot':types.SimpleNamespace(connected=False)}): ck('service.decide_and_act',lambda:service.decide_and_act('demo','DAY_TRADING',['EURUSD']))
with patch.object(service.workflow('DAY_TRADING'),'prepare',return_value=types.SimpleNamespace(state=types.SimpleNamespace(value='WAITING'),decision_state=None,message='validation',plan=None,details={})): ck('service.prepare_trade_payload',lambda:service.prepare_trade_payload('EURUSD','demo',.5,'DAY_TRADING'))
ck('service.approve_execute_missing',lambda:(service.approve_trade('missing'),service.execute_trade('missing')))

import skills.trading_skill.workflow as workflow_mod
w=workflow_mod.TradingWorkflow(Mock()); ck('workflow.approve_execute_missing',lambda:(w.approve('missing'),w.execute('missing')))

import skills.voice.clap_listener as clap
class Audio:
    paInt16=8
    def open(self,**kwargs):
        class S:
            def read(self,*a,**k): return b'\\x00\\x00'*1024
            def stop_stream(self): pass
            def close(self): pass
        return S()
    def terminate(self): pass
with patch.object(clap,'pyaudio',Audio()),patch.object(clap,'audioop',types.SimpleNamespace(rms=lambda c,w:2000)):
    ck('voice.clap.detect_double_clap',lambda:clap.ClapListener().detect_double_clap(timeout=.15))

import skills.wifi_control.router_client as wr
with patch.object(wr,'_ensure_router_session',return_value=None),patch.object(wr,'request_router_command',return_value={'AclMode':'2','WhiteMacList':'','WhiteNameList':'','BlackMacList':'aa:bb:cc;','BlackNameList':'phone;'}),patch.object(wr,'_write_router_command',return_value={'result':'success'}),patch.object(wr,'remove_access_schedule',return_value={'result':'success'}):
    ck('wifi.get_router_status',lambda:wr.get_router_status('127.0.0.1')); ck('wifi.list_disconnected_devices',lambda:wr.list_disconnected_devices('127.0.0.1')); ck('wifi.set_acl',lambda:wr.set_access_control_list({'mode':'2','white_macs':'','white_names':'','black_macs':'','black_names':''},'127.0.0.1'))
    ck('wifi.allow_duration',lambda:wr.allow_device_for_duration('aa:bb:cc',1,'127.0.0.1'))
    if wr._timed_access_timers.get('aa:bb:cc'): wr._timed_access_timers['aa:bb:cc'].cancel()
class Resp:
    headers={'Set-Cookie':'s=1;'}
    def read(self,*args): return b'{"result":"0"}'
    def __enter__(self): return self
    def __exit__(self,*args): return False
with patch.object(wr,'urlopen',return_value=Resp()), patch.object(wr,'request_router_command',return_value={'LD':'challenge'}): ck('wifi.login_router',lambda:wr.login_router('127.0.0.1','password'))

print('SUMMARY',len(R),sum(1 for x in R if x[1]=='PASS'),sum(1 for x in R if x[1]=='FAIL'))
for x in R:
    if x[1]!='PASS': print('FAIL_DETAIL',x)
sys.exit(1 if any(x[1]=='FAIL' for x in R) else 0)
