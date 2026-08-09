import os
import subprocess
import platform
import psutil


def _normalize_version(version: str | None) -> str | None:
    if version is None:
        return None
    cleaned = str(version).strip().lstrip("vV")
    return cleaned or None


def _split_version_parts(version: str) -> list[object]:
    parts: list[object] = []
    for chunk in re.split(r"[._+\-]", version):
        if not chunk:
            continue
        if chunk.isdigit():
            parts.append(int(chunk))
            continue
        numeric_match = re.match(r"^(\d+)([A-Za-z].*)$", chunk)
        if numeric_match:
            parts.append(int(numeric_match.group(1)))
            suffix = numeric_match.group(2)
            if suffix:
                parts.append(suffix.lower())
            continue
        parts.append(chunk.lower())
    return parts


def _compare_versions(installed_version: str, requested_version: str) -> int:
    installed_parts = _split_version_parts(_normalize_version(installed_version) or installed_version)
    requested_parts = _split_version_parts(_normalize_version(requested_version) or requested_version)
    max_length = max(len(installed_parts), len(requested_parts))
    for index in range(max_length):
        installed_part = installed_parts[index] if index < len(installed_parts) else 0
        requested_part = requested_parts[index] if index < len(requested_parts) else 0
        if installed_part == requested_part:
            continue
        if isinstance(installed_part, int) and isinstance(requested_part, int):
            return 1 if installed_part > requested_part else -1
        installed_text = str(installed_part)
        requested_text = str(requested_part)
        if installed_text == requested_text:
            continue
        return 1 if installed_text > requested_text else -1
    return 0


def _version_satisfies(installed_version: str, requested_version: str, version_mode: str = "exact") -> bool:
    normalized_mode = (version_mode or "exact").strip().lower()
    installed_normalized = _normalize_version(installed_version)
    requested_normalized = _normalize_version(requested_version)
    if not installed_normalized or not requested_normalized:
        return False
    if normalized_mode in {"minimum", "at_least", "atleast", "gte", "greater_or_equal", "greater-than-or-equal"}:
        return _compare_versions(installed_normalized, requested_normalized) >= 0
    return installed_normalized == requested_normalized


def _linux_installed_packages() -> list[str]:
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Package}\n"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode != 0:
            return []
        return [line.strip().lower() for line in (result.stdout or "").splitlines() if line.strip()]
    except Exception:
        return []


def _linux_package_versions(package_name: str) -> list[str]:
    try:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${Package}\t${Version}\n", package_name],
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode != 0:
            return []
        versions = []
        for line in (result.stdout or "").splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2 and parts[0].strip().lower() == package_name.lower():
                versions.append(parts[1].strip())
        return versions
    except Exception:
        return []


def _is_executable_or_desktop_target(target_name: str) -> tuple[bool, str | None]:
    lower_target = target_name.lower()

    try:
        result = subprocess.run(["which", lower_target], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return True, result.stdout.strip()
    except Exception:
        pass

    apps = get_installed_apps()
    if lower_target in apps:
        return True, apps[lower_target].get("name")

    for key, info in apps.items():
        app_name = str(info.get("name", "")).lower()
        exec_line = str(info.get("exec", "")).lower()
        if lower_target in key or lower_target in app_name or lower_target in exec_line:
            return True, info.get("name")

    return False, None


def check_installed(target_name: str, version: str | None = None, version_mode: str = "exact", working: bool = False) -> str:
    """Check whether a package or application appears to be installed."""
    normalized = (target_name or "").strip()
    if not normalized:
        return "No target provided to check installation status."

    system = platform.system()
    lower_target = normalized.lower()
    requested_version = _normalize_version(version)
    normalized_mode = (version_mode or "exact").strip().lower()

    def _version_message(match: bool, installed_versions: list[str], matched_package: str | None = None) -> str:
        if not requested_version:
            return ""
        if match:
            if normalized_mode in {"minimum", "at_least", "atleast", "gte", "greater_or_equal", "greater-than-or-equal"}:
                return f"✅ '{normalized}' meets minimum version {requested_version}."
            return f"✅ '{normalized}' is installed and matches version {requested_version}."
        if installed_versions:
            version_text = ", ".join(installed_versions)
            if normalized_mode in {"minimum", "at_least", "atleast", "gte", "greater_or_equal", "greater-than-or-equal"}:
                return f"⚠️ '{normalized}' is installed, but minimum version {requested_version} was not met. Installed version(s): {version_text}."
            return f"⚠️ '{normalized}' is installed, but version {requested_version} was not found. Installed version(s): {version_text}."
        if matched_package:
            return f"✅ '{normalized}' appears to be installed as package '{matched_package}', but its version could not be verified."
        return f"✅ '{normalized}' appears to be installed, but its version could not be verified."

    if system == "Linux":
        try:
            result = subprocess.run(
                ["dpkg", "-s", lower_target],
                capture_output=True,
                text=True,
                timeout=5,
            )
            stdout = (result.stdout or "").lower()
            if result.returncode == 0 and "status: install ok installed" in stdout:
                installed_versions = _linux_package_versions(lower_target)
                if requested_version:
                    if any(_version_satisfies(installed_version, requested_version, normalized_mode) for installed_version in installed_versions):
                        return _version_message(True, installed_versions)
                    return _version_message(False, installed_versions)
                return f"✅ '{normalized}' appears to be installed as a package."
        except Exception:
            pass

        for package_name in _linux_installed_packages():
            if lower_target == package_name or lower_target in package_name:
                if requested_version:
                    installed_versions = _linux_package_versions(package_name)
                    if any(_version_satisfies(installed_version, requested_version, normalized_mode) for installed_version in installed_versions):
                        if normalized_mode in {"minimum", "at_least", "atleast", "gte", "greater_or_equal", "greater-than-or-equal"}:
                            return f"✅ '{normalized}' is installed as package '{package_name}' and meets minimum version {requested_version}."
                        return f"✅ '{normalized}' is installed as package '{package_name}' and matches version {requested_version}."
                    if installed_versions:
                        version_text = ", ".join(installed_versions)
                        if normalized_mode in {"minimum", "at_least", "atleast", "gte", "greater_or_equal", "greater-than-or-equal"}:
                            return f"⚠️ '{normalized}' is installed as package '{package_name}', but minimum version {requested_version} was not met. Installed version(s): {version_text}."
                        return f"⚠️ '{normalized}' is installed as package '{package_name}', but version {requested_version} was not found. Installed version(s): {version_text}."
                    return f"✅ '{normalized}' appears to be installed as package '{package_name}', but its version could not be verified."
                return f"✅ '{normalized}' appears to be installed as package '{package_name}'."

        executable_found, resolved_name = _is_executable_or_desktop_target(normalized)
        if executable_found:
            if resolved_name and resolved_name.lower() != lower_target:
                suffix = f" and appears to be working" if working else ""
                return f"✅ '{normalized}' appears to be installed{suffix} and available as '{resolved_name}'."
            suffix = f" and appears to be working" if working else ""
            return f"✅ '{normalized}' appears to be installed{suffix} and available."

        return f"❌ '{normalized}' does not appear to be installed."

    if system == "Windows":
        apps = get_installed_apps()
        if lower_target in apps:
            suffix = f" and appears to be working" if working else ""
            return f"✅ '{apps[lower_target].get('name', normalized)}' appears to be installed{suffix}."
        for key, info in apps.items():
            if lower_target in key or lower_target in str(info.get("name", "")).lower():
                suffix = f" and appears to be working" if working else ""
                return f"✅ '{info.get('name', normalized)}' appears to be installed{suffix}."
        return f"❌ '{normalized}' does not appear to be installed."

    return f"❌ Platform '{system}' not supported for installation checks."


def open_app(app_name: str) -> str:
    """Open a GUI application by name."""
    system = platform.system()

    if system == "Linux":
        desktop_file_map = {
            "firefox": "firefox.desktop",
            "chrome": "google-chrome.desktop", "chromium": "chromium.desktop",
            "code": "code.desktop", "vscode": "code.desktop", "visual studio code": "code.desktop",
            "nautilus": "org.gnome.Nautilus.desktop", "files": "org.gnome.Nautilus.desktop",
            "terminal": "gnome-terminal.desktop", "konsole": "konsole.desktop",
            "thunderbird": "thunderbird.desktop", "libreoffice": "libreoffice.desktop",
            "vlc": "vlc.desktop", "gimp": "gimp.desktop",
        }

        if app_name.lower() in desktop_file_map:
            desktop_file = desktop_file_map[app_name.lower()]
            try:
                subprocess.Popen(
                    ["xdg-open", f"/usr/share/applications/{desktop_file}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return f"✅ Launched '{app_name}' via desktop file."
            except Exception:
                pass

        try:
            subprocess.Popen([app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"✅ Launched '{app_name}'."
        except FileNotFoundError:
            pass

        try:
            result = subprocess.run(
                ["which", app_name], capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                subprocess.Popen([app_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"✅ Launched '{app_name}' (found at {result.stdout.strip()})."
        except Exception:
            pass

        return f"❌ '{app_name}' not found. Use 'list apps' to see installed applications."

    elif system == "Windows":
        try:
            subprocess.Popen(app_name, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"✅ Launched '{app_name}'."
        except Exception:
            return f"❌ Failed to launch '{app_name}'."

    else:
        return f"❌ Platform '{system}' not supported for app launching."


def get_installed_apps() -> dict:
    """List all installed GUI applications on the system."""
    system = platform.system()
    apps = {}

    if system == "Linux":
        desktop_dirs = [
            "/usr/share/applications",
            os.path.expanduser("~/.local/share/applications"),
            "/var/lib/flatpak/exports/share/applications",
            os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
        ]

        for desktop_dir in desktop_dirs:
            if not os.path.isdir(desktop_dir):
                continue
            for filename in sorted(os.listdir(desktop_dir)):
                if filename.endswith(".desktop"):
                    filepath = os.path.join(desktop_dir, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        name = None
                        exec_line = None
                        for line in content.split('\n'):
                            if line.startswith("Name=") and not name:
                                name = line[5:].strip()
                            if line.startswith("Exec=") and not exec_line:
                                exec_line = line[5:].strip()
                        if name:
                            apps[name.lower()] = {
                                "name": name,
                                "file": filename,
                                "exec": exec_line,
                                "desktop_file": filepath,
                            }
                    except Exception:
                        continue

    elif system == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths")
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(key, i)
                    path, _ = winreg.QueryValueEx(winreg.OpenKey(key, name), "")
                    apps[name.lower()] = {"name": name, "path": path}
                    i += 1
                except OSError:
                    break
        except Exception:
            pass

    return apps


def close_app(app_name: str) -> str:
    """Close a running application by name."""
    try:
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if app_name.lower() in proc.info['name'].lower():
                    proc.kill()
                    return f"✅ Closed '{app_name}' (PID {proc.info['pid']})."
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return f"❌ Process '{app_name}' not found."
    except Exception as e:
        return f"❌ Close failed: {e}"


def list_apps() -> str:
    """Return a formatted list of installed applications."""
    apps = get_installed_apps()
    if not apps:
        return "No installed applications found."

    lines = [f"📱 Installed Applications ({len(apps)} total):\n"]
    for i, (key, info) in enumerate(sorted(apps.items())[:50], 1):
        name = info.get('name', key)
        lines.append(f"  {i}. {name}")

    if len(apps) > 50:
        lines.append(f"\n... and {len(apps) - 50} more.")

    return "\n".join(lines)