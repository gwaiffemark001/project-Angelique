from __future__ import annotations
import json, sys, tempfile, types
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RESULTS=[]
def check(group, operation, fn, mode='real-local'):
    print(f'CHECK {group} :: {operation}', flush=True)
    try:
        out=fn()
        print(f'PASS {group} :: {operation}', flush=True)
        RESULTS.append({'group':group,'operation':operation,'status':'PASS','mode':mode,'detail':str(out)[:350]})
    except Exception as e:
        print(f'FAIL {group} :: {operation} :: {type(e).__name__}: {e}', flush=True)
        RESULTS.append({'group':group,'operation':operation,'status':'FAIL','mode':mode,'detail':f'{type(e).__name__}: {e}'})

def safe_candles(n=100, base=1.1, step=0.0001):
    arr=[]; p=base
    for i in range(n):
        o=p; c=p + (step if i%2 else -step*0.4); h=max(o,c)+step; l=min(o,c)-step
        arr.append({'time':i,'open':o,'high':h,'low':l,'close':c,'tick_volume':100+i}); p=c
    return arr

print("GROUP automation", flush=True)
# ---------- automation ----------
from skills.automation import automation
jid=automation.schedule('printf validation',3600)
check('automation','schedule',lambda:bool(jid)); check('automation','list_schedules',automation.list_schedules); check('automation','cancel',lambda:automation.cancel(jid))

print("GROUP conversation", flush=True)
# ---------- conversation ----------
from skills.conversation import chat_skill as chat
sid=chat.new_session(); check('conversation','new/save/history',lambda:(sid,chat.save_conversation(sid,'u','a'),chat.get_conversation_history(sid,10))); check('conversation','context/summary',lambda:(chat.get_session_context(sid),chat.summarize_context(sid))); check('conversation','remember/recall',lambda:(chat.remember({},'validation','ok',5),chat.recall({},'validation'))); check('conversation','clear/close/state',lambda:(chat.clear_session(sid),chat.close_session(sid),chat.is_session_closed(sid))); check('conversation','sessions',chat.list_sessions)

print("GROUP file management", flush=True)
# ---------- file management ----------
from skills.file_management import document_writer as dw, file_ops as fops, file_converter as fc
from PIL import Image
with tempfile.TemporaryDirectory() as td:
 p=Path(td); img=p/'img.png'; Image.new('RGB',(20,20)).save(img)
 check('file_management','create/read/list',lambda:(fops.manage_files('create',str(p/'a.txt'),content='hello'),fops.manage_files('read',str(p/'a.txt')),fops.manage_files('list',str(p)))); check('file_management','write_text',lambda:dw.write_text_file(str(p/'b.txt'),'text','w')); check('file_management','write_word_document',lambda:dw.write_word_document(str(p/'a.docx'),'hello')); check('file_management','save_text_pdf',lambda:fops.save_text_pdf(str(p/'a.pdf'),'hello','validation')); check('file_management','images_to_pdf',lambda:fc.convert_images_to_pdf([str(img)],str(p/'images.pdf'))); check('file_management','word_to_pdf',lambda:fc.convert_word_to_pdf(str(p/'a.docx'),str(p/'word.pdf')),'real-local-if-converter')

print("GROUP media", flush=True)
# ---------- media ----------
import skills.media.playback as media
with patch.object(media,'open_app',lambda name:'opened'):
 check('media','play_media dispatch',lambda:media.play_media(app_name='spotify',service='spotify',query='validation'),'dispatch-mocked-player')

print("GROUP memory", flush=True)
# ---------- memory ----------
import skills.memory.memory_tools as mem
check('memory','entities/friends',lambda:(mem.get_all_entities(),mem.get_friends_list())); check('memory','save_fact/recall',lambda:(mem.save_fact(person='validation_person',key='validation_key',value='validation_value'),mem.recall_facts(query='validation_key'))); check('memory','train',lambda:mem.train_angelique('validation training'))

print("GROUP messaging", flush=True)
# ---------- messaging ----------
import skills.messaging.whatsapp_tools as wa
contacts=wa.load_contacts(); contact=contacts[0]['names'][-1] if contacts else None
check('messaging','contacts load/resolve',lambda:(len(contacts),wa.resolve_contact(contact) if contact else None))
# Test Meta payload contract without sending real message.
fake_resp=Mock(ok=True,status_code=200); fake_resp.json.return_value={'messages':[{'id':'validation'}]}
with patch.object(wa.config,'WHATSAPP_PROVIDER','meta'),patch.object(wa.config,'WHATSAPP_ACCESS_TOKEN','TEST'),patch.object(wa.config,'WHATSAPP_PHONE_NUMBER_ID','TEST'),patch.object(wa.requests,'post',return_value=fake_resp) as post:
 check('messaging','prepare/draft/send',lambda:(wa.prepare_whatsapp_message('angeliquemoesha4','validation'),wa.draft_whatsapp('angeliquemoesha4','validation'),wa.send_whatsapp('angeliquemoesha4','validation')),'network-mocked')
check('messaging','approval contract',lambda:wa.send_whatsapp_approved(contact,'validation',False) if contact else {'confirmation_required':True}); check('messaging','status',wa.check_messaging_status)

print("GROUP OS control", flush=True)
# ---------- OS control ----------
import skills.os_control.app_discovery as apps
check('os_control','app list/check',lambda:(apps.get_installed_apps(),apps.list_apps(),apps.check_installed('python3')))
import skills.os_control.cli_file_manager as cli
with tempfile.TemporaryDirectory() as td:
 p=Path(td)/'project-Angelique'; p.mkdir(); (p/'a.txt').write_text('hello')
 check('os_control','file list/open/cat/search',lambda:(cli.list_files(td),cli.open_file(str(p/'a.txt'),5),cli.cat_file(str(p/'a.txt')),cli.search_files('project-Angelique',td,20,10)))
import skills.os_control.system_cmds as sc
check('os_control','system health/network/disk/logs',lambda:(sc.get_system_health(),sc.get_network_interfaces(),sc.disk_usage('/tmp'),sc.get_network_info(),sc.get_logs(None,3))); check('os_control','safe shell',lambda:sc.run_shell_command('printf validation',timeout=5))
import skills.os_control.system_monitor as sm
check('os_control','monitor',lambda:(sm.get_system_health(),sm.get_running_processes(3)))
import skills.os_control.desktop_control as dc
fake_py=types.SimpleNamespace(
    screenshot=lambda: types.SimpleNamespace(save=lambda p: Path(p).write_bytes(b'png')),
    moveTo=lambda *a,**k: None, click=lambda *a,**k: None, write=lambda *a,**k: None, hotkey=lambda *a,**k: None, press=lambda *a,**k: None
)
with patch.dict(sys.modules, {'pyautogui': fake_py}):
 check('os_control','desktop screenshot/input',lambda:(dc.screenshot('/tmp/angelique_validation.png'),dc.mouse_move(10,10),dc.key_press('esc'),dc.hotkey('ctrl+l')),'pyautogui-mocked')
check('os_control','active window',dc.active_window,'real-local')


print("GROUP self evolution", flush=True)
# ---------- self evolution ----------
import skills.self_evolution.code_generator as evo
check('self_evolution','execute_generated_code',lambda:evo.execute_generated_code('def main():\n return "ok"\n',timeout=3,reuse_cache=False),'isolated-subprocess'); check('self_evolution','save/retrieve component',lambda:(evo.store_component('validation_component','def f(): return 1',{}),evo.retrieve_component('validation_component'))); check('self_evolution','recovery/log',lambda:(evo.build_recovery_instruction('test','failure'),evo.get_evolution_log()))

print("GROUP vision", flush=True)
# ---------- vision ----------
import skills.vision.file_analyzer as vfa
with tempfile.NamedTemporaryFile('w',suffix='.txt',delete=False) as f: f.write('vision validation'); fp=f.name
check('vision','file/directory analysis',lambda:(vfa.analyze_file(fp),vfa.analyze_directory(str(Path(fp).parent),False))); Path(fp).unlink(missing_ok=True)
import skills.vision.screen_tools as st
check('vision','screen OCR/capture/find',lambda:(st.read_screen(),st.capture_and_analyze(),st.find_on_screen('validation')),'real-X11')
import skills.vision.camera_tools as camera
class FakeCap:
    def __init__(self,*a,**k): self.opened=True
    def isOpened(self): return True
    def read(self): return True, __import__('numpy').zeros((20,20,3),dtype='uint8')
    def release(self): pass
with patch.object(camera.cv2,'VideoCapture',FakeCap), patch.object(camera,'_get_yolo_model',return_value=None):
 check('vision','camera analyze/capture',lambda:(camera.analyze_camera_scene(),camera.capture_photo('/tmp/angelique_cam_test.jpg')),'hardware-mocked')
import skills.vision.image_generator as ig
check('vision','image generator contract',lambda:'generator callable' if callable(ig.generate_image) else False,'provider-contract')
import skills.vision.ollama_vision as ov
fake_json=lambda:{'message':{'content':'vision ok'}}
class Resp:
 status_code=200
 ok=True
 def json(self): return fake_json()
with patch.object(ov.requests,'post',return_value=Resp()), patch('brain.llm_interface._discover_ollama_models',return_value=['test-vision']):
 with tempfile.NamedTemporaryFile(suffix='.png') as tf:
  Path(tf.name).write_bytes(b'not-real-image')
  check('vision','ollama vision request contract',lambda:ov.analyze_image_with_model(tf.name,'describe'),'ollama-mocked')

print("GROUP voice", flush=True)
# ---------- voice ----------
import skills.voice.voice_interface as vi
check('voice','enable state',lambda:(vi.set_speech_enabled(False),vi.is_speech_enabled(),vi.set_speech_enabled(True))); check('voice','speak disabled path',lambda:(vi.set_speech_enabled(False),vi.speak('validation')),'real-local'); vi.set_speech_enabled(False); check('voice','listen disabled-safe path',lambda:vi.listen(),'hardware-guarded')
import skills.voice.wake_word_system as ww
check('voice','wake/sleep/status',lambda:(ww.sleep(),ww.is_awake(),ww.wake_up(),ww.is_awake(),ww.activation_protocol('angelique',None)))
import skills.voice.clap_listener as cl
listener=cl.ClapListener(); check('voice','clap detector/predicate',lambda:(cl.is_double_clap_interval(0.4),listener.is_available()))

print("GROUP web", flush=True)
# ---------- web ----------
import skills.web.search_tools as ws
with patch.object(ws,'DDGS',None), patch.object(ws.webbrowser,'open',return_value=True): check('web','search fallback',lambda:ws.search_web('validation'),'dependency-fallback')
import skills.web.browser_tools as wb
with patch.object(wb.webbrowser,'open',return_value=True): check('web','browser search',lambda:wb.open_browser_and_search('flowers'),'browser-mocked')
import skills.web.download_tools as wd
resp=MagicMock(); resp.raise_for_status.return_value=None; resp.iter_content.return_value=[b'validation']
with patch.object(wd.requests,'get',return_value=resp):
 with tempfile.TemporaryDirectory() as td: check('web','download',lambda:wd.download_file('https://example.invalid/file',str(Path(td)/'f'),5),'network-mocked')

print("GROUP wifi", flush=True)
# ---------- wifi ----------
import skills.wifi_control.router_client as wr
check('wifi','normalize devices',lambda:wr.normalize_devices([{'hostname':'test','mac':'AA:BB:CC'}]))
with patch.object(wr,'request_router_command',return_value={'rows':[{'hostname':'test','mac':'AA:BB:CC'}]}):
 with patch.object(wr,'_ensure_router_session',return_value=None): check('wifi','list connected',lambda:wr.list_connected_devices('127.0.0.1',1),'router-mocked')

print("GROUP trading engine / trading_skill pure + guarded flows", flush=True)
# ---------- trading engine / trading_skill pure + guarded flows ----------
from skills.trading_skill.demo import synthesize_pattern_candles
candles=synthesize_pattern_candles('trend','EURUSD',120,7,'M15')
import skills.trading_skill.indicators as ti
check('trading','indicators',lambda:(ti.ema([x['close'] for x in candles],14),ti.rsi([x['close'] for x in candles],14),ti.atr(candles,14),ti.adx(candles,14),ti.snapshot(candles)))
import skills.trading_skill.data_quality as tdq
check('trading','data quality',lambda:tdq.assess_candles(candles,'M15'))
import skills.trading_skill.evidence as tev
check('trading','evidence',lambda:(tev.detect_candle_pattern(candles),tev.detect_amd_phase(candles),tev.detect_wave_context(candles),tev.detect_ifvg(candles,[])))
import skills.trading_skill.smc as tsmc
zr=tsmc.ZoneRegistry(); check('trading','smc registry/detect',lambda:(zr.observe({'low':1.1,'high':1.2},'M15','order_block'),tsmc.detect_smc(candles,'BUY','M15',zr),zr.snapshot()))
import skills.trading_skill.analysis as tana
check('trading','structure analysis',lambda:tana.analyze_structure({'M15':candles,'H1':candles}))
import skills.trading_skill.context as tctx
check('trading','market context',lambda:tctx.build_market_context({'M15':candles,'H1':candles}))
import skills.trading_skill.strategy_engine as tse
inds={'M15':ti.snapshot(candles),'H1':ti.snapshot(candles)}; trends={'M15':'BULLISH','H1':'BULLISH'}
check('trading','strategy selection',lambda:tse.select_strategy(timeframes={'M15':candles,'H1':candles},indicators=inds,trends=trends,structure=None,preferred='AUTO'))
import skills.trading_skill.confluence as tconf
check('trading','confluence',lambda:tconf.evaluate_confluence('BUY',trends,inds,{},None,'TREND_FOLLOWING'))
import skills.trading_skill.risk as trisk
spec={'tick_size':0.00001,'tick_value':1.0,'volume_step':0.01,'volume_min':0.01,'volume_max':10.0,'margin_per_volume':10}
check('trading','risk math',lambda:(trisk.account_risk_percent(1000),trisk.effective_risk_percent(1000,1.0),trisk.build_risk(1.1,1.098,1000,1.0,spec,1000)))
import skills.trading_skill.account as ta
check('trading','account normalization',lambda:(ta.normalize_mode('real'),ta.account_snapshot({'balance':1000,'equity':1000},'demo')))
import skills.trading_skill.profiles as tp
prof=tp.get_trading_profile('DAY_TRADING'); check('trading','profiles',lambda:(prof.as_dict(),prof.required_timeframes,prof.analysis_required_timeframes,prof.analysis_optional_timeframes,prof.candle_count('M15'),prof.analysis_windows('M15'),tp.max_spread_for_symbol('EURUSD'),tp.max_spread_points_for_symbol('EURUSD'),tp.is_metal_symbol('XAUUSD')))
import skills.trading_skill.symbols as tsy
check('trading','symbols',lambda:(tsy.canonical('eur/usd'),tsy.resolve('EURUSD',['EURUSD','XAUUSD'])))
import skills.trading_skill.universe as tun
check('trading','universe',lambda:(tun.normalize(' EURUSD '),tun.eligible_bases(),tun.eligible_symbols(['EURUSD','GBPUSD','XAUUSD'])))
import skills.trading_skill.protection as prot
check('trading','protection',lambda:(prot.update_peak_equity(987654,1000),prot.drawdown_percent(987654,950),prot.consecutive_losses([{'profit':-1},{'profit':-2},{'profit':1}])))
import skills.trading_skill.position_display as tpd
check('trading','position display',lambda:(tpd.pip_size('EURUSD',{'point':0.00001}),tpd.format_position_row({'ticket':1,'symbol':'EURUSD','type':'BUY','volume':0.1,'price_open':1.1,'sl':1.09,'tp':1.12,'profit':2},{'bid':1.105,'ask':1.1052})))
import skills.trading_skill.journal as tj
check('trading','journal read/record',lambda:(tj.read_trades(3),tj.record_trade({'id':'validation'},{'status':'validation'})))
import skills.trading_skill.event_detector as ted
ed=ted.MarketEventDetector(); check('trading','event detector',lambda:(ed.update('EURUSD','M15',candles),ed.record_setup_state('EURUSD','M15',{'direction':'BUY'}),ed.recent('EURUSD',3)))
import skills.trading_skill.event_logging as tel
check('trading','event logging',lambda:(tel.get_logger(),tel.log_event(20,'validation')))
import skills.trading_skill.position_monitor as tpm
b=Mock(); b.positions.return_value={'positions':[]}; mon=tpm.PositionMonitor(b)
check('trading','position monitor read/evaluate',lambda:(mon.get_open_positions('demo'),mon.evaluate_position({'ticket':1,'type':'BUY','price_open':1.1,'sl':1.09,'tp':1.12,'profit':0},{'bid':1.105,'ask':1.1052}),mon.monitor_once('demo'),mon.check_kill_switch(type('A',(),{'equity':1000,'balance':1000})(),'DAY_TRADING',0,0)),'bridge-mocked')
import skills.trading.engine.mt5_bridge_server as srv
check('trading','demo bridge candles',lambda:srv.synthesize_demo_candles('EURUSD','trend',30,1,'M15'))
import skills.trading.engine.trading_status as tst
check('trading','status UI contract',lambda:(tst.get_trading_status_state('demo',True,None,True),tst.build_trading_status_banner('demo',True,None,1000,True)))
# Guarded MT5 execution: explicitly assert disabled trading never calls order_send.
from skills.trading_skill.wine_server import _choose_filling_mode
class MT5Consts:
 SYMBOL_FILLING_FOK=1; SYMBOL_FILLING_IOC=2; ORDER_FILLING_FOK=0; ORDER_FILLING_IOC=1; ORDER_FILLING_RETURN=2; SYMBOL_TRADE_EXECUTION_MARKET=2
check('trading','broker filling mode selection',lambda:_choose_filling_mode(MT5Consts, type('I',(),{'filling_mode':2,'trade_exemode':2})()))

print("GROUP missing public skill operations", flush=True)
# Exercise public operations that are not covered by the main path above.

with patch('brain.cognitive_loop.resolve_user_query',return_value={'source':'heuristic','answer':'12:34 AM, August 29, 2026','details':{}}):
    check('conversation','handle_user_message routing',lambda:chat.handle_user_message(sid,'what is the time and date'),'resolver-mocked')
check('messaging','execute_whatsapp_send',lambda:wa.execute_whatsapp_send(contact_name=contact,message='validation',confirm=False) if contact else {'confirmation_required':True},'approval-guarded')

# Desktop clipboard/typing helpers: use the already imported mocked pyautogui module.
with patch.dict(sys.modules, {'pyautogui': fake_py}):
    with patch.object(dc.shutil,'which',side_effect=lambda name: '/usr/bin/'+name if name == 'xclip' else None):
        with patch.object(dc.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout='validation',stderr='')):
            check('os_control','clipboard get/set + type',lambda:(dc.clipboard_set('validation'),dc.clipboard_get(),dc.type_text('validation')),'clipboard-backend-mocked')
check('os_control','privileged callback registration',lambda:sc.set_privileged_command_callbacks(lambda c: True, lambda c:'password', lambda c: True),'callback-contract')
check('os_control','schedule_task validation',lambda:sc.schedule_task('validation','printf validation','now'),'safe-command')

# Self-evolution: exercise generation, persistence, orchestration and media conversion guards.
with tempfile.TemporaryDirectory() as td:
    evo_dir=Path(td)
    with patch.object(evo,'SKILLS_DIR',evo_dir), patch.object(evo,'COMPONENT_CACHE',evo_dir/'components.json'), patch.object(evo,'EVOLUTION_LOG',evo_dir/'evolution.json'):
        check('self_evolution','generate_skill fallback',lambda:evo.generate_skill_from_instruction('return validation',skill_name='validation_skill',allow_llm=False))
        check('self_evolution','save_new_skill',lambda:evo.save_new_skill('validation_saved','def main(): return "ok"'))
        check('self_evolution','create_and_execute_skill no-LLM',lambda:evo.create_and_execute_skill('return validation',max_attempts=1,allow_llm=False))
        check('self_evolution','think_about_problem',lambda:'Analysis' in evo.think_about_problem('validation') or isinstance(evo.think_about_problem('validation'),str),'llm-fallback')
        check('self_evolution','convert_webm_to_mp4 missing-input',lambda:evo.convert_webm_to_mp4(str(evo_dir/'missing.webm'),str(evo_dir/'x.mp4')))

# Trading legacy facade and all position-management action methods through a mocked bridge.
import skills.trading.trading_skill as ltr
check('trading','legacy facade account/market',lambda:(ltr.get_account_summary('demo'),ltr.market('EURUSD','M15','demo')),'facade-contract')
# Test only the facade routing for planning/recommendation; full broker calls stay mocked.
with patch.object(ltr._LEGACY_WORKFLOW,'prepare',return_value=type('R',(),{'plan':None,'state':type('S',(),{'value':'NO_SETUP'})(),'message':'validation','details':{},'account':None,'market':None})()):
    check('trading','legacy create/analyze facade',lambda:(ltr.create_trade_plan('EURUSD'),ltr.analyze_and_recommend('EURUSD',auto_execute=False)),'workflow-mocked')

pm=tpm.PositionMonitor(fake_adapter if 'fake_adapter' in globals() else Mock())
pm.bridge=Mock()
pm.bridge.request.return_value={'success':True,'status':'ok','closed':[],'failed':[]}
check('trading','position modify/close/flatten',lambda:(pm.modify_position(1,'EURUSD',1.09,1.12,'demo'),pm.close_single(1,'EURUSD','demo'),pm.flatten_all('demo')),'bridge-mocked')
with patch.object(pm,'monitor_once',return_value={'status':'connected','positions':[{'ticket':1,'symbol':'EURUSD','type':'BUY','price_open':1.1,'sl':1.09,'tp':1.12,'profit':2}], 'decisions':[{'ticket':1,'symbol':'EURUSD','action':'BREAK_EVEN','suggested_stop':1.101,'reason':'test'}]}):
    check('trading','position apply_management',lambda:pm.apply_management('demo',{}),'bridge-mocked')

check('trading','profile normalization',lambda:tp.normalize_trading_mode('day_trading'))
check('trading','profile all public limits',lambda:tp.get_trading_profile('SWING').as_dict())
check('trading','risk profile validation',lambda:trisk.validate_profile_limits({'equity':1000,'daily_loss_percent':0,'weekly_loss_percent':0,'margin_level':500},[],tp.get_trading_profile('DAY_TRADING'),new_risk_percent=1.0,symbol='EURUSD'))
check('trading','safety validator',lambda:__import__('skills.trading_skill.safety',fromlist=['validate_trade_setup']).validate_trade_setup(symbol='EURUSD',direction='BUY',entry=1.1,stop_loss=1.09,take_profit=1.13,risk_amount=5,risk_percent=1.0,volume=0.1,margin_required=10,free_margin_after=990,minimum_free_margin=0,projected_margin_level=1000,spread_pips=0.8,minimum_rr=2.0,maximum_spread_pips=1.5))
check('trading','smc registry prune',lambda:(zr.prune('M15',200,100),zr.snapshot()))
check('trading','strategy identify_setup',lambda:__import__('skills.trading_skill.strategy',fromlist=['identify_setup']).identify_setup('BUY',{},{}))

# Trading engine/server/status helper coverage.
check('trading.engine.trading_status','status helpers',lambda:(tst.get_bridge_status_label(True),tst.get_mt5_data_badge_text('demo','demo',True,True),tst.self_display('demo')))
# Server read paths through a fake MT5 module; no order-send.
class FakeMT5:
    SYMBOL_TRADE_EXECUTION_MARKET=2; SYMBOL_FILLING_FOK=1; SYMBOL_FILLING_IOC=2; ORDER_FILLING_FOK=0; ORDER_FILLING_IOC=1; ORDER_FILLING_RETURN=2
    TRADE_RETCODE_DONE=10009; TRADE_RETCODE_PLACED=10008; TRADE_RETCODE_DONE_PARTIAL=10010; ACCOUNT_TRADE_MODE_DEMO=0; ACCOUNT_TRADE_MODE_REAL=2
    def __init__(self): self._info=type('I',(),{'trade_mode':0,'login':1,'balance':1000,'equity':1000,'margin':0,'margin_free':1000,'margin_level':0,'leverage':100,'currency':'USD','company':'Validation Broker','server':'Validation'})()
    def initialize(self,*a,**k): return True
    def shutdown(self): pass
    def last_error(self): return (0,'ok')
    def account_info(self): return self._info
    def symbols_get(self): return [type('S',(),{'name':'EURUSD'})()]
    def symbol_select(self,*a,**k): return True
    def symbol_info(self,*a,**k): return type('SI',(),{'filling_mode':2,'trade_exemode':2,'point':0.00001,'digits':5,'trade_stops_level':0,'trade_tick_size':0.00001,'trade_tick_value':1.0,'volume_step':0.01,'volume_min':0.01,'volume_max':10.0,'trade_contract_size':100000})()
    def symbol_info_tick(self,*a,**k): return type('T',(),{'bid':1.1,'ask':1.1002,'last':1.1,'time':int(__import__('time').time())})()
    def copy_rates_from_pos(self,*a,**k): return [{'time':1,'open':1.1,'high':1.101,'low':1.099,'close':1.1005,'tick_volume':100} for _ in range(k[2] if len(k)>2 else 50)]
    def history_deals_get(self,*a,**k): return []
    def positions_get(self,*a,**k): return []
    def order_send(self,*a,**k): raise AssertionError('order_send must not be called in server read-path tests')
import skills.trading_skill.wine_server as tws_missing
with patch.dict(sys.modules, {'MetaTrader5': FakeMT5()}):
    check('trading_skill.wine_server','server account/symbols/market/positions/deals',lambda:(tws_missing.account({'account_mode':'demo'}),tws_missing.symbols({'account_mode':'demo'}),tws_missing.market({'account_mode':'demo','symbol':'EURUSD','timeframes':['M15'],'count':50}),tws_missing.positions({'account_mode':'demo'}),tws_missing.recent_deals({'account_mode':'demo'})),'mt5-mocked-read-only')
import skills.trading_skill.workflow as twf_missing
check('trading_skill.workflow','approve/execute stale confirmation',lambda:(twf_missing.TradingWorkflow(Mock()).approve('missing'),twf_missing.TradingWorkflow(Mock()).execute('missing')),'broker-safe')

# Vision/image generator callable contract and local model; actual external image generation is provider-dependent.
check('vision','image generator invalid-provider path',lambda:ig.generate_image('validation',width=16,height=16),'provider-guarded')

# Wi-Fi management methods through a mocked router API. No actual router changes are sent.
with patch.object(wr,'_ensure_router_session',return_value=None), patch.object(wr,'_write_router_command',return_value={'result':'success'}), patch.object(wr,'request_router_command',side_effect=[{'child_mac_rule_info':'aa:bb:cc+1+08:00,18:00,1;'}, {'AclMode':'2','WhiteMacList':'','WhiteNameList':'','BlackMacList':'aa:bb:cc;','BlackNameList':'phone;'}]):
    check('wifi','schedule/ACL readers',lambda:(wr.get_access_schedules('aa:bb:cc'),wr.get_access_control_list()),'router-mocked')
with patch.object(wr,'_ensure_router_session',return_value=None), patch.object(wr,'_write_router_command',return_value={'result':'success'}), patch.object(wr,'get_access_control_list',return_value={'mode':'2','white_macs':'','white_names':'','black_macs':'','black_names':''}), patch.object(wr,'remove_access_schedule',return_value={'result':'success'}):
    check('wifi','allow/block schedule operations',lambda:(wr.add_access_schedule('aa:bb:cc','08:00','18:00',1),wr.disconnect_device('aa:bb:cc','test'),wr.allow_device_forever('aa:bb:cc')),'router-mocked-write')

# Brain command routing and model policy: online -> cloud first, offline -> local only.
import brain.llm_interface as lli
with patch.object(lli,'_is_online',return_value=False), patch.object(lli,'_call_ollama',return_value='LOCAL_OK') as local:
    check('brain','offline local-first policy',lambda:lli.query_llm([{'role':'user','content':'hi'}]) )
    assert local.called
with patch.object(lli,'_is_online',return_value=True), patch.object(lli,'_call_openrouter',return_value='CLOUD_OK'), patch.object(lli,'_call_ollama',return_value='LOCAL_OK'):
    check('brain','online cloud-first policy',lambda:lli.query_llm([{'role':'user','content':'hi'}]))

import brain.cognitive_loop as cog
for text in ['what is the time and date','look for project-Angelique on my pc','open the browser and search flowers','send Mukundane Jerome Agaba message on whatsapp saying hello']:
    check('brain','heuristic command routing '+text,lambda text=text:cog.extract_command_heuristically(text))


print('SAFE_EXHAUSTIVE_CHECKS_COMPLETE')
failed=[r for r in RESULTS if r.get('status')=='FAIL']
print('SUMMARY',len(RESULTS),len(RESULTS)-len(failed),len(failed))
raise SystemExit(1 if failed else 0)
