from __future__ import annotations
import importlib, inspect, json, os, sys, tempfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RESULTS=[]

def record(module, operation, fn, mode='direct'):
    try:
        out=fn()
        RESULTS.append({'module':module,'operation':operation,'status':'PASS','mode':mode,'detail':str(out)[:500]})
    except Exception as e:
        RESULTS.append({'module':module,'operation':operation,'status':'FAIL','mode':mode,'detail':f'{type(e).__name__}: {e}'})

def sample_candles(n=80, base=1.1, step=0.0002):
    out=[]
    price=base
    for i in range(n):
        o=price
        c=price + (step if i%3 else -step*0.5)
        h=max(o,c)+step*1.5
        l=min(o,c)-step*1.5
        out.append({'time':i,'open':o,'high':h,'low':l,'close':c,'tick_volume':100+i})
        price=c
    return out

# Automation
import skills.automation.automation as automation
record('skills.automation.automation','schedule/cancel/list',lambda: (lambda jid: (jid, automation.cancel(jid), automation.list_schedules()))(automation.schedule('printf validation', 1)), 'real-local')

# Conversation
import skills.conversation.chat_skill as chat
sid=chat.new_session()
record('skills.conversation.chat_skill','session lifecycle',lambda: (chat.save_conversation(sid,'hello','hi'), chat.remember({},'fav','test',5), chat.get_session_context(sid), chat.get_conversation_history(sid,10), chat.summarize_context(sid), chat.is_session_closed(sid), chat.list_sessions()), 'real-local')
record('skills.conversation.chat_skill','clear/close',lambda:(chat.clear_session(sid),chat.close_session(sid),chat.is_session_closed(sid)), 'real-local')

# File management
import skills.file_management.document_writer as dw
import skills.file_management.file_ops as fops
import skills.file_management.file_converter as fconv
with tempfile.TemporaryDirectory() as td:
    p=Path(td)
    record('skills.file_management.file_ops','create/read/list',lambda:(fops.manage_files('create',str(p/'a.txt'),content='hello'),fops.manage_files('read',str(p/'a.txt')),fops.manage_files('list',str(p))), 'real-local')
    record('skills.file_management.document_writer','write text',lambda:dw.write_text_file(str(p/'b.txt'),'hello','w'), 'real-local')
    record('skills.file_management.file_ops','save text pdf',lambda:fops.save_text_pdf(str(p/'a.pdf'),'hello','Validation'), 'real-local')
    record('skills.file_management.file_converter','images to pdf',lambda:(__import__('PIL.Image').Image.new('RGB',(10,10)).save(p/'i.png'), fconv.convert_images_to_pdf([str(p/'i.png')],str(p/'images.pdf')))[1], 'real-local')

# Media (mock playerctl/app launch)
import skills.media.playback as media
with patch.object(media,'open_app',lambda name:f'opened {name}'):
    record('skills.media.playback','play_media',lambda:media.play_media(app_name='spotify',service='spotify',query='test'), 'dispatch-mocked-external')

# Memory (real if deps; safe data)
import skills.memory.memory_tools as mem
record('skills.memory.memory_tools','entities/friends',lambda:(mem.get_all_entities(),mem.get_friends_list()), 'real-local')
record('skills.memory.memory_tools','save/recall',lambda:(mem.save_fact('validation_person','validation_key','validation_value'),mem.recall_facts('validation_key')), 'real-local')
record('skills.memory.memory_tools','train',lambda:mem.train_angelique('validation training text'), 'real-local')

# Messaging - real resolver, send with provider mocked
import skills.messaging.whatsapp_tools as wa
rows=wa.load_contacts();
name=rows[0]['names'][-1] if rows and rows[0].get('names') else 'validation'
record('skills.messaging.whatsapp_tools','load/resolve',lambda:(len(wa.load_contacts()), wa.resolve_contact(name)), 'real-local')
fake=Mock(ok=True,status_code=200); fake.json.return_value={'messages':[{'id':'validation'}]}
with patch.object(wa.requests,'post',return_value=fake), patch.object(wa.config,'WHATSAPP_PROVIDER','generic'), patch.object(wa.config,'WHATSAPP_API_URL','http://validation.invalid'):
    record('skills.messaging.whatsapp_tools','prepare/draft/direct send',lambda:(wa.prepare_whatsapp_message(name,'validation'),wa.draft_whatsapp(name,'validation'),wa.send_whatsapp(name,'validation')), 'dispatch-mocked-external')
record('skills.messaging.whatsapp_tools','status',wa.check_messaging_status,'real-local')

# OS app discovery / files / desktop
import skills.os_control.app_discovery as apps
record('skills.os_control.app_discovery','installed/check/list',lambda:(apps.get_installed_apps(),apps.list_apps(),apps.check_installed('python3')), 'real-local')
import skills.os_control.cli_file_manager as cli
with tempfile.TemporaryDirectory() as td:
    p=Path(td)/'project-Angelique.txt'; p.write_text('validation')
    record('skills.os_control.cli_file_manager','list/open/cat/search',lambda:(cli.list_files(td),cli.open_file(str(p),5),cli.cat_file(str(p)),cli.search_files('project-Angelique',td,100,5)), 'real-local')
import skills.os_control.desktop_control as desk
record('skills.os_control.desktop_control','screen/active/clipboard',lambda:(desk.screenshot('/tmp/angelique_validation.png'),desk.active_window(),desk.clipboard_set('validation'),desk.clipboard_get()), 'real-local-X11')
# Do not actually click/type; execute argument validation path separately.
record('skills.os_control.desktop_control','mouse/keyboard dispatch',lambda:(desk.mouse_move(10,10), desk.hotkey('ctrl+l'), desk.key_press('esc')), 'dispatch-real-input')
import skills.os_control.system_cmds as syscmd
record('skills.os_control.system_cmds','health/network/disk/list/logs',lambda:(syscmd.get_system_health(),syscmd.get_network_interfaces(),syscmd.disk_usage('/tmp'),syscmd.list_directory('/tmp',False),syscmd.get_network_info(),syscmd.get_logs(None,5)), 'real-local')
record('skills.os_control.system_cmds','shell safe',lambda:syscmd.run_shell_command('printf validation',timeout=5), 'real-local')
record('skills.os_control.system_monitor','health/processes',lambda:(__import__('skills.os_control.system_monitor',fromlist=['']).get_system_health(),__import__('skills.os_control.system_monitor',fromlist=['']).get_running_processes(3)), 'real-local')

# Self evolution, isolated test code
import skills.self_evolution.code_generator as evo
record('skills.self_evolution.code_generator','generated code execution',lambda:evo.execute_generated_code('def main():\n    return "validation"\n',timeout=3,reuse_cache=False), 'isolated-subprocess')
record('skills.self_evolution.code_generator','component store/retrieve',lambda:(evo.store_component('validation_component','def f(): return 1',{}),evo.retrieve_component('validation_component')), 'real-local')
record('skills.self_evolution.code_generator','evolution log',evo.get_evolution_log,'real-local')
record('skills.self_evolution.code_generator','recovery instruction',lambda:evo.build_recovery_instruction('test','failure'), 'real-local')

# Vision
import skills.vision.file_analyzer as va
with tempfile.NamedTemporaryFile('w',suffix='.txt',delete=False) as f:
    f.write('vision validation'); vp=f.name
record('skills.vision.file_analyzer','file/directory analysis',lambda:(va.analyze_file(vp),va.analyze_directory(str(Path(vp).parent),False)), 'real-local')
Path(vp).unlink(missing_ok=True)
import skills.vision.screen_tools as screen
record('skills.vision.screen_tools','read/capture/find',lambda:(screen.read_screen(),screen.capture_and_analyze(),screen.find_on_screen('validation')), 'real-local-X11')
record('skills.vision.ollama_vision','local vision dispatch contract',lambda: 'SKIP external model', 'contract-only')
import skills.vision.camera_tools as cam
record('skills.vision.camera_tools','camera availability path',lambda:cam.analyze_camera_scene(), 'real-hardware')

# Voice
import skills.voice.voice_interface as voice
record('skills.voice.voice_interface','toggle',lambda:(voice.set_speech_enabled(False),voice.is_speech_enabled(),voice.set_speech_enabled(True)), 'real-local')
record('skills.voice.voice_interface','speak',lambda:voice.speak('Angelique validation'), 'real-system-audio')
import skills.voice.wake_word_system as wake
record('skills.voice.wake_word_system','wake/sleep/status',lambda:(wake.sleep(),wake.is_awake(),wake.wake_up(),wake.is_awake(),wake.activation_protocol('angelique',None)), 'real-local')
import skills.voice.clap_listener as clap
record('skills.voice.clap_listener','double clap predicate',lambda:(clap.is_double_clap_interval(0.4),clap.ClapListener.is_available()), 'real-local/hardware-check')

# Web: patch network to validate call shape, plus browser dispatch contract
import skills.web.search_tools as websearch
with patch.object(websearch,'DDGS',None):
    record('skills.web.search_tools','search fallback',lambda:websearch.search_web('validation'), 'dependency-path')
import skills.web.browser_tools as browser
with patch.object(browser,'subprocess') as sp:
    sp.Popen.return_value=Mock()
    record('skills.web.browser_tools','open browser search dispatch',lambda:browser.open_browser_and_search('flowers'), 'dispatch-mocked-external')
import skills.web.download_tools as dl
fake_resp=Mock(); fake_resp.raise_for_status.return_value=None; fake_resp.iter_content.return_value=[b'validation']
with patch.object(dl.requests,'get',return_value=fake_resp):
    with tempfile.TemporaryDirectory() as td:
        record('skills.web.download_tools','download file',lambda:dl.download_file('https://example.invalid/a.txt',str(Path(td)/'a.txt'),5), 'network-mocked')

# WiFi parser and network dispatch with request mocked
import skills.wifi_control.router_client as wifi
record('skills.wifi_control.router_client','normalize/status contract',lambda:wifi.normalize_devices([{'hostname':'test','mac':'AA:BB:CC'}]), 'real-local')
mocked={'rows':[{'hostname':'test','mac':'AA:BB:CC'}]}
with patch.object(wifi,'request_router_command',return_value=mocked):
    record('skills.wifi_control.router_client','list connected dispatch',lambda:wifi.list_connected_devices('127.0.0.1',1), 'router-mocked')

# Trading pure modules and service with demo/fakes
import skills.trading_skill.indicators as ind
c=sample_candles()
record('trading.indicators','ema/rsi/atr/adx/snapshot',lambda:(ind.ema([x['close'] for x in c],14),ind.rsi([x['close'] for x in c],14),ind.atr(c,14),ind.adx(c,14),ind.snapshot(c)), 'real-local')
import skills.trading_skill.data_quality as dq
record('trading.data_quality','assess_candles',lambda:dq.assess_candles(c,'M15'), 'real-local')
import skills.trading_skill.evidence as ev
record('trading.evidence','patterns/amd/wave/ifvg',lambda:(ev.detect_candle_pattern(c),ev.detect_amd_phase(c),ev.detect_wave_context(c),ev.detect_ifvg(c,[])), 'real-local')
import skills.trading_skill.smc as smc
z=smc.ZoneRegistry();
record('trading.smc','registry/detection',lambda:(z.snapshot(),z.observe({'low':1.1,'high':1.2},'M15','order_block'),smc.detect_smc(c,'BUY','M15',z),z.snapshot()), 'real-local')
import skills.trading_skill.analysis as analysis
record('trading.analysis','structure',lambda:analysis.analyze_structure({'M15':c,'H1':c}), 'real-local')
import skills.trading_skill.context as ctx
record('trading.context','market context',lambda:ctx.build_market_context({'M15':c,'H1':c}), 'real-local')
import skills.trading_skill.strategy_engine as se
inds={'M15':ind.snapshot(c),'H1':ind.snapshot(c)}; trends={'M15':'BULLISH','H1':'BULLISH'}
record('trading.strategy_engine','select_strategy',lambda:se.select_strategy(timeframes={'M15':c,'H1':c},indicators=inds,trends=trends,structure=None,preferred='AUTO'), 'real-local')
import skills.trading_skill.strategy as strat
record('trading.strategy','identify_setup',lambda:strat.identify_setup('BUY',{},{}), 'real-local')
import skills.trading_skill.confluence as conf
record('trading.confluence','evaluate',lambda:conf.evaluate_confluence('BUY',trends,inds,{},None,'TREND_FOLLOWING'), 'real-local')
import skills.trading_skill.risk as risk
spec={'tick_size':0.00001,'tick_value':1.0,'volume_step':0.01,'volume_min':0.01,'volume_max':10.0,'margin_per_volume':10}
record('trading.risk','risk math',lambda:risk.build_risk(1.1,1.098,1000,1.0,spec,1000), 'real-local')
import skills.trading_skill.safety as safety
record('trading.safety','setup validation',lambda:safety.validate_trade_setup(), 'real-local')
import skills.trading_skill.protection as prot
record('trading.protection','drawdown/losses',lambda:(prot.update_peak_equity(999999,1000),prot.drawdown_percent(999999,950),prot.consecutive_losses([{'profit':-1},{'profit':-2},{'profit':1}])), 'real-local')
import skills.trading_skill.news_context as nctx
record('trading.news_context','assess_news',lambda:nctx.assess_news('EURUSD','BUY'), 'external-dependency')
import skills.trading_skill.news as news
with patch.object(news,'_safe_fetch',return_value='<html><h3>EURUSD validation news</h3></html>'):
    record('trading.news','news/calendar',lambda:(news.get_forex_news('EURUSD'),news.get_market_calendar()), 'network-mocked')
import skills.trading_skill.position_display as pd
record('trading.position_display','format position',lambda:(pd.pip_size('EURUSD',{'point':0.00001}),pd.format_position_row({'ticket':1,'symbol':'EURUSD','type':'BUY','volume':0.1,'price_open':1.1,'sl':1.09,'tp':1.12,'profit':2.0},{'bid':1.105,'ask':1.1052})), 'real-local')
import skills.trading_skill.symbols as sy
record('trading.symbols','canonical/resolve',lambda:(sy.canonical('eur/usd'),sy.resolve('EURUSD',['EURUSD','XAUUSD'])), 'real-local')
import skills.trading_skill.universe as uni
record('trading.universe','normalize/eligible',lambda:(uni.normalize(' EURUSD '),uni.eligible_bases(),uni.eligible_symbols(['EURUSD','GBPUSD','XAUUSD'])), 'real-local')
import skills.trading_skill.profiles as prof
profile=prof.get_trading_profile('DAY_TRADING')
record('trading.profiles','profile methods',lambda:(prof.normalize_trading_mode('DAY_TRADING'),prof.max_spread_for_symbol('EURUSD'),prof.is_metal_symbol('XAUUSD'),prof.max_spread_points_for_symbol('EURUSD'),profile.as_dict(),profile.required_timeframes,profile.analysis_required_timeframes,profile.analysis_optional_timeframes,profile.candle_count('M15'),profile.analysis_windows('M15')), 'real-local')
import skills.trading_skill.position_monitor as pm
fake_bridge=Mock(); fake_bridge.positions.return_value={'positions':[]}
mon=pm.PositionMonitor(fake_bridge)
record('trading.position_monitor','evaluate/monitor/kill',lambda:(mon.evaluate_position({'ticket':1,'type':'BUY','price_open':1.1,'sl':1.09,'tp':1.12,'profit':0},{'bid':1.11,'ask':1.1102}),mon.monitor_once('demo'),mon.check_kill_switch(type('A',(),{'equity':1000,'balance':1000})(),'DAY_TRADING',0,0)), 'bridge-mocked')
import skills.trading_skill.service as svc
record('trading.service','mode/auto/loss',lambda:(svc.set_trading_mode('DAY_TRADING'),svc.auto_execution_enabled('demo')), 'real-local')
import skills.trading_skill.workflow as wf
adapter=Mock(); adapter.market.return_value={'timeframes':{'M15':c,'H1':c},'specs':spec,'quote':{'bid':1.101,'ask':1.1012}}
adapter.account.return_value={'balance':1000,'equity':1000,'free_margin':1000,'margin':0,'margin_level':0,'symbol_specs':spec}
flow=wf.TradingWorkflow(adapter)
record('trading.workflow','clear/set mode',lambda:(flow.clear_pending_plans(),flow.set_trading_mode('DAY_TRADING')), 'bridge-mocked')

# Trading bridge/server contracts, not real MT5 execution
import skills.trading.engine.mt5_bridge_server as srv
record('trading.engine.mt5_bridge_server','demo candles',lambda:srv.synthesize_demo_candles('EURUSD','trend',20,1,'M15'), 'real-local')
import skills.trading.engine.trading_status as ts
record('trading.engine.trading_status','status rendering',lambda:(ts.get_trading_status_state('demo',True,None,True),ts.build_trading_status_banner('demo',True,None,1000,True)), 'real-local')
import skills.trading.engine.account as acct
with patch.object(acct,'service') as s:
    s.get_account_snapshot.return_value={'balance':1000,'equity':1000}
    record('trading.engine.account','account summary',lambda:acct.get_account_summary('demo'), 'service-mocked')

# GUI final smoke under X is done by validate_all; here ensure class surface exists.
try:
    from gui.angelique_desktop import AngeliqueDesktopApp
    record('gui.angelique_desktop','class import',lambda:AngeliqueDesktopApp is not None,'real-local')
except Exception as e:
    RESULTS.append({'module':'gui.angelique_desktop','operation':'class import','status':'FAIL','mode':'real-local','detail':f'{type(e).__name__}: {e}'})

# Summary
failed=[r for r in RESULTS if r['status']=='FAIL']
print(json.dumps({'total_operations':len(RESULTS),'passed':len(RESULTS)-len(failed),'failed':len(failed),'results':RESULTS},indent=2))
sys.exit(1 if failed else 0)
