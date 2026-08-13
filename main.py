import json
import os
import re
import select
import shlex
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
RESERVED_MT5_BRIDGE_PORTS = config.MT5_BRIDGE_RESERVED_PORTS
BRIDGE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills", "trading_skill", "wine_server.py")


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


def _find_responsive_bridge_port() -> int | None:
    for port in RESERVED_MT5_BRIDGE_PORTS:
        if is_bridge_responsive(BRIDGE_HOST, port, timeout=1.0):
            return port
    return None


def select_bridge_port() -> int | None:
    if BRIDGE_PORT:
        if is_port_free(BRIDGE_HOST, BRIDGE_PORT):
            return BRIDGE_PORT

        if is_bridge_responsive(BRIDGE_HOST, BRIDGE_PORT, timeout=1.0):
            print(f"🔌 [Bootstrap] MT5 Bridge already available on {BRIDGE_HOST}:{BRIDGE_PORT}")
            return BRIDGE_PORT

        other_port = _find_responsive_bridge_port()
        if other_port is not None:
            print(f"⚠️ [Bootstrap] Requested bridge port {BRIDGE_PORT} is already in use; using existing bridge on {BRIDGE_HOST}:{other_port}")
            return other_port

        # Only allow reserved fallback ports, no additional port scanning.
        for port in RESERVED_MT5_BRIDGE_PORTS:
            if port != BRIDGE_PORT and is_port_free(BRIDGE_HOST, port):
                print(f"⚠️ [Bootstrap] Requested bridge port {BRIDGE_PORT} is already in use; falling back to {port}")
                return port

        print(f"⚠️ [Bootstrap] Requested bridge port {BRIDGE_PORT} is already in use and no reserved port is free.")
        return None

    responsive_port = _find_responsive_bridge_port()
    if responsive_port is not None:
        print(f"🔌 [Bootstrap] MT5 Bridge already available on {BRIDGE_HOST}:{responsive_port}")
        return responsive_port

    for port in RESERVED_MT5_BRIDGE_PORTS:
        if is_port_free(BRIDGE_HOST, port):
            return port

    return None


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


BRIDGE_PORT = select_bridge_port()

if BRIDGE_PORT is not None and bridge_manager is not None:
    os.environ[config.MT5_BRIDGE_HOST_ENV] = BRIDGE_HOST
    os.environ[config.MT5_BRIDGE_PORT_ENV] = str(BRIDGE_PORT)
    bridge_manager.host = BRIDGE_HOST
    bridge_manager.port = BRIDGE_PORT


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


def _to_windows_path(path: str) -> str:
    if shutil.which("winepath") is None:
        return path
    try:
        completed = subprocess.run(
            ["winepath", "-w", path],
            capture_output=True,
            text=True,
            check=True,
        )
        converted = completed.stdout.strip()
        return converted or path
    except Exception:
        return path


def _get_bridge_launch_command() -> list[str]:
    launcher = str(getattr(config, "MT5_BRIDGE_LAUNCHER", "wine cmd /c python")).strip()
    candidates = [launcher] if launcher else []
    candidates.extend([
        "wine64 cmd /c python",
        "wine cmd /c python",
        "wine64 python",
        "wine python",
        "wine64 cmd /c python.exe",
        "wine cmd /c python.exe",
    ])

    seen = set()
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parts = shlex.split(candidate)
        except ValueError:
            continue
        if not parts:
            continue
        if shutil.which(parts[0]) is None:
            continue
        executable = parts[0]
        if executable.startswith("wine"):
            script_path = _to_windows_path(BRIDGE_SCRIPT)
        else:
            script_path = BRIDGE_SCRIPT
        print(f"🔧 [Bootstrap] Selected MT5 bridge launcher: {' '.join(parts)}")
        return parts + [script_path]

    raise RuntimeError(
        "MT5 bridge launcher command is not configured or available. "
        "Install wine/wine64 or set ANGELIQUE_MT5_BRIDGE_LAUNCHER to a valid command."
    )


def _launch_bridge_process(bridge_env: dict[str, str], cmd: list[str], pass_fds=()):
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=bridge_env,
        start_new_session=True,
        pass_fds=pass_fds,
    )


def _reserve_bridge_port(host: str, port: int):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(5)
    sock.setblocking(False)
    return sock


def launch_mt5_bridge_if_needed() -> bool:
    if BRIDGE_PORT is None:
        print("❌ [Bootstrap] No free MT5 bridge port was available. Available ports are: " + ", ".join(str(p) for p in RESERVED_MT5_BRIDGE_PORTS))
        return False

    print(f"🔧 [Bootstrap] Using MT5 Bridge port {BRIDGE_PORT}")
    if is_bridge_responsive(BRIDGE_HOST, BRIDGE_PORT, timeout=1.0):
        print(f"🔌 [Bootstrap] MT5 Bridge already available on {BRIDGE_HOST}:{BRIDGE_PORT}")
        return True

    if not os.path.exists(BRIDGE_SCRIPT):
        print(f"⚠️ [Bootstrap] Bridge script not found: {BRIDGE_SCRIPT}")
        return False

    print("🔧 [Bootstrap] Launching MT5 Bridge Server under Wine...")
    bridge_env = os.environ.copy()
    bridge_env[config.MT5_BRIDGE_HOST_ENV] = BRIDGE_HOST
    bridge_env[config.MT5_BRIDGE_PORT_ENV] = str(BRIDGE_PORT)
    bridge_env[config.MT5_BRIDGE_FD_ENV] = ""
    cmd = _get_bridge_launch_command()
    if cmd[0].startswith("wine"):
        bridge_env["PYTHONPATH"] = _to_windows_path(os.path.dirname(os.path.abspath(__file__)))
    else:
        bridge_env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))
    bridge_socket = None
    try:
        if cmd[0].startswith("wine"):
            bridge_env[config.MT5_BRIDGE_FD_ENV] = ""
            bridge_process = _launch_bridge_process(bridge_env, cmd=cmd)
        else:
            bridge_socket = _reserve_bridge_port(BRIDGE_HOST, BRIDGE_PORT)
            bridge_env[config.MT5_BRIDGE_FD_ENV] = str(bridge_socket.fileno())
            bridge_process = _launch_bridge_process(bridge_env, cmd=cmd, pass_fds=(bridge_socket.fileno(),))
    except Exception as exc:
        if bridge_socket is not None:
            try:
                bridge_socket.close()
            except Exception:
                pass
        print(f"❌ [Bootstrap] Failed to launch MT5 Bridge: {exc}")
        return False
    finally:
        if bridge_socket is not None:
            try:
                bridge_socket.close()
            except Exception:
                pass

    time.sleep(0.5)
    if bridge_process.poll() is not None:
        output = bridge_process.stdout.read().strip() if bridge_process.stdout else ""
        if output:
            print(output)
        print(f"❌ [Bootstrap] MT5 Bridge exited immediately with code {bridge_process.returncode}.")
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
    if bridge_process.stdout is not None:
        try:
            bridge_output = bridge_process.stdout.read().strip()
            if bridge_output:
                print("--- MT5 Bridge stdout/stderr ---")
                print(bridge_output)
        except Exception:
            pass
    print(f"    If this port is already used by another app, set {config.MT5_BRIDGE_PORT_ENV} to a free port and restart.")
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
    # Acquire single-session lock for terminal mode
    try:
        from core.session_lock import acquire_lock, release_lock, read_lock
    except Exception:
        acquire_lock = None
        release_lock = None
        read_lock = None

    if acquire_lock:
        ok = acquire_lock("terminal")
        if not ok:
            existing = read_lock()
            mode = existing.get("mode") if existing else "unknown"
            print(f"Another Angelique session is already running (mode={mode}). Exiting.")
            return
    if BRIDGE_PORT is not None:
        os.environ[config.MT5_BRIDGE_HOST_ENV] = BRIDGE_HOST
        os.environ[config.MT5_BRIDGE_PORT_ENV] = str(BRIDGE_PORT)
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
    
    # System ready - always active, no wake word required
    print("🟢 Angelique v2 - Cognitive Architecture Online")
    print(" Trading focus | Memory enabled | Fast AI pipeline")
    print(" Type 'mode terminal' for text CLI. Type 'exit' or 'goodbye' to quit.\n")

    audio_enabled = True
    has_had_conversation = False

    while True:
        user_input = ""
        try:
            if audio_enabled:
                print("🎤 Listening... (press Enter to toggle audio)", end="\r")
                result = [None]
                def listen_thread():
                    result[0] = listen()
                t = threading.Thread(target=listen_thread, daemon=True)
                t.start()
                while t.is_alive():
                    t.join(timeout=0.1)
                    if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                        pressed = input().strip()
                        if pressed == "":
                            audio_enabled = not audio_enabled
                            mode = "🎤 Audio" if audio_enabled else "💬 Text"
                            print(f"\n{mode} mode.")
                        else:
                            user_input = pressed
                        break
                if not user_input and result[0]:
                    user_input = normalize_voice_command(result[0].strip())
                    if user_input:
                        print(f"\n🗣️ You: {user_input}")
            else:
                print("\n💬 Text mode. Type your message, or press Enter to re-enable audio.", end="\n💬 You: ")
                try:
                    pressed = input().strip()
                except EOFError:
                    break
                if pressed == "":
                    audio_enabled = True
                    print("\n🎤 Audio enabled.")
                    continue
                user_input = pressed

            if user_input.lower() in ("mode", "mode terminal", "text mode", "terminal"):
                print("\n💬 Switched to text mode. Type 'mode audio' to return to voice.")
                audio_enabled = False
                continue
            if user_input.lower() in ("mode audio", "audio mode", "voice"):
                print("\n🎤 Switched to audio mode.")
                audio_enabled = True
                continue

            if not user_input:
                continue

        except (EOFError, KeyboardInterrupt):
            break

        lower_input = user_input.lower()
        if lower_input in ["exit", "quit", "goodbye", "shut down", "stop"]:
            print("\n👋 Shutting down...")
            break

        has_had_conversation = True
        print("\n🧠 Thinking...")
        try:
            response = run_cognitive_loop(user_input)
        except Exception as e:
            response = f"I encountered an error processing your request: {e}"
        print(f"\n✨ Angelique: {response}\n")
        if audio_enabled:
            try:
                speak(response)
            except Exception:
                pass
        try:
            if release_lock:
                release_lock()
        except Exception:
            pass

if __name__ == "__main__":
    if os.environ.get(config.ANGELIQUE_LAUNCHED_ENV) == "1":
        main()
    else:
        print("Please start Angelique via launcher.py. Run: python3 launcher.py")
