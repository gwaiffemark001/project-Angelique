import subprocess
import os
import signal
import re
import psutil
import shutil
import platform
import socket
import time
from datetime import datetime
from core import config

_confirm_privileged_command_callback = None
_prompt_for_sudo_password_callback = None
_prompt_for_privileged_command_callback = None


def set_privileged_command_callbacks(confirm_callback=None, password_callback=None, privileged_callback=None):
    global _confirm_privileged_command_callback, _prompt_for_sudo_password_callback, _prompt_for_privileged_command_callback
    _confirm_privileged_command_callback = confirm_callback
    _prompt_for_sudo_password_callback = password_callback
    _prompt_for_privileged_command_callback = privileged_callback


def _is_interactive_sudo_command(command: str) -> bool:
    return bool(re.match(r"^\s*sudo\b", command or ""))


def _is_privileged_command(command: str) -> bool:
    normalized = (command or "").strip().lower()
    if not normalized:
        return False
    # Treat commands prefixed with sudo or pkexec as privileged too
    normalized = re.sub(r"^(sudo\s+|pkexec\s+)", "", normalized)
    privileged_prefixes = (
        "apt-get ",
        "apt ",
        "dnf ",
        "yum ",
        "pacman ",
        "zypper ",
        "systemctl ",
        "service ",
        "shutdown",
        "reboot",
        "mount ",
        "umount ",
        "useradd ",
        "usermod ",
        "userdel ",
    )
    return normalized.startswith(privileged_prefixes)


def run_shell_command(
    command: str,
    timeout: int = 30,
    interactive: bool | None = None,
    sudo_password: str | None = None,
    auto_confirm: bool = False,
) -> str:
    """Execute a shell command safely, supporting GUI-provided sudo credentials when available."""
    try:
        if interactive is None:
            interactive = _is_interactive_sudo_command(command) or _is_privileged_command(command)

        command_to_run = command
        gui_confirmed = False
        stripped_command = (command or "").strip()
        is_privileged = _is_privileged_command(command)
        apt_auto_confirm = bool(re.match(r"^(?:sudo\s+)?(?:apt-get|apt)\s+", stripped_command, flags=re.IGNORECASE))
        if apt_auto_confirm:
            auto_confirm = True

        explicit_auth = sudo_password is not None

        if is_privileged and not explicit_auth and _prompt_for_privileged_command_callback is not None:
            auth_result = _prompt_for_privileged_command_callback(command)
            if auth_result is None:
                if apt_auto_confirm:
                    gui_confirmed = True
                else:
                    return "Command cancelled."

            if isinstance(auth_result, dict):
                if not auth_result.get("confirmed", True):
                    if not apt_auto_confirm:
                        return "Command cancelled."
                    gui_confirmed = True
                else:
                    gui_confirmed = bool(auth_result.get("auto_confirm", True))
                if auth_result.get("password") is not None:
                    sudo_password = str(auth_result.get("password"))
            elif isinstance(auth_result, tuple) and len(auth_result) >= 2:
                confirmed, password = auth_result[0], auth_result[1]
                if not bool(confirmed):
                    if not apt_auto_confirm:
                        return "Command cancelled."
                    gui_confirmed = True
                else:
                    gui_confirmed = True
                sudo_password = None if password is None else str(password)
            elif isinstance(auth_result, str):
                gui_confirmed = True
                sudo_password = auth_result
            else:
                gui_confirmed = bool(auth_result) or apt_auto_confirm

        # Sudo/pkexec commands are already explicitly privileged by their syntax.
        # Do not ask for a redundant second y/n confirmation. The authentication
        # callback below is responsible only for obtaining the user's password.
        if is_privileged and _is_interactive_sudo_command(command):
            gui_confirmed = True
        elif is_privileged and not explicit_auth and _confirm_privileged_command_callback is not None:
            callback_confirmed = bool(_confirm_privileged_command_callback(command))
            if not callback_confirmed and not apt_auto_confirm:
                return "Command cancelled."
            gui_confirmed = gui_confirmed or callback_confirmed or apt_auto_confirm

        if gui_confirmed:
            auto_confirm = True

        if auto_confirm and _is_privileged_command(command):
            stripped = command.strip()
            # Match optional leading sudo, then apt or apt-get, capturing the remainder
            m = re.match(r'^(?:(sudo)\s+)?(apt-get|apt)\b(.*)$', stripped, flags=re.IGNORECASE)
            if m and " -y" not in f" {stripped} ":
                sudo_prefix = (m.group(1) or "").strip()
                apt_cmd = m.group(2)
                rest = (m.group(3) or "").strip()
                # Build command placing -y after apt/apt-get and preserving sudo if present
                if sudo_prefix:
                    command_to_run = f"{sudo_prefix} {apt_cmd} -y {rest}".strip()
                else:
                    command_to_run = f"{apt_cmd} -y {rest}".strip()
            else:
                command_to_run = command

        if sudo_password is None and _prompt_for_sudo_password_callback is not None and _is_privileged_command(command):
            sudo_password = _prompt_for_sudo_password_callback(command)

        if sudo_password is not None and _is_privileged_command(command):
            proc = subprocess.Popen(
                ["sudo", "-S", "-p", "", "bash", "-lc", command_to_run],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = proc.communicate(f"{sudo_password}\n", timeout=timeout)
            output = (stdout or "").strip() or (stderr or "").strip() or "(no output)"
            return f"Exit code: {proc.returncode}\n{output}"

        if interactive and not _is_interactive_sudo_command(command) and _is_privileged_command(command):
            if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
                pkexec_path = shutil.which("pkexec")
                bash_path = shutil.which("bash") or "/bin/bash"
                if pkexec_path:
                    proc = subprocess.Popen([pkexec_path, bash_path, "-lc", command_to_run])
                    return_code = proc.wait()
                    return (
                        f"Interactive command finished with exit code: {return_code}\n"
                        "A GUI authorization dialog should have appeared for the privileged action."
                    )

            command = f"sudo {command_to_run.strip()}"

        if interactive:
            proc = subprocess.Popen(command, shell=True)
            return_code = proc.wait()
            return (
                f"Interactive command finished with exit code: {return_code}\n"
                "If sudo prompted, enter the password directly in the terminal where Angelique is running."
            )

        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        output = proc.stdout.strip()
        if not output:
            output = proc.stderr.strip() or "(no output)"
        return f"Exit code: {proc.returncode}\n{output}"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s."
    except Exception as e:
        return f"Error: {str(e)}"


def get_system_health() -> dict:
    """Returns comprehensive system health information."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()
        boot_time = datetime.fromtimestamp(psutil.boot_time()).isoformat()
        uptime_seconds = time.time() - psutil.boot_time()

        return {
            "cpu_percent": cpu_percent,
            "cpu_cores": psutil.cpu_count(logical=True),
            "cpu_physical_cores": psutil.cpu_count(logical=False),
            "cpu_freq": psutil.cpu_freq().current if psutil.cpu_freq() else 0,
            "memory_total_gb": round(mem.total / (1024**3), 2),
            "memory_used_gb": round(mem.used / (1024**3), 2),
            "memory_percent": mem.percent,
            "memory_available_gb": round(mem.available / (1024**3), 2),
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024**3), 2),
            "network_sent_mb": round(net.bytes_sent / (1024**2), 2),
            "network_recv_mb": round(net.bytes_recv / (1024**2), 2),
            "boot_time": boot_time,
            "uptime_seconds": round(uptime_seconds, 1),
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
        }
    except Exception as e:
        return {"error": str(e)}


def get_running_processes(limit: int = 10) -> str:
    """List top processes by CPU usage."""
    try:
        procs = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
            try:
                info = proc.info
                procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        procs.sort(key=lambda x: x.get('cpu_percent', 0) or 0, reverse=True)
        lines = [f"{'PID':<8} {'CPU%':<8} {'MEM%':<8} {'STATUS':<10} NAME"]
        lines.append("-" * 60)
        for p in procs[:limit]:
            lines.append(f"{p.get('pid', '?'):<8} {p.get('cpu_percent', 0) or 0:<8.1f} {p.get('memory_percent', 0) or 0:<8.1f} {p.get('status', '?'):<10} {p.get('name', '?')}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing processes: {e}"


def kill_process(pid_or_name: str) -> str:
    """Kill a process by PID or name."""
    try:
        pid = int(pid_or_name)
        proc = psutil.Process(pid)
        proc.kill()
        return f"✅ Process {pid} ({proc.name()}) killed."
    except ValueError:
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] == pid_or_name or pid_or_name in proc.info['name']:
                    proc.kill()
                    return f"✅ Process '{pid_or_name}' (PID {proc.info['pid']}) killed."
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return f"❌ Process '{pid_or_name}' not found."
    except Exception as e:
        return f"❌ Kill failed: {e}"


def get_network_interfaces() -> str:
    """List all network interfaces with their addresses."""
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        lines = []
        for iface, addr_list in addrs.items():
            lines.append(f"\n🌐 {iface} ({'UP' if iface in stats and stats[iface].isup else 'DOWN'}):")
            for addr in addr_list:
                lines.append(f"   {addr.family.name}: {addr.address}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


def disk_usage(path: str = "/") -> str:
    """Get disk usage for a path."""
    try:
        usage = psutil.disk_usage(path)
        return f"Disk {path}:\n  Total: {usage.total / (1024**3):.2f} GB\n  Used: {usage.used / (1024**3):.2f} GB\n  Free: {usage.free / (1024**3):.2f} GB\n  Usage: {usage.percent}%"
    except Exception as e:
        return f"Error: {e}"


def list_directory(path: str = ".", recursive: bool = False) -> str:
    """List files and directories."""
    try:
        target = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(target):
            return f"Path is not a directory: {target}"

        items = os.listdir(target)
        lines = []
        for item in sorted(items):
            full = os.path.join(target, item)
            is_dir = os.path.isdir(full)
            size = os.path.getsize(full) if os.path.isfile(full) else 0
            size_str = _human_size(size) if not is_dir else "<DIR>"
            marker = "📁" if is_dir else "📄"
            lines.append(f"  {marker} {item:<40} {size_str}")
        return f"Listing {target} ({len(items)} items):\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing directory: {e}"


def manage_files(action: str, path: str, content: str = "", new_path: str = "") -> str:
    """Comprehensive file management: create, read, delete, move, copy, list."""
    path = os.path.abspath(os.path.expanduser(path))

    if action == "read" or action == "cat":
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception as e:
            return f"❌ Read failed: {e}"

    elif action == "create" or action == "write":
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"✅ File created: {path}"
        except Exception as e:
            return f"❌ Write failed: {e}"

    elif action == "delete" or action == "rm":
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
                return f"🗑️ Directory deleted: {path}"
            os.remove(path)
            return f"🗑️ File deleted: {path}"
        except Exception as e:
            return f"❌ Delete failed: {e}"

    elif action == "move" or action == "mv":
        try:
            new_path = os.path.abspath(os.path.expanduser(new_path)) if new_path else path
            shutil.move(path, new_path)
            return f"📁 Moved: {path} → {new_path}"
        except Exception as e:
            return f"❌ Move failed: {e}"

    elif action == "copy" or action == "cp":
        try:
            new_path = os.path.abspath(os.path.expanduser(new_path)) if new_path else path + ".copy"
            if os.path.isdir(path):
                shutil.copytree(path, new_path)
            else:
                shutil.copy2(path, new_path)
            return f"📋 Copied: {path} → {new_path}"
        except Exception as e:
            return f"❌ Copy failed: {e}"

    elif action == "mkdir" or action == "create_dir":
        try:
            os.makedirs(path, exist_ok=True)
            return f"📁 Directory created: {path}"
        except Exception as e:
            return f"❌ Mkdir failed: {e}"

    elif action == "list" or action == "ls":
        return list_directory(path)

    else:
        return f"Unknown action: {action}. Use: read, create, delete, move, copy, mkdir, list"


def get_network_info() -> dict:
    """Return network configuration information."""
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        try:
            external_ip = requests.get(config.EXTERNAL_IP_LOOKUP_URL, timeout=5).text.strip()
        except Exception:
            external_ip = "unavailable"

        interfaces = {}
        addrs = psutil.net_if_addrs()
        for iface, addr_list in addrs.items():
            for addr in addr_list:
                if addr.family == socket.AF_INET:
                    interfaces[iface] = addr.address

        return {
            "hostname": hostname,
            "local_ip": local_ip,
            "external_ip": external_ip,
            "interfaces": interfaces,
        }
    except Exception as e:
        return {"error": str(e)}


def schedule_task(description: str, command: str, when: str = "now") -> str:
    """Schedule a task using cron (Linux) or at."""
    try:
        if when == "now":
            proc = subprocess.Popen(command, shell=True, start_new_session=True)
            return f"✅ Task started now (PID {proc.pid}): {description}"
        else:
            cron_expr = _parse_when(when)
            if cron_expr:
                cron_job = f"{cron_expr} {command}"
                existing = subprocess.run(['crontab', '-l'], capture_output=True, text=True, timeout=5).stdout
                new_crontab = existing + f"\n{cron_job}\n" if existing else f"{cron_job}\n"
                proc = subprocess.run(['crontab', '-'], input=new_crontab, capture_output=True, text=True, timeout=10)
                if proc.returncode == 0:
                    return f"✅ Cron job scheduled: {cron_expr} — {description}"
                return f"❌ Failed to set cron job."
            else:
                return f"❌ Could not parse time expression: {when}"
    except Exception as e:
        return f"❌ Scheduling failed: {e}"


def _parse_when(when: str) -> str:
    when = when.lower().strip()
    if when in ("now", "immediately", "asap"):
        return ""
    patterns = {
        "every minute": "* * * * *",
        "hourly": "0 * * * *",
        "daily": "0 0 * * *",
        "weekly": "0 0 * * 0",
        "monthly": "0 0 1 * *",
    }
    return patterns.get(when, "")


def get_logs(log_file: str = None, lines: int = 50) -> str:
    """Read the last N lines of a log file."""
    if log_file is None:
        log_dir = str(config.LOG_DIR)
        if os.path.isdir(log_dir):
            logs = os.listdir(log_dir)
            return f"Log directory: {log_dir}\nFiles: {', '.join(logs[:20])}"
        return "No log directory found."

    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            all_lines = f.readlines()
        return f"Last {lines} lines of {log_file}:\n" + "".join(all_lines[-lines:])
    except Exception as e:
        return f"❌ Could not read log file: {e}"


def _human_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


import requests