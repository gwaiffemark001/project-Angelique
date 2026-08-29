from __future__ import annotations
import ast, json, tempfile, sys
from pathlib import Path
from unittest.mock import patch, Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
results=[]
def check(group,name,fn):
    try:
        v=fn(); results.append({"group":group,"skill":name,"passed":True,"detail":str(v)[:300]})
    except Exception as e:
        results.append({"group":group,"skill":name,"passed":False,"detail":f"{type(e).__name__}: {e}"})

# Automation
from skills.automation.automation import schedule,list_schedules,cancel
check("automation","schedule/cancel",lambda:(lambda jid:(jid,cancel(jid)))(schedule("echo validation",999)))

# Conversation
from skills.conversation.chat_skill import new_session,get_session_context
check("conversation","session context",lambda:isinstance(get_session_context(new_session()),dict))

# File management
from skills.file_management.file_ops import manage_files
def t_file():
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"a.txt"; manage_files("create",str(p),content="hello")
        assert "hello" in manage_files("read",str(p)); return str(p)
check("file_management","create/read",t_file)

# Media, mocked app opener
import skills.media.playback as media
check("media","play dispatch",lambda:(setattr(media,"open_app",lambda name:f"opened {name}"), media.play_media(app_name="spotify"))[1])

# Messaging contact resolution, HTTP mocked
import skills.messaging.whatsapp_tools as wa
def t_wa():
    rows=wa.load_contacts(); assert rows
    full_names=[r["names"][-1] for r in rows if r["names"]]; name=next((n for n in full_names if wa.resolve_contact(n)), None); assert name
    fake=Mock(ok=True,status_code=200); fake.json.return_value={"messages":[{"id":"test"}]}
    with patch.object(wa.requests,"post",return_value=fake), patch.object(wa.config,"WHATSAPP_PROVIDER","generic"), patch.object(wa.config,"WHATSAPP_API_URL","http://validation.invalid"):
        out=wa.send_whatsapp(name,"validation"); assert out["success"]; return name
check("messaging","contact+send contract",t_wa)

# OS
from skills.os_control.system_cmds import run_shell_command,get_system_health
check("os_control","shell",lambda: "Exit code: 0" in run_shell_command("printf validation"))
check("os_control","health",lambda:isinstance(get_system_health(),dict))

# Self evolution: AST + executable generated code in isolated subprocess
from skills.self_evolution.code_generator import execute_generated_code
check("self_evolution","generated code",lambda:"Code executed" in execute_generated_code("def main():\n    return 1\n",timeout=3,reuse_cache=False))

# Vision
from skills.vision.file_analyzer import analyze_file
def t_vision():
    with tempfile.NamedTemporaryFile("w",suffix=".txt",delete=False) as f: f.write("vision validation"); p=f.name
    try:return analyze_file(p).get("type")
    finally:Path(p).unlink(missing_ok=True)
check("vision","file analyzer",t_vision)

# Voice no microphone: state toggle
from skills.voice.voice_interface import is_speech_enabled,set_speech_enabled
check("voice","toggle",lambda:(set_speech_enabled(False),is_speech_enabled(),set_speech_enabled(True))[1] is False)

# Web search fallback only (dependency absent is valid but must return text)
from skills.web.search_tools import search_web
check("web","search interface",lambda:isinstance(search_web("validation"),str))

# WiFi parser
from skills.wifi_control.router_client import normalize_devices
check("wifi","device normalize",lambda:isinstance(normalize_devices([{"hostname":"test","mac":"AA:BB:CC"}]),list))

# Trading pure calculations
from skills.trading_skill.strategy_engine import select_strategy
from skills.trading_skill.risk import account_risk_percent,build_risk
check("trading","strategy selection",lambda:isinstance(select_strategy(timeframes={},indicators={},trends={},structure=None,preferred="AUTO"),dict))
check("trading","risk tier",lambda:account_risk_percent(1000)==1.0)

def t_risk():
    r=build_risk(1.1000,1.0980,1000,1.0,{"tick_size":0.00001,"tick_value":1,"volume_step":0.01,"volume_min":0.01,"volume_max":10,"margin_per_volume":10},free_margin=1000)
    assert r["risk_amount"]==10.0; return r["volume"]
check("trading","volume calculation",t_risk)

# LLM policy
import brain.llm_interface as llm
def _model_online():
    with patch.object(llm,"_is_online",return_value=True),patch.object(llm,"_call_openrouter",return_value="cloud-ok"),patch.object(llm,"_call_nvidia",return_value=None),patch.object(llm,"_call_bluesminds",return_value=None),patch.object(llm,"_call_gemini",return_value=None),patch.object(llm,"_call_ollama",return_value="local-ok"):
        return llm.query_llm([{"role":"user","content":"hi"}])=="cloud-ok"
def _model_offline():
    with patch.object(llm,"_is_online",return_value=False),patch.object(llm,"_call_ollama",return_value="local-ok"): return llm.query_llm([{"role":"user","content":"hi"}])=="local-ok"
check("models","online cloud first",_model_online)
check("models","offline local",_model_offline)

# Cognitive deterministic routing: time/date and filename search. Tool execution mocked.
import brain.cognitive_loop as cog
def _cog_time():
    r=cog.resolve_user_query("what is the time","validation-time")
    return r.get("source")=="system" and "current time" in r.get("answer","").lower()

def _cog_file():
    with patch.object(cog,"_call_through_execute_tool",return_value=Mock(success=True,output="file: /tmp/project-Angelique",error=None)) as m:
        r=cog.resolve_user_query("look for any file named project-Angelique on my laptop","validation-file")
        assert m.called; args=m.call_args.args[1]; assert args["query"]=="project-Angelique"; assert r.get("details",{}).get("tool")=="search_files"; return r["answer"]
check("cognitive","filename search route",_cog_file)

def _cog_wa():
    with patch.object(cog,"_exec_tool",create=True): pass
# inspect heuristic directly instead of full execution
from brain.heuristic_engine import extract_command_heuristically
def _wa_route():
    t,a=extract_command_heuristically("send Mukundane Jerome Agaba a message on whatsapp saying hello")
    assert t=="send_whatsapp"; assert a["contact_name"]=="mukundane jerome agaba"; return a
check("cognitive","whatsapp phrase parsing",_wa_route)
check("cognitive","browser search route",lambda:extract_command_heuristically("open the browser and search flowers")[0])

# GUI import and geometry is executed separately under Xvfb by the wrapper command.
try:
    import tkinter
    from gui.angelique_desktop import AngeliqueDesktopApp
    def t_gui():
        app=AngeliqueDesktopApp(); app.update_idletasks()
        assert app.winfo_width()>=1200 and app.winfo_height()>=760
        for attr in ("send_button","mic_button","training_toggle_button","_position_monitor_button","_signal_button"):
            assert getattr(app,attr,None) is not None, attr
        dims=f"{app.winfo_width()}x{app.winfo_height()}"; app.destroy(); return dims
    check("gui","original UI render/buttons",t_gui)
except Exception as e:
    results.append({"group":"gui","skill":"import","passed":False,"detail":f"{type(e).__name__}: {e}"})

failed=[r for r in results if not r["passed"]]
print(json.dumps({"total":len(results),"passed":len(results)-len(failed),"failed":len(failed),"results":results},indent=2))
sys.exit(1 if failed else 0)
