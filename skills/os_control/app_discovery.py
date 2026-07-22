import os
import glob
import subprocess

def get_installed_apps() -> dict:
    """Dynamically scans the Linux system for installed GUI applications."""
    apps = {}
    
    # 🔥 FIX: Added the Snap directory so it finds apps like Spotify, Discord, etc.
    desktop_dirs = [
        "/usr/share/applications",
        os.path.expanduser("~/.local/share/applications"),
        "/var/lib/flatpak/exports/share/applications",
        "/var/lib/snapd/desktop/applications" 
    ]
    
    for directory in desktop_dirs:
        if not os.path.exists(directory):
            continue
            
        for filepath in glob.glob(os.path.join(directory, "*.desktop")):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    name = None
                    exec_cmd = None
                    
                    for line in f:
                        if line.startswith("Name=") and not name:
                            name = line.split("=", 1)[1].strip()
                            
                        elif line.startswith("Exec=") and not exec_cmd:
                            exec_line = line.split("=", 1)[1].strip()
                            # Clean up arguments like %U, %F, and env variables (e.g., env VAR=val)
                            parts = exec_line.split()
                            for part in parts:
                                if not part.startswith('%') and '=' not in part:
                                    exec_cmd = part
                                    break
                                    
                    if name and exec_cmd:
                        apps[name.lower()] = exec_cmd
                        
            except Exception:
                pass
                
    return apps

def open_app(app_name: str) -> str:
    """Finds an app by fuzzy matching its name and opens it dynamically."""
    installed_apps = get_installed_apps()
    target_app = app_name.lower().strip()
    
    # 1. Exact match
    if target_app in installed_apps:
        cmd = installed_apps[target_app]
        subprocess.Popen([cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Opening {app_name.title()}."
        
    # 2. Fuzzy/Partial match (e.g., "chrome" matches "google chrome", "spot" matches "spotify")
    for name, cmd in installed_apps.items():
        if target_app in name:
            subprocess.Popen([cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Opening {name.title()}."
            
    return f"I couldn't find an app named {app_name} on your system."