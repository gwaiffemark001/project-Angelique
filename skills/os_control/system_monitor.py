import psutil
import os
import platform
from datetime import datetime


def get_system_health() -> dict:
    try:
        cpu_percent = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        boot_time = datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")
        uptime = time.time() - psutil.boot_time()
        return {
            "cpu_percent": cpu_percent,
            "cpu_cores": psutil.cpu_count(logical=True),
            "memory_total_gb": round(mem.total / (1024**3), 2),
            "memory_used_gb": round(mem.used / (1024**3), 2),
            "memory_percent": mem.percent,
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_percent": disk.percent,
            "boot_time": boot_time,
            "uptime_hours": round(uptime / 3600, 1),
            "platform": platform.platform(),
            "hostname": platform.node(),
        }
    except Exception as e:
        return {"error": str(e)}


def get_running_processes(limit: int = 10) -> str:
    try:
        procs = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                procs.append(proc.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x.get('cpu_percent', 0) or 0, reverse=True)
        lines = [f"{'PID':<8} {'CPU%':<8} {'MEM%':<8} NAME"]
        lines.append("-" * 55)
        for p in procs[:limit]:
            lines.append(f"{p.get('pid', '?'):<8} {p.get('cpu_percent', 0) or 0:<8.1f} {p.get('memory_percent', 0) or 0:<8.1f} {p.get('name', '?')}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


import time