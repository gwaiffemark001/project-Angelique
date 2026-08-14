"""Adapter to expose Jarvis `jarviscli` plugins as Angelique-callable actions.

This adapter discovers plugin modules under `base projects/Jarvis/jarviscli/plugins`.
It provides `list_plugins()` and `call_plugin(name, text)` functions. Calls are performed
with a best-effort strategy: if the plugin backend expects (jarvis_api, s) we pass
`None` for the API and the provided `text` string. The adapter returns any exception
messages as strings to avoid raising inside the main loop.
"""
from pathlib import Path
import sys
import importlib
import inspect


def _plugins_dir():
    root = Path(__file__).resolve().parents[2]
    cand = root / "base projects" / "Jarvis" / "jarviscli" / "plugins"
    if cand.exists():
        return cand
    return None


def list_plugins():
    pd = _plugins_dir()
    if not pd:
        return []
    names = []
    for p in pd.glob("*.py"):
        if p.name.startswith("__"):
            continue
        names.append(p.stem)
    return names


def _import_plugin_module(name):
    pd = _plugins_dir()
    if not pd:
        raise ImportError("Jarvis jarviscli plugins folder not found")
    # ensure path on sys.path
    sys.path.insert(0, str(pd.parent))
    try:
        return importlib.import_module(f"jarviscli.plugins.{name}")
    except Exception:
        # try importing by file stem from plugins dir
        spec = importlib.util.spec_from_file_location(name, str(pd / f"{name}.py"))
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        raise


def call_plugin(name: str, text: str = "") -> str:
    try:
        mod = _import_plugin_module(name)
    except Exception as e:
        return f"Error importing plugin {name}: {e}"

    # find callables or Plugin classes
    for attr in dir(mod):
        val = getattr(mod, attr)
        # If it's a class created by @plugin decorator, it will have _backend_instance
        if inspect.isclass(val) and hasattr(val, "_backend_instance"):
            try:
                backend = getattr(val, "_backend_instance")
                if callable(backend):
                    # many plugins expect (jarvis_api, s)
                    try:
                        result = backend(None, text)
                        return str(result) if result is not None else "OK"
                    except TypeError:
                        # try calling with no args
                        return str(backend())
            except Exception as e:
                return f"Error running plugin {name}: {e}"
        # fallback: top-level callables
        if callable(val) and not attr.startswith("_"):
            try:
                sig = inspect.signature(val)
                if len(sig.parameters) == 0:
                    return str(val())
                if len(sig.parameters) == 1:
                    return str(val(text))
                # try best-effort calling with text and None
                return str(val(None, text))
            except Exception as e:
                return f"Error calling plugin function {attr} in {name}: {e}"

    return f"No callable entrypoint found in plugin {name}"
