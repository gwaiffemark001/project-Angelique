from __future__ import annotations
import argparse, os, sys, tempfile, types
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import core.tools as tools
from core.tools_adapter import migrate_registry
from core.tool_registry import GLOBAL_TOOL_REGISTRY
migrate_registry()

parser=argparse.ArgumentParser(); parser.add_argument('name'); args=parser.parse_args(); name=args.name
root=Path(tempfile.mkdtemp(prefix='angelique-one-'))
(root/'hello.txt').write_text('Angelique project-Angelique audit\n',encoding='utf-8')
try:
    from PIL import Image
    Image.new('RGB',(64,64),'white').save(root/'img.png')
except Exception: pass

A={
'open_app':dict(app_name='__not_a_real_app__'),'close_app':dict(app_name_or_pid='99999999'),'list_apps':{},'check_installation_status':dict(target_name='python3'),
'run_shell_command':dict(command='printf Angelique_AUDIT'),'get_system_health':{},'get_running_processes':dict(limit=1),'kill_process':dict(pid_or_name='99999999'),
'manage_files':dict(action='create',path=str(root/'created.txt'),content='audit'), 'list_directory':dict(path=str(root),recursive=False),
'cli_ls':dict(path=str(root)),'cli_open':dict(file_path=str(root/'hello.txt'),lines=3),'cli_cat':dict(file_path=str(root/'hello.txt'),max_size=1000),
'search_files':dict(query='project-Angelique',root=str(root),max_results=10,max_depth=4),'disk_usage':dict(path=str(root)),
'save_memory':dict(person='Audit',key='test',value='ok'),'recall_memory':dict(query='test'),'remember':dict(key='test',value='ok',importance=5),'recall_conversation':dict(query='test'),
'summarize_context':{},'start_new_session':{},'read_screen':{},'read_screen_region':dict(x=0,y=0,width=80,height=60),'find_on_screen':dict(search_text='Angelique'),'capture_and_analyze':{},
'analyze_camera':{},'capture_photo':dict(save_path=str(root/'photo.jpg')),
'generate_image':dict(prompt='audit icon',style='realistic',width=64,height=64),'analyze_file':dict(file_path=str(root/'hello.txt')),'analyze_directory':dict(path=str(root),recursive=False),
'create_and_execute_skill':dict(instruction='return AUDIT_OK'),'execute_generated_code':dict(code='def main():\n    return "AUDIT_OK"',function_name='main',kwargs={}),
'save_new_skill':dict(skill_name='audit_registered_tool_skill',code='def main():\n    return "AUDIT_OK"'),'think_about_problem':dict(problem='Produce a test plan.'),
'store_component':dict(name='audit_component',code='def x(): return "ok"'),'retrieve_component':dict(name_query='audit_component'),'get_evolution_log':{},
'get_network_info':{},'get_network_interfaces':{},'adapter.jarvis.time':{},'adapter.jarvis.date':{},'adapter.jarvis.system_info':{},
'adapter.jarviscli.list_plugins':{},'adapter.jarviscli.call':dict(plugin_name='__missing__',text='audit'),'adapter.calendar.list':{},'adapter.calendar.get_events':dict(calendar_path=str(root/'missing.ics')),
'adapter.calendar.add_event':dict(title='Audit Event',start_iso='2026-08-29T12:00',end_iso='2026-08-29T12:30',description='audit'), 'adapter.calendar.remove_event':dict(event_id='missing'),
'adapter.img.imgtopdf':dict(image_paths=[str(root/'img.png')],output_path=str(root/'img.pdf')),'adapter.screen.capture_to_pdf':dict(output_path=str(root/'screen.pdf'),region=None),
'get_logs':dict(log_file=str(root/'missing.log'),lines=5),'search_web':dict(query='flowers'),'open_browser_and_search':dict(query='flowers'),
'save_text_pdf':dict(path=str(root/'text.pdf'),text='audit',content='audit',title='Audit'),'send_whatsapp':dict(contact_name='Mukundane Jerome',message='audit'),
'check_messaging_status':{},'send_email_draft':dict(to='audit@example.com',subject='Audit',body='audit'),'media.play_media':dict(app_name='__missing__',service='youtube',query='flowers'),
'file.write_text':dict(file_path=str(root/'write.txt'),content='audit',mode='w'),'file.write_word_document':dict(file_path=str(root/'doc.docx'),content='audit'),
'file.convert_images_to_pdf':dict(image_paths=[str(root/'img.png')],output_path=str(root/'img2.pdf')),'file.convert_word_to_pdf':dict(docx_path=str(root/'doc.docx'),pdf_path=str(root/'word.pdf')),
'voice.speak':dict(text='audit'),'voice.listen':{},'voice.set_enabled':dict(enabled=False),'voice.wake_up':{},'voice.sleep':{},'voice.is_awake':{},'voice.activation_protocol':dict(audio_text='',audio_samples=[]),
'automation.schedule':dict(command='printf audit',delay_seconds=3600,repeat_seconds=None),'automation.cancel':dict(job_id='missing'),'automation.list':{},
'conversation.new_session':{},'conversation.history':dict(session_id='default',limit=5),'conversation.context':dict(session_id='default'),'memory.entities':{},'memory.friends':{},'vision.camera':{},'vision.capture_photo':dict(save_path=str(root/'vphoto.jpg')),'voice.clap_available':{},
'call_skill':dict(skill_name='get_system_health',args={}),
'wifi.list_connected_devices':dict(host='127.0.0.1'),'wifi.list_disconnected_devices':dict(host='127.0.0.1'),'wifi.get_router_status':dict(host='127.0.0.1'),'wifi.login_router':dict(host='127.0.0.1',password='audit'),
'wifi.add_access_schedule':dict(mac='00:11:22:33:44:55',start='00:00',end='23:59',day_mask=0,host='127.0.0.1'),'wifi.get_access_schedules':dict(mac='00:11:22:33:44:55',host='127.0.0.1'),
'wifi.disconnect_device':dict(mac='00:11:22:33:44:55',name='audit',host='127.0.0.1'),'wifi.allow_device_forever':dict(mac='00:11:22:33:44:55',host='127.0.0.1'),
'wifi.allow_device_for_duration':dict(mac='00:11:22:33:44:55',minutes=1,host='127.0.0.1'),'wifi.remove_access_schedule':dict(mac='00:11:22:33:44:55',host='127.0.0.1'),
'system_monitor.get_system_health':{},'check_mt5_status':{},'get_account_balance':{},'analyze_market_and_recommend':dict(symbol='EURUSD',timeframe='M15',risk_percent=.5),
'execute_approved_trade':dict(confirmation_phrase='INVALID'),'trading_hub_health':dict(account_mode='demo',symbol='EURUSD',trading_mode='DAY_TRADING'),
'get_forex_news':dict(symbol='EURUSD'),'get_market_calendar':{},
'mouse_move':dict(x=1,y=1),'mouse_click':dict(x=1,y=1,button='left',clicks=1),'type_text':dict(text='audit',interval=0),'hotkey':dict(keys='ctrl+l'),'key_press':dict(key='esc'),
'clipboard_get':{},'clipboard_set':dict(text='audit'),'active_window':{},'schedule_task':dict(command='printf audit',delay_seconds=3600,repeat_seconds=None),'cancel_scheduled_task':dict(job_id='missing'),'list_scheduled_tasks':{},
'analyze_image_with_local_model':dict(image_path=str(root/'img.png'),prompt='describe'),'download_file':dict(url='http://127.0.0.1:9/missing',output_path=str(root/'missing'),timeout=.3),'send_whatsapp_direct':dict(contact_name='Mukundane Jerome',message='audit')
}
if name not in GLOBAL_TOOL_REGISTRY.list():
    raise RuntimeError('not registered')
kwargs=A.get(name,{})

# External/hardware providers are replaced only at their edge. The actual skill/adapter
# function and gateway are still invoked.
patchers=[]
import webbrowser
patchers += [patch.object(webbrowser,'open',return_value=True)]
try:
 import skills.messaging.whatsapp_tools as ww
 class R:
  ok=True; status_code=200; text='{}'
  def json(self): return {'messages':[{'id':'audit'}]}
 patchers += [patch.object(ww.requests,'post',return_value=R())]
except Exception: pass
try:
 import skills.media.playback as mp
 patchers += [patch.object(mp.subprocess,'Popen',return_value=Mock())]
except Exception: pass
try:
 import skills.wifi_control.router_client as wr
 class Resp:
  headers={'Set-Cookie':'audit=1;'}
  def read(self,*a): return b'{"result":"0"}'
  def __enter__(self): return self
  def __exit__(self,*a): return False
 patchers += [patch.object(wr,'urlopen',return_value=Resp()),patch.object(wr,'request_router_command',return_value={'LD':'challenge','AclMode':'2','WhiteMacList':'','WhiteNameList':'','BlackMacList':'','BlackNameList':'','result':'success'}),patch.object(wr,'_write_router_command',return_value={'result':'success'}),patch.object(wr,'_ensure_router_session',return_value=None),patch.object(wr,'add_access_schedule',return_value={'result':'success'}),patch.object(wr,'remove_access_schedule',return_value={'result':'success'}),patch.object(wr,'set_access_control_list',return_value={'result':'success'})]
except Exception: pass
try:
 import skills.os_control.desktop_control as dc
 patchers += [patch.object(dc,'subprocess',Mock(run=lambda *a,**k:Mock(stdout='audit\n',stderr='',returncode=0)),create=True)]
except Exception: pass
# avoid real camera, webcam and local vision downloads
try:
 import skills.vision.camera_tools as cam
 class Cap:
  def isOpened(self): return False
 patchers += [patch.object(cam.cv2,'VideoCapture',return_value=Cap())]
except Exception: pass
try:
 import skills.vision.image_generator as ig
 patchers += [patch.object(ig,'generate_image',return_value='AUDIT_IMAGE_OK')]
except Exception: pass
try:
 import skills.vision.ollama_vision as ov
 patchers += [patch.object(ov,'_discover_ollama_models',return_value=[])]
except Exception: pass
# LLM-dependent skill calls get a deterministic response so they do not consult real providers.
patchers += [patch('brain.llm_interface.query_llm',return_value='AUDIT_OK')]
# Trading network edges are explicitly patched when invoking the general dispatcher; the deep
# trading suites separately exercise calculation/bridge semantics.
try:
 import skills.trading_skill.service as tsvc
 patchers += [patch.object(tsvc,'get_account_snapshot',return_value={'snapshot':types.SimpleNamespace(connected=False,login=None,equity=1000)}),patch.object(tsvc,'enforce_loss_limits',return_value={'triggered':False})]
except Exception: pass

with patch.object(__import__('skills.automation.automation',fromlist=['automation']),'time',create=True):
    pass
from contextlib import ExitStack
with ExitStack() as stack:
    for p in patchers:
        try: stack.enter_context(p)
        except Exception: pass
    # For generate_image, use the real registry executor but provider output is stubbed at module edge.
    out=tools.execute_tool(name,kwargs,session_id='tool-audit',user_request='registered tool audit',timeout=4)
print('RESULT',repr(out)[:1000])
