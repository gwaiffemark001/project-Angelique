import json
import os
import re
import select
import shutil
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import config

run_cognitive_loop = None
listen = None
speak = None
sleep = None
is_awake = None
bridge_manager = None

BRIDGE_HOST = config.MT5_BRIDGE_HOST
BRIDGE_PORT = config.MT5_BRIDGE_PORT
RESERVED_MT5_BRIDGE_PORTS = [10001, 10002, 10003, 10004, 10005]
BRIDGE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills", "trading", "engine", "mt5_bridge_server.py")


def _import_runtime_modules():
    global run_cognitive_loop, listen, speak, sleep, is_awake, bridge_manager

    if run_cognitive_loop is None:
        try:
            from brain.cognitive_loop import run_cognitive_loop as _rc
            run_cognitive_loop = _rc
        except Exception as e:
            print(f"⚠️ [Main] Could not import cognitive_loop: {e}")

    if listen is None or speak is None:
        try:
            from skills.voice.voice_interface import listen as _listen, speak as _speak
            listen = _listen
            speak = _speak
        except Exception as e:
            print(f"⚠️ [Main] Voice interface unavailable: {e}")
            def _missing_listen(*args, **kwargs):
                return ""
            def _missing_speak(*args, **kwargs):
                print("⚠️ [Voice] speak unavailable.")
            listen = _missing_listen
            speak = _missing_speak

    if sleep is None or is_awake is None:
        try:
            from skills.voice.wake_word_system import sleep as _sleep, is_awake as _is_awake
            sleep = _sleep
            is_awake = _is_awake
        except Exception as e:
            print(f"⚠️ [Main] Wake-word system unavailable: {e}")
            def _missing_sleep(*args, **kwargs):
                pass
            def _missing_is_awake():
                return True
            sleep = _missing_sleep
            is_awake = _missing_is_awake

    if bridge_manager is None:
        try:
            from skills.trading.engine.connection_manager import bridge_manager as _bridge_manager
            bridge_manager = _bridge_manager
        except Exception as e:
            print(f"⚠️ [Main] MT5 bridge manager unavailable: {e}")
            class DummyBridge:
                def __init__(self):
                    self.host = None
                    self.port = None
                def start(self):
                    return False
                def get_status(self):
                    return False
                def ping(self):
                    return {"error": "bridge unavailable"}
                def connect(self):
                    return False
            bridge_manager = DummyBridge()


def get_wake_phrase() -> str:
    return get_intro_phrase()

def is_port_free(host: str, port: int, timeout: float = 0.1) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(timeout)
            sock.bind((host, port))
            return True
    except OSError:
        return False


def select_bridge_port() -> int | None:
    if BRIDGE_PORT:
        if is_port_free(BRIDGE_HOST, BRIDGE_PORT):
            return BRIDGE_PORT
        print(f"⚠️ [Bootstrap] Requested bridge port {BRIDGE_PORT} is already in use.")
        return None

    for port in RESERVED_MT5_BRIDGE_PORTS:
        if is_port_free(BRIDGE_HOST, port):
            return port

    return None


BRIDGE_PORT = select_bridge_port()

if BRIDGE_PORT is not None and bridge_manager is not None:
    os.environ["ANGELIQUE_MT5_BRIDGE_HOST"] = BRIDGE_HOST
    os.environ["ANGELIQUE_MT5_BRIDGE_PORT"] = str(BRIDGE_PORT)
    bridge_manager.host = BRIDGE_HOST
    bridge_manager.port = BRIDGE_PORT


def is_bridge_responsive(host: str, port: int, timeout: float | None = None) -> bool:
    timeout = timeout or config.MT5_BRIDGE_CONNECT_TIMEOUT
    try:
        import asyncio
        import websockets
    except ImportError:
        return False

    async def _ping():
        try:
            async with websockets.connect(f"ws://{host}:{port}", open_timeout=timeout) as ws:
                await ws.send(json.dumps({"action": "ping"}))
                response = await asyncio.wait_for(ws.recv(), timeout=timeout)
                return isinstance(response, str) and "pong" in response
        except Exception:
            return False

    try:
        return asyncio.run(_ping())
    except Exception:
        return False


def get_intro_phrase() -> str:
    return (
        "Angelique, my love, the voice of money, ambassador of the rich, brother from another mother, "
        "conquerer of the multiverse, wealth itself, born to conquer, the best of the best, mr money, "
        "I am here for you and ready to serve."
    )


def get_wake_phrase() -> str:
    return (
        "Angelique, the voice of money, ambassador of the rich, conquerer of the multiverse, "
        "born to conquer and the best of the best."
    )


def launch_mt5_bridge_if_needed() -> bool:
    if BRIDGE_PORT is None:
        print("❌ [Bootstrap] No free MT5 bridge port was available. Available ports are: " + ", ".join(str(p) for p in RESERVED_MT5_BRIDGE_PORTS))
        return False

    print(f"🔧 [Bootstrap] Using MT5 Bridge port {BRIDGE_PORT}")
    if is_bridge_responsive(BRIDGE_HOST, BRIDGE_PORT, timeout=1.0):
        print(f"🔌 [Bootstrap] MT5 Bridge already available on {BRIDGE_HOST}:{BRIDGE_PORT}")
        return True

    wine_path = shutil.which("wine")
    if wine_path is None:
        if os.path.exists(BRIDGE_SCRIPT):
            try:
                print("⚠️ [Bootstrap] Wine not found — launching bridge with local Python as fallback.")
                bridge_env = os.environ.copy()
                bridge_env["ANGELIQUE_MT5_BRIDGE_HOST"] = BRIDGE_HOST
                bridge_env["ANGELIQUE_MT5_BRIDGE_PORT"] = str(BRIDGE_PORT)
                subprocess.Popen(
                    [sys.executable, BRIDGE_SCRIPT],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=bridge_env,
                    start_new_session=True,
                )
            except Exception as exc:
                print(f"❌ [Bootstrap] Failed to launch MT5 Bridge with local Python: {exc}")
                return False
        else:
            print(f"⚠️ [Bootstrap] Bridge script not found: {BRIDGE_SCRIPT}")
            return False
    else:
        if not os.path.exists(BRIDGE_SCRIPT):
            print(f"⚠️ [Bootstrap] Bridge script not found: {BRIDGE_SCRIPT}")
            return False
        print("🍷 [Bootstrap] Launching MT5 Bridge Server inside Wine...")
        bridge_env = os.environ.copy()
        bridge_env["ANGELIQUE_MT5_BRIDGE_HOST"] = BRIDGE_HOST
        bridge_env["ANGELIQUE_MT5_BRIDGE_PORT"] = str(BRIDGE_PORT)
        try:
            subprocess.Popen(
                [wine_path, "python", BRIDGE_SCRIPT],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=bridge_env,
                start_new_session=True,
            )
        except Exception as exc:
            print(f"❌ [Bootstrap] Failed to launch MT5 Bridge: {exc}")
            return False

    print(f"⏳ [Bootstrap] Waiting for MT5 Bridge to initialize on port {BRIDGE_PORT}...")
    deadline = time.time() + config.MT5_BRIDGE_CONNECT_TIMEOUT
    
    while time.time() < deadline:
        if is_bridge_responsive(BRIDGE_HOST, BRIDGE_PORT, timeout=config.MT5_BRIDGE_CONNECT_TIMEOUT):
            print("✅ [Bootstrap] MT5 Bridge has started.")
            return True
        print(f"⏳ [Bootstrap] MT5 Bridge not responsive yet on {BRIDGE_HOST}:{BRIDGE_PORT}; retrying...")
        time.sleep(config.MT5_BRIDGE_RECONNECT_INTERVAL)
        
    print(f"⚠️ [Bootstrap] MT5 Bridge did not start in time on {BRIDGE_HOST}:{BRIDGE_PORT}.")
    print("    If this port is already used by another app, set ANGELIQUE_MT5_BRIDGE_PORT to a free port and restart.")
    return False

def speak_intro_phrase() -> None:
    segments = [
        "The Big Dog. ", "Head of the table. ", "Voice of the voiceless. ",
        "Ambassador of the rich. ", "Brother from another mother. ",
        "Conquerer of the multiverse. ", "Voice of the money. ",
        "Wealth itself. ", "Born to conquer. ", "The best of the best. ",
        "Mr money. ", "I am here for you and ready to serve. ",
    ]
    for segment in segments:
        speak(segment)
        time.sleep(0.01)

def normalize_voice_command(text: str) -> str:
    if not text: return ""
    cleaned = text.strip()
    if "angelique" in cleaned.lower():
        cleaned = re.sub(r"\bangelique\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^[\s,;.:-]+|[\s,;.:-]+$", "", cleaned)
    return cleaned

def get_mode_toggle_action(user_text: str, audio_enabled: bool) -> str | None:
    text = user_text.strip().lower()
    if not text: return None
    text_commands = {"type", "text", "i want to type", "switch to text", "switch back to text", "back to text", "text mode", "typing"}
    voice_commands = {"voice", "switch to voice", "switch back to voice", "back to voice", "audio", "speak", "talk"}
    if audio_enabled:
        if text in text_commands: return "disable"
        if text in voice_commands: return "enable"
    else:
        if text in voice_commands: return "enable"
        if text in text_commands: return "disable"
    return None

def main():
    _import_runtime_modules()
    if BRIDGE_PORT is not None:
        os.environ["ANGELIQUE_MT5_BRIDGE_HOST"] = BRIDGE_HOST
        os.environ["ANGELIQUE_MT5_BRIDGE_PORT"] = str(BRIDGE_PORT)
        if hasattr(bridge_manager, "host"):
            bridge_manager.host = BRIDGE_HOST
        if hasattr(bridge_manager, "port"):
            bridge_manager.port = BRIDGE_PORT

    print("🚀 [Bootstrap] Starting Angelique Environment...")
    launch_mt5_bridge_if_needed()
    
    if bridge_manager is not None:
        print("🔗 [System] Initializing MT5 Trading Engine...")
        bridge_manager.start()
        time.sleep(1.5)
        if bridge_manager.get_status():
            print("✅ [System] MT5 Bridge Connected Successfully.")
        else:
            print("⚠️ [System] MT5 Bridge is starting in the background. Will auto-reconnect.")
    else:
        print("⚠️ [System] Trading bridge unavailable; continuing without MT5 integration.")
    print("=" * 50)
    
    # Initialize wake-word system (START IN SLEEP MODE)
    print("😴 [System] Angelique wake-word system initialized. Angelique is sleeping.")
    print("   Say 'Angelique' followed by a clap to wake her up.")
    sleep()  # Start in sleep mode for safety

    audio_enabled = True
    has_started = False
    last_speech_time = 0.0
    has_had_conversation = False

    print("🟢 Angelique v1 - Cognitive Architecture Online")
    print(" Audio is ON by default. Press Enter to toggle audio on/off.")
    print("Type 'exit' or say 'goodbye' to quit.\n")

    while True:
        user_input = ""
        try:
            if audio_enabled and not has_started and not has_had_conversation:
                speak_intro_phrase()
                has_started = True

            if audio_enabled:
                print("🎤 Listening... (press Enter to toggle audio)", end="\r")
                result: list[str | None] = [None]
                def listen_thread():
                    result[0] = listen()
                t = threading.Thread(target=listen_thread, daemon=True)
                t.start()
                while t.is_alive():
                    t.join(timeout=0.1)
                    if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                        pressed = input().strip()
                        if pressed == "":
                            audio_enabled = False
                            print("\n🔈 Audio disabled. Press Enter again to re-enable audio.")
                        else:
                            user_input = pressed
                        break
                if not user_input and result[0]:
                    user_input = normalize_voice_command(result[0].strip())
                    if user_input:
                        print(f"\n🗣️ You: {user_input}")
            else:
                print("\n Text mode active. Type your message, or press Enter to re-enable audio.")
                try:
                    pressed = input("💬 You: ").strip()
                except EOFError:
                    break
                if pressed == "":
                    audio_enabled = True
                    print("\n🔈 Audio enabled again.")
                    continue
                user_input = pressed

            if user_input:
                action = get_mode_toggle_action(user_input, audio_enabled)
                if action == "disable":
                    audio_enabled = False
                    print("\n🔈 Audio disabled.")
                    continue
                if action == "enable":
                    audio_enabled = True
                    print("\n🔈 Audio enabled again.")
                    continue

            if not user_input:
                continue

        except (EOFError, KeyboardInterrupt):
            break

        lower_input = user_input.lower()
        if lower_input in ["exit", "quit", "goodbye", "shut down", "stop"]:
            print("\n👋 Shutting down...")
            speak("Alright, I'm shutting down now. Talk to you later!")
            break

        has_had_conversation = True
        print("\n🧠 Thinking...")
        response = run_cognitive_loop(user_input)
        print(f"\n✨ Angelique: {response}\n")
        if audio_enabled:
            now = time.time()
            if now - last_speech_time > 0.8:
                speak(response)
                last_speech_time = now

if __name__ == "__main__":
    if os.environ.get("ANGELIQUE_LAUNCHED") == "1":
        main()
    else:
        print("Please start Angelique via launcher.py. Run: python3 launcher.py")
