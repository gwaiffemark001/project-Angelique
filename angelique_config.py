#!/usr/bin/env python3
"""Helper to manage Angelique default mode and systemd autostart."""
import os
import shutil
import subprocess
import sys
import json

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".config", "angelique", "config.json")
SERVICE_SOURCE = os.path.join(os.path.dirname(__file__), "packaging", "angelique.service")
SERVICE_TARGET = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user", "angelique.service")
COMMAND_PATH = os.path.join(os.path.expanduser("~"), ".config", "angelique", "command.json")


def set_default(mode: str):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"default_mode": mode}, f)
    print(f"Default mode set to: {mode}")


def install_systemd_service(enable: bool = True):
    os.makedirs(os.path.dirname(SERVICE_TARGET), exist_ok=True)
    # Create a venv-aware service file using the current Python executable
    python_exec = sys.executable
    project_dir = os.path.dirname(__file__)
    # ExecStartPre waits up to 30s for a display socket (X11 or Wayland) to appear
    wait_cmd = (
        "for i in $(seq 1 30); do "
        "[ -n \"$DISPLAY\" ] && exit 0; "
        "[ -e /tmp/.X11-unix/X0 ] && exit 0; "
        "[ -n \"$XDG_RUNTIME_DIR\" ] && [ -e \"$XDG_RUNTIME_DIR/wayland-0\" ] && exit 0; "
        "sleep 1; done; exit 0"
    )

    service_content = f"""[Unit]
Description=Angelique AI user service
After=default.target

[Service]
Type=simple
WorkingDirectory={project_dir}
Environment=PYTHONUNBUFFERED=1
ExecStartPre=/bin/sh -c '{wait_cmd}'
ExecStart={python_exec} {os.path.join(project_dir, 'launcher.py')}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
    with open(SERVICE_TARGET, "w", encoding="utf-8") as f:
        f.write(service_content)
    print(f"Wrote service to: {SERVICE_TARGET}")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    if enable:
        subprocess.run(["systemctl", "--user", "enable", "--now", "angelique.service"], check=False)
        print("Enabled and started angelique.service (user systemd)")


def uninstall_systemd_service():
    subprocess.run(["systemctl", "--user", "disable", "--now", "angelique.service"], check=False)
    try:
        os.remove(SERVICE_TARGET)
        print("Removed service file")
    except FileNotFoundError:
        pass
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def switch_mode(mode: str):
    os.makedirs(os.path.dirname(COMMAND_PATH), exist_ok=True)
    cmd = {"action": "switch", "mode": mode}
    with open(COMMAND_PATH, "w", encoding="utf-8") as f:
        json.dump(cmd, f)
    print(f"Wrote switch command to: {COMMAND_PATH}")


def print_help():
    print("Usage: angelique_config.py set-default GUI|TERMINAL|FLOATING")
    print("       angelique_config.py switch-mode GUI|TERMINAL|FLOATING")
    print("       angelique_config.py install-service")
    print("       angelique_config.py uninstall-service")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_help()
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "set-default":
        if len(sys.argv) < 3:
            print_help(); sys.exit(1)
        set_default(sys.argv[2].lower())
    elif cmd == "switch-mode":
        if len(sys.argv) < 3:
            print_help(); sys.exit(1)
        switch_mode(sys.argv[2].lower())
    elif cmd == "install-service":
        install_systemd_service()
    elif cmd == "uninstall-service":
        uninstall_systemd_service()
    else:
        print_help()
