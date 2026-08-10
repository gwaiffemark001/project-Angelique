import json
import os
import errno
from pathlib import Path


SESSION_DIR = Path.home() / ".config" / "angelique"
SESSION_LOCK = SESSION_DIR / "session.lock"


def _ensure_dir():
    try:
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _is_pid_running(pid: int) -> bool:
    try:
        # signal 0 does not kill; it raises exception if no process
        os.kill(pid, 0)
    except OSError as e:
        if e.errno == errno.ESRCH:
            return False
        if e.errno == errno.EPERM:
            return True
        return False
    else:
        return True


def read_lock():
    _ensure_dir()
    if not SESSION_LOCK.exists():
        return None
    try:
        with open(SESSION_LOCK, "r", encoding="utf-8") as f:
            data = json.load(f)
            pid = int(data.get("pid"))
            mode = str(data.get("mode", "unknown"))
            if _is_pid_running(pid):
                return {"pid": pid, "mode": mode}
            # stale lock
            try:
                SESSION_LOCK.unlink()
            except Exception:
                pass
            return None
    except Exception:
        return None


def acquire_lock(mode: str) -> bool:
    """Attempt to acquire the session lock for `mode` (gui|terminal).
    Returns True on success, False if another live session exists."""
    _ensure_dir()
    existing = read_lock()
    if existing:
        return False
    try:
        with open(SESSION_LOCK, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "mode": mode}, f)
        return True
    except Exception:
        return False


def release_lock():
    try:
        if SESSION_LOCK.exists():
            with open(SESSION_LOCK, "r", encoding="utf-8") as f:
                data = json.load(f)
                pid = int(data.get("pid", 0))
                if pid != os.getpid():
                    # don't remove someone else's lock
                    return False
            SESSION_LOCK.unlink()
            return True
    except Exception:
        pass
    return False
