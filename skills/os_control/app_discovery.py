import os
import glob
import subprocess

def get_installed_apps() -> dict:
    """Dynamically scans the Linux system for installed GUI applications."""
    apps = {}
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
                            exec_cmd = " ".join([part for part in exec_line.split() if not part.startswith('%')])
                    if name and exec_cmd:
                        apps[name.lower()] = exec_cmd
            except Exception:
                pass
    return apps

def open_app(app_name: str) -> str:
    """Finds an app by smart fuzzy matching and opens it dynamically."""
    installed_apps = get_installed_apps()
    target_app = app_name.lower().strip()
    
    # 1. Exact match
    if target_app in installed_apps:
        cmd = installed_apps[target_app]
        print(f"🔍 [DEBUG] Attempting to launch exact match '{target_app}' with command: {cmd}")
        try:
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return f"Opening {app_name.title()}."
        except Exception as e:
            return f"Failed to open {app_name}: {str(e)}"
            
    # 2. Smart Fuzzy Match with Tie-Breaker
    best_match = None
    best_score = -1
    best_length = 0
    
    for name, cmd in installed_apps.items():
        target_words = set(target_app.split())
        name_words = set(name.split())
        
        # Score based on overlapping words
        score = len(target_words.intersection(name_words))
        
        # Massive bonus if the name contains the entire target string
        if target_app in name:
            score += 10
            
        # Tie-breaker: if scores are equal, prefer the longer (more specific) app name
        if score > best_score or (score == best_score and len(name) > best_length):
            best_score = score
            best_match = (name, cmd)
            best_length = len(name)
            
    if best_match and best_score > 0:
        name, cmd = best_match
        print(f"🔍 [DEBUG] Smart fuzzy match found: '{name}' (score: {best_score}) -> launching with command: {cmd}")
        try:
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return f"Opening {name.title()}."
        except Exception as e:
            return f"Failed to open {name}: {str(e)}"
            
    return f"I couldn't find an app named '{app_name}' on your system. Try asking me to 'list all apps' to find the exact name."