from __future__ import annotations
import json, os, sys, tempfile, types, subprocess
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.tools as tools
from core.tools_adapter import migrate_registry
from core.tool_registry import GLOBAL_TOOL_REGISTRY
migrate_registry()

RESULTS=[]

def run(name, fn, mode='real-local'):
    try:
        out=fn()
        RESULTS.append({'tool':name,'status':'PASS','mode':mode,'detail':str(out)[:280]})
    except Exception as e:
        RESULTS.append({'tool':name,'status':'FAIL','mode':mode,'detail':f'{type(e).__name__}: {e}'})

root=Path(tempfile.mkdtemp(prefix='angelique-tool-audit-'))
(root/'hello.txt').write_text('hello Angelique\nproject-Angelique\n', encoding='utf-8')

# Safe local functions
local_args={
'open_app': {'app_name':'__angelique_nonexistent_app__'},
'close_app': {'app_name_or_pid':'__angelique_nonexistent_app__'},
'list_apps': {},
'check_installation_status': {'target_name':'python3'},
'run_shell_command': {'command':'printf tool-audit'},
'get_system_health': {},
'get_running_processes': {'limit':2},
'list_directory': {'path':str(root),'recursive':False},
'cli_ls': {'path':str(root)},
'cli_open': {'file_path':str(root/'hello.txt'),'lines':5},
'cli_cat': {'file_path':str(root/'hello.txt'),'max_size':1000},
'search_files': {'query':'project-Angelique','root':str(root),'max_results':10,'max_depth':3},
'disk_usage': {'path':str(root)},
'save_memory': {'person':'AuditUser','key':'tool_audit','value':'ok'},
'recall_memory': {'query':'tool_audit'},
'remember': {'key':'tool_audit','value':'ok','importance':5},
'recall_conversation': {'query':'tool_audit'},
'summarize_context': {},
'start_new_session': {},
'create_and_execute_skill': {'instruction':'return the string AUDIT_OK'},
'execute_generated_code': {'code':'def main():\n    return "AUDIT_OK"','function_name':'main','kwargs':{}},
'save_new_skill': {'skill_name':'validation_tool_skill','code':'def main():\n    return "AUDIT_OK"'},
' think_about_problem': {'problem':'Return a compact test plan.'},
'store_component': {'name':'audit_component','code':'def audit_component():\n    return "ok"'},
'retrieve_component': {'name_query':'audit_component'},
'get_evolution_log': {},
'get_network_info': {},
'get_network_interfaces': {},
'adapter.jarvis.time': {},
'adapter.jarvis.date': {},
'adapter.jarvis.system_info': {},
'adapter.jarviscli.list_plugins': {},
'adapter.calendar.list': {},
'adapter.calendar.get_events': {'calendar_name':None},
'get_logs': {'lines':5},
'open_browser_and_search': {'query':'flowers'},
'check_messaging_status': {},
'media.play_media': {'query':'__angelique_missing_media__'},
'voice.set_enabled': {'enabled':False},
'voice.wake_up': {},
'voice.sleep': {},
'voice.is_awake': {},
'voice.activation_protocol': {},
'automation.schedule': {'command':'printf audit','delay_seconds':3600},
'automation.list': {},
'conversation.new_session': {},
'conversation.history': {},
'conversation.context': {},
'memory.entities': {},
'memory.friends': {},
'voice.clap_available': {},
'system_monitor.get_system_health': {},
'check_mt5_status': {},
'get_account_balance': {'account_mode':'demo'},
'trading_hub_health': {'account_mode':'demo'},
'get_market_calendar': {},
'mouse_move': {'x':1,'y':1},
'clipboard_get': {},
'active_window': {},
'list_scheduled_tasks': {},
'get_account_snapshot': {'account_mode':'demo'},
}

# Fix typo key, and tool aliases not in registry are handled separately.
local_args['think_about_problem']=local_args.pop(' think_about_problem')

# Create/cancel temporary scheduled task first so no long-running timer remains.
# Execute tools through the actual public dispatch surface.
for name, args in list(local_args.items()):
    if name not in GLOBAL_TOOL_REGISTRY.list():
        continue
    if name=='open_browser_and_search':
        run(name, lambda n=name,a=args: tools.execute_tool(n,a,timeout=4), 'dispatch-local')
    elif name=='create_and_execute_skill' or name=='think_about_problem':
        with patch('brain.llm_interface.query_llm',return_value='validationPASS'):
            run(name, lambda n=name,a=args: tools.execute_tool(n,a,timeout=6), 'dispatch-llm-mocked')
    elif name=='media.play_media':
        with patch('skills.media.playback.subprocess.Popen'):
            run(name, lambda n=name,a=args: tools.execute_tool(n,a,timeout=4), 'dispatch-process-mocked')
    else:
        run(name, lambda n=name,a=args: tools.execute_tool(n,a,timeout=6), 'dispatch-real-or-local')

# Explicit file mutation surface in a temp directory.
for name,args in [
 ('manage_files',{'action':'create','path':str(root/'created.txt'),'content':'created'}),
 ('manage_files',{'action':'read','path':str(root/'created.txt')}),
 ('manage_files',{'action':'copy','path':str(root/'created.txt'),'new_path':str(root/'copy.txt')}),
 ('manage_files',{'action':'move','path':str(root/'copy.txt'),'new_path':str(root/'moved.txt')}),
 ('manage_files',{'action':'mkdir','path':str(root/'dir')}),
 ('manage_files',{'action':'list','path':str(root)}),
 ('manage_files',{'action':'delete','path':str(root/'moved.txt')}),
 ('file.write_text',{'path':str(root/'doc.txt'),'content':'hello'}),
 ('file.write_word_document',{'path':str(root/'audit.docx'),'title':'Audit','content':'Audit body'}),
 ('save_text_pdf',{'text':'Audit PDF','output_path':str(root/'audit.pdf')}),
 ('file.convert_images_to_pdf',{'image_paths':[],'output_path':str(root/'empty.pdf')}),
 ('file.convert_word_to_pdf',{'input_path':str(root/'audit.docx'),'output_path':str(root/'audit-word.pdf')}),
 ('analyze_file',{'file_path':str(root/'hello.txt')}),
 ('analyze_directory',{'path':str(root),'recursive':False}),
]:
    if name in GLOBAL_TOOL_REGISTRY.list(): run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=8),'dispatch-file')

# Screen/camera/vision: actual functions under Xvfb where possible, camera with hardware mocked.
vision_safe={
'read_screen':{},'read_screen_region':{'x':0,'y':0,'width':120,'height':80},'find_on_screen':{'search_text':'Angelique'},
'capture_and_analyze':{},'capture_photo':{'save_path':str(root/'photo.jpg')},'analyze_camera':{},
'generate_image':{'prompt':'a tiny abstract test icon','style':'realistic','width':64,'height':64},
'analyze_image_with_local_model':{'image_path':str(root/'hello.txt'),'prompt':'describe'},
}
for name,args in vision_safe.items():
    if name not in GLOBAL_TOOL_REGISTRY.list(): continue
    if name in {'analyze_camera','capture_photo'}:
        # OpenCV capture is external hardware. Exercise dispatcher with camera failure safely.
        run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=4),'camera-guarded')
    elif name=='generate_image':
        run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=4),'provider-guarded')
    elif name=='analyze_image_with_local_model':
        with patch('skills.vision.ollama_vision._discover_ollama_models',return_value=[]):
            run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=4),'ollama-guarded')
    else: run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=8),'x11-local')

# External/financial/system tools are invoked through validation/guard paths or mocked providers.
external_cases=[
 ('send_whatsapp',{'contact_name':'Mukundane Jerome Agaba','message':'validation'}),
 ('send_whatsapp_direct',{'contact_name':'Mukundane Jerome Agaba','message':'validation'}),
 ('send_email_draft',{'to':'validation@example.com','subject':'Audit','body':'Audit'}),
 ('search_web',{'query':'flowers'}),
 ('download_file',{'url':'http://127.0.0.1:9/nope','output_path':str(root/'nope'),'timeout':0.5}),
 ('wifi.list_connected_devices',{'host':'127.0.0.1'}),
 ('wifi.list_disconnected_devices',{'host':'127.0.0.1'}),
 ('wifi.get_router_status',{'host':'127.0.0.1'}),
 ('wifi.login_router',{'host':'127.0.0.1','password':'validation'}),
 ('wifi.add_access_schedule',{'mac':'aa:bb:cc:dd:ee:ff','start_time':'00:00','end_time':'23:59','week_days':'1,2,3,4,5,6,7','host':'127.0.0.1'}),
 ('wifi.get_access_schedules',{'host':'127.0.0.1'}),
 ('wifi.disconnect_device',{'mac':'aa:bb:cc:dd:ee:ff','host':'127.0.0.1'}),
 ('wifi.allow_device_forever',{'mac':'aa:bb:cc:dd:ee:ff','host':'127.0.0.1'}),
 ('wifi.allow_device_for_duration',{'mac':'aa:bb:cc:dd:ee:ff','minutes':1,'host':'127.0.0.1'}),
 ('wifi.remove_access_schedule',{'mac':'aa:bb:cc:dd:ee:ff','host':'127.0.0.1'}),
]
for name,args in external_cases:
    if name not in GLOBAL_TOOL_REGISTRY.list(): continue
    if name.startswith('wifi.'):
        import skills.wifi_control.router_client as wr
        with patch.object(wr,'_ensure_router_session',return_value=None), patch.object(wr,'request_router_command',return_value={'LD':'challenge','AclMode':'2','WhiteMacList':'','WhiteNameList':'','BlackMacList':'','BlackNameList':'','result':'success'}), patch.object(wr,'_write_router_command',return_value={'result':'success'}), patch.object(wr,'add_access_schedule',return_value={'result':'success'}), patch.object(wr,'remove_access_schedule',return_value={'result':'success'}), patch.object(wr,'set_access_control_list',return_value={'result':'success'}):
            run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=5),'router-mocked')
    elif name.startswith('send_whatsapp'):
        import skills.messaging.whatsapp_tools as ww
        with patch.object(ww,'_send_via_meta',return_value={'success':True,'status':'mocked'}), patch.object(ww,'_send_via_http_gateway',return_value={'success':True,'status':'mocked'}):
            run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=5),'whatsapp-provider-mocked')
    elif name=='send_email_draft':
        run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=5),'draft-local')
    else:
        run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=5),'external-guarded')

# Trading tools with disabled/guarded account and mocked market path.
trade_cases=[
 ('analyze_market_and_recommend',{'symbol':'EURUSD','account_mode':'demo','risk_percent':0.5,'profile':'DAY_TRADING'}),
 ('execute_approved_trade',{'confirmation_phrase':'INVALID'}),
 ('get_forex_news',{'symbol':'EURUSD'}),
 ('get_market_calendar',{}),
]
for name,args in trade_cases:
    if name not in GLOBAL_TOOL_REGISTRY.list(): continue
    if name=='get_forex_news':
        import skills.trading.news as tn
        with patch.object(tn,'_safe_fetch',return_value='<html><h3>EURUSD validation</h3></html>'):
            run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=5),'news-mocked')
    elif name=='get_market_calendar':
        import skills.trading.news as tn
        with patch.object(tn,'_safe_fetch',return_value='<html>calendar</html>'):
            run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=5),'news-mocked')
    else:
        run(name,lambda n=name,a=args:tools.execute_tool(n,a,timeout=8),'trading-guarded')

# Confirm all registered tools have been invoked by name or explicitly registered but not safely runnable.
seen={r['tool'] for r in RESULTS}
for name in GLOBAL_TOOL_REGISTRY.list():
    if name not in seen:
        RESULTS.append({'tool':name,'status':'FAIL','mode':'not-invoked','detail':'Registered tool was not invoked by validator'})

print(json.dumps({'total':len(RESULTS),'passed':sum(r['status']=='PASS' for r in RESULTS),'failed':sum(r['status']=='FAIL' for r in RESULTS),'root':str(root),'results':RESULTS},indent=2))
# Don't let optional external provider absence turn the run into a false all-green result.
sys.exit(1 if any(r['status']=='FAIL' for r in RESULTS) else 0)
