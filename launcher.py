import os
import shutil
import subprocess
import sys
import json
import time
from pathlib import Path

try:
    from core import config
except Exception:
    config = None

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".config", "angelique", "config.json")
COMMAND_PATH = os.path.join(os.path.expanduser("~"), ".config", "angelique", "command.json")

# Ensure child processes can import the project package modules by adding ROOT to PYTHONPATH.
def _ensure_pythonpath_in_env(env: dict) -> dict:
    try:
        existing = env.get("PYTHONPATH", "")
        if existing:
            env["PYTHONPATH"] = ROOT + os.pathsep + existing
        else:
            env["PYTHONPATH"] = ROOT
    except Exception:
        pass
    return env

def _read_default_mode() -> str:
    env_name = config.ANGELIQUE_DEFAULT_MODE_ENV if config is not None else "ANGELIQUE_DEFAULT_MODE"
    env = os.environ.get(env_name)
    if env:
        return env.lower()
    try:
        with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            mode = cfg.get("default_mode", "gui")
            return str(mode).lower()
    except Exception:
        return "gui"

def _child_cmd_for_mode(mode: str):
    mode = (mode or "").lower()
    if mode == "terminal":
        return [sys.executable, os.path.join(ROOT, "main.py")]
    else:
        gui_script = os.path.join(ROOT, "gui", "angelique_desktop.py")
        if os.environ.get("DISPLAY"):
            return [sys.executable, gui_script]
        if shutil.which("xvfb-run"):
            return ["xvfb-run", "-a", sys.executable, gui_script]
        return [sys.executable, gui_script]


def _check_session_conflict(mode: str) -> bool:
    """Return True if another active session conflicts with requested mode."""
    try:
        from core.session_lock import read_lock
    except Exception:
        return False
    existing = read_lock()
    if not existing:
        return False
    existing_mode = existing.get("mode")
    if existing_mode and existing_mode != mode:
        return True
    return False

def _to_windows_path(path: str) -> str:
    if shutil.which("winepath") is None:
        return path
    try:
        completed = subprocess.run([
            "winepath", "-w", path
        ], capture_output=True, text=True, check=True)
        return completed.stdout.strip() or path
    except Exception:
        return path


def _get_wine_bridge_command() -> list[str] | None:
    for exe in ("wine", "wine64"):
        if shutil.which(exe):
            return [exe, "cmd", "/c", "python"]
    return None


def launch_child_process(mode: str):
    # Prevent launching a child if another differing session is active
    if _check_session_conflict(mode):
        print(f"Refusing to launch {mode} because another Angelique session is active.")
        raise SystemExit(1)
    cmd = _child_cmd_for_mode(mode)
    env = os.environ.copy()
    launched_env_name = config.ANGELIQUE_LAUNCHED_ENV if config is not None else "ANGELIQUE_LAUNCHED"
    env[launched_env_name] = "1"
    env = _ensure_pythonpath_in_env(env)
    return subprocess.Popen(cmd, cwd=ROOT, env=env)

def _write_switch_command(mode: str):
    os.makedirs(os.path.dirname(COMMAND_PATH), exist_ok=True)
    with open(COMMAND_PATH, "w", encoding="utf-8") as f:
        json.dump({"action": "switch", "mode": mode}, f)

def _print_usage_and_exit():
    print("Usage: launcher.py [--gui|--terminal|--set-default MODE|--switch-mode MODE]")
    print("  --gui         Launch native desktop GUI mode (default)")
    print("  --terminal    Launch terminal/CLI mode")
    print("  --set-default MODE  Set default startup mode (gui/terminal)")
    print("  --switch-mode MODE  Switch mode at runtime (writes command file)")
    sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--gui":
            launch_child_process("gui").wait()
        elif sys.argv[1] == "--start-bridge":
            # Start the demo MT5 bridge server in foreground via Wine
            bridge_script = os.path.join(ROOT, "skills", "trading", "engine", "mt5_bridge_server.py")
            wine_cmd = _get_wine_bridge_command()
            if wine_cmd is None:
                print("Wine is not available; cannot launch MT5 bridge.")
                raise SystemExit(1)
            windows_bridge_script = _to_windows_path(bridge_script)
            subprocess.run(wine_cmd + [windows_bridge_script], cwd=ROOT)
        elif sys.argv[1] == "--start-bridge-bg":
            # Start the demo MT5 bridge server in background and return via Wine
            bridge_script = os.path.join(ROOT, "skills", "trading", "engine", "mt5_bridge_server.py")
            wine_cmd = _get_wine_bridge_command()
            if wine_cmd is None:
                print("Wine is not available; cannot launch MT5 bridge.")
                raise SystemExit(1)
            windows_bridge_script = _to_windows_path(bridge_script)
            subprocess.Popen(wine_cmd + [windows_bridge_script], cwd=ROOT)
        elif sys.argv[1] == "--terminal":
            launch_child_process("terminal").wait()
        elif sys.argv[1] == "--set-default":
            if len(sys.argv) < 3:
                _print_usage_and_exit()
            mode = sys.argv[2].lower()
            if mode not in ("gui", "terminal"):
                mode = "gui"
            os.makedirs(os.path.dirname(DEFAULT_CONFIG_PATH), exist_ok=True)
            with open(DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({"default_mode": mode}, f)
            print(f"Default mode set to: {mode}")
        elif sys.argv[1] == "--switch-mode":
            if len(sys.argv) < 3:
                _print_usage_and_exit()
            mode = sys.argv[2].lower()
            _write_switch_command(mode)
            print(f"Switch command written: {mode}")
        else:
            _print_usage_and_exit()
    else:
        os.makedirs(os.path.dirname(DEFAULT_CONFIG_PATH), exist_ok=True)
        os.makedirs(os.path.dirname(COMMAND_PATH), exist_ok=True)

        while True:
            default_mode = _read_default_mode()
            if default_mode not in ("gui", "terminal"):
                default_mode = "gui"

            proc = launch_child_process(default_mode)
            try:
                while proc.poll() is None:
                    if os.path.exists(COMMAND_PATH):
                        try:
                            with open(COMMAND_PATH, "r", encoding="utf-8") as cf:
                                cmd = json.load(cf)
                        except Exception:
                            cmd = None
                        if cmd and cmd.get("action") == "switch":
                            new_mode = str(cmd.get("mode", "gui")).lower()
                            if new_mode in ("gui", "terminal"):
                                with open(DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
                                    json.dump({"default_mode": new_mode}, f)
                                try:
                                    os.remove(COMMAND_PATH)
                                except Exception:
                                    pass
                                proc.terminate()
                                proc.wait(timeout=10)
                                break
                    time.sleep(0.5)
            except KeyboardInterrupt:
                try:
                    proc.terminate()
                except Exception:
                    pass
                raise
            time.sleep(1)