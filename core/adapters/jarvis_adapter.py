"""Proof-of-concept adapter to load Jarvis projects as Angelique skills.

This adapter tries to locate a Jarvis-like project under `base projects/` and
import the `Jarvis` package to use its `JarvisAssistant` methods.

The functions below are thin wrappers: `time()`, `date()`, `system_info()`.
They return strings when available or raise ImportError if no Jarvis package
is found.
"""
from pathlib import Path
import sys
import importlib


_assistant = None
_jarvis_module = None


def _find_jarvis_module():
    global _jarvis_module
    if _jarvis_module is not None:
        return _jarvis_module
    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        project_root / "base projects" / "JARVIS",
        project_root / "base projects" / "Jarvis",
        project_root / "base projects" / "Jarvis-Desktop-Voice-Assistant",
        project_root / "base projects" / "OpenJarvis",
    ]
    for cand in candidates:
        if not cand.exists():
            continue
        # Add candidate directory to path so its subpackages can be imported
        sys.path.insert(0, str(cand))
        try:
            # Most Jarvis forks expose a `Jarvis` package directory
            mod = importlib.import_module("Jarvis")
            _jarvis_module = mod
            return mod
        except Exception:
            # fallback: some variants use lowercase or other names; try to find any package
            for child in cand.iterdir():
                if child.is_dir() and (child / "__init__.py").exists():
                    try:
                        mod = importlib.import_module(child.name)
                        _jarvis_module = mod
                        return mod
                    except Exception:
                        continue
    raise ImportError("No Jarvis package found under base projects")


def get_jarvis_assistant():
    """Return an instantiated JarvisAssistant from the discovered Jarvis package.

    Raises ImportError if no Jarvis package is present.
    """
    global _assistant
    if _assistant is not None:
        return _assistant
    mod = _find_jarvis_module()
    assistant_cls = getattr(mod, "JarvisAssistant", None)
    if assistant_cls is None:
        # try common alternative class names
        for name in ("Jarvis", "Assistant", "JarvisAssistant"):
            assistant_cls = getattr(mod, name, None)
            if assistant_cls:
                break
    if assistant_cls is None:
        raise ImportError("Jarvis package found but no assistant class was detected")
    _assistant = assistant_cls()
    return _assistant


def time():
    """Return current time string via Jarvis assistant."""
    assistant = get_jarvis_assistant()
    if hasattr(assistant, "tell_time"):
        return assistant.tell_time()
    # some variants use date_time.time() function directly
    mod = _find_jarvis_module()
    if hasattr(mod, "features") and hasattr(mod.features, "date_time"):
        return mod.features.date_time.time()
    raise AttributeError("Jarvis assistant does not expose time functionality")


def date():
    """Return current date string via Jarvis assistant."""
    assistant = get_jarvis_assistant()
    if hasattr(assistant, "tell_me_date"):
        return assistant.tell_me_date()
    mod = _find_jarvis_module()
    if hasattr(mod, "features") and hasattr(mod.features, "date_time"):
        return mod.features.date_time.date()
    raise AttributeError("Jarvis assistant does not expose date functionality")


def system_info():
    """Return system stats string via Jarvis assistant."""
    assistant = get_jarvis_assistant()
    if hasattr(assistant, "system_info"):
        return assistant.system_info()
    # fallback to features.system_stats
    mod = _find_jarvis_module()
    try:
        return mod.features.system_stats.system_stats()
    except Exception:
        raise AttributeError("Jarvis assistant does not expose system_info functionality")
