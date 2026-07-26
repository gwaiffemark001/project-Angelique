import os
import subprocess
import sys
import json
import time
from pathlib import Path


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".config", "angelique", "config.json")
COMMAND_PATH = os.path.join(os.path.expanduser("~"), ".config", "angelique", "command.json")


def _wait_for_display(timeout: int = 30) -> bool:
    """Wait for an X or Wayland display to be available.
    Returns True if a display appears within timeout, otherwise False.
    """
    start = time.time()
    while time.time() - start < timeout:
        # common X11 socket
        if os.environ.get("DISPLAY"):
            return True
        if os.path.exists("/tmp/.X11-unix/X0"):
            return True
        # wayland socket
        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg and os.path.exists(os.path.join(xdg, "wayland-0")):
            return True
        time.sleep(0.5)
    return False


def _read_default_mode() -> str:
    # priority: env ANGELIQUE_DEFAULT_MODE > user config file > 'floating'
    env = os.environ.get("ANGELIQUE_DEFAULT_MODE")
    if env:
        return env.lower()

    try:
        with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            mode = cfg.get("default_mode", "floating")
            return str(mode).lower()
    except Exception:
        return "floating"



def _child_cmd_for_mode(mode: str):
    mode = (mode or "").lower()
    if mode == "terminal":
        return [sys.executable, os.path.join(ROOT, "main.py")]
    elif mode == "floating":
        return [sys.executable, os.path.join(ROOT, "gui", "angelique_gui.py"), "--floating"]
    else:
        # default: gui
        return [sys.executable, os.path.join(ROOT, "gui", "angelique_gui.py")]


def launch_child_process(mode: str):
    """Start the child process for the given mode and return the Popen object."""
    cmd = _child_cmd_for_mode(mode)
    # Ensure child processes know they were launched by the supervisor
    env = os.environ.copy()
    env["ANGELIQUE_LAUNCHED"] = "1"
    return subprocess.Popen(cmd, cwd=ROOT, env=env)


def _write_switch_command(mode: str):
    os.makedirs(os.path.dirname(COMMAND_PATH), exist_ok=True)
    with open(COMMAND_PATH, "w", encoding="utf-8") as f:
        json.dump({"action": "switch", "mode": mode}, f)


def _print_usage_and_exit():
    print("Usage: launcher.py [--gui|--terminal|--floating|--set-default MODE|--switch-mode MODE]")
    print("When no mode is provided, launcher reads the user's default mode from ~/.config/angelique/config.json or env ANGELIQUE_DEFAULT_MODE.")
    sys.exit(1)


if __name__ == "__main__":
    # Support: --gui, --terminal, --floating, --set-default MODE
    if len(sys.argv) > 1:
        if sys.argv[1] == "--gui":
            launch_child_process("gui").wait()
        elif sys.argv[1] == "--floating":
            launch_child_process("floating").wait()
        elif sys.argv[1] == "--terminal":
            launch_child_process("terminal").wait()
        elif sys.argv[1] == "--switch-mode":
            if len(sys.argv) < 3:
                _print_usage_and_exit()
            new_mode = sys.argv[2].lower()
            os.makedirs(os.path.dirname(COMMAND_PATH), exist_ok=True)
            with open(COMMAND_PATH, "w", encoding="utf-8") as f:
                json.dump({"action": "switch", "mode": new_mode}, f)
            print(f"Wrote switch command to {COMMAND_PATH}")
        elif sys.argv[1] == "--set-default":
            if len(sys.argv) < 3:
                _print_usage_and_exit()
            mode = sys.argv[2].lower()
            os.makedirs(os.path.dirname(DEFAULT_CONFIG_PATH), exist_ok=True)
            with open(DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump({"default_mode": mode}, f)
            print(f"Set default mode to: {mode}")
        elif sys.argv[1] == "--switch-mode":
            if len(sys.argv) < 3:
                _print_usage_and_exit()
            mode = sys.argv[2].lower()
            _write_switch_command(mode)
            print(f"Switch command written: {mode}")
        else:
            _print_usage_and_exit()
    else:
        # Supervisor mode: respect configured default and watch for runtime commands
        os.makedirs(os.path.dirname(DEFAULT_CONFIG_PATH), exist_ok=True)
        os.makedirs(os.path.dirname(COMMAND_PATH), exist_ok=True)

        while True:
            default_mode = _read_default_mode()
            # If default is a GUI mode, wait for display before launching to avoid terminal-first startup
            if default_mode in ("gui", "floating"):
                if not _wait_for_display(timeout=30):
                    # No display found; fallback to terminal to avoid hanging
                    print("[launcher] No display available; falling back to terminal mode.")
                    default_mode = "terminal"
            proc = launch_child_process(default_mode)
            try:
                while proc.poll() is None:
                    # check for command file
                    if os.path.exists(COMMAND_PATH):
                        try:
                            with open(COMMAND_PATH, "r", encoding="utf-8") as cf:
                                cmd = json.load(cf)
                        except Exception:
                            cmd = None
                        if cmd and cmd.get("action") == "switch":
                            new_mode = str(cmd.get("mode", "gui")).lower()
                            # update default config
                            with open(DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
                                json.dump({"default_mode": new_mode}, f)
                            # remove command
                            try:
                                os.remove(COMMAND_PATH)
                            except Exception:
                                pass
                            # restart child
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
            # if child exited unexpectedly, wait a bit and restart
            time.sleep(1)
