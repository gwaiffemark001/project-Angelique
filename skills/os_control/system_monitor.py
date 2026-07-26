# skills/os_control/system_monitor.py
import os
import psutil
import platform

def get_system_health() -> str:
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count_logical = psutil.cpu_count(logical=True)
        cpu_count_physical = psutil.cpu_count(logical=False)
        ram = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage('/')
        load_avg = os.getloadavg() if hasattr(os, 'getloadavg') else (0.0, 0.0, 0.0)

        report = (
            f"🖥️ OS: {platform.system()} {platform.release()}\n"
            f"⚙️ CPU: {cpu_count_physical or cpu_count_logical} physical / {cpu_count_logical} logical cores\n"
            f"⚙️ CPU Usage: {cpu_percent}%\n"
            f"📈 Load Average (1m, 5m, 15m): {load_avg[0]:.2f}, {load_avg[1]:.2f}, {load_avg[2]:.2f}\n"
            f"🧠 RAM: {ram.percent}% used ({ram.used // (1024**2)} MiB of {ram.total // (1024**3)} GiB)\n"
            f"🔁 Swap: {swap.percent}% used ({swap.used // (1024**2)} MiB of {swap.total // (1024**3)} GiB)\n"
            f"💾 Disk: {disk.percent}% used ({disk.used // (1024**3)} GiB of {disk.total // (1024**3)} GiB)\n"
            f"🌐 Platform: {platform.machine()}"
        )
        return report
    except Exception as e:
        return f"Failed to read system stats: {str(e)}"

def get_running_processes(limit: int = 10) -> str:
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
            try:
                processes.append(proc.info)
            except:
                pass
        
        processes.sort(key=lambda x: x['cpu_percent'] or 0, reverse=True)
        top_procs = processes[:limit]
        
        report_lines = ["Top CPU consuming processes:"]
        for p in top_procs:
            report_lines.append(f"- {p.get('name','unknown')} (PID: {p.get('pid','?')}): {p.get('cpu_percent',0)}%")
        report = "\n".join(report_lines)
        return report
    except Exception as e:
        return f"Failed: {str(e)}"
