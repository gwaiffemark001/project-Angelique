"""Small client for the ZTE MF296A local management API.

The device-list command is confirmed from the router's web UI capture. Write
commands remain configurable until the exact schedule payload is captured.
"""

from __future__ import annotations

import json
import hashlib
import os
import threading
from datetime import datetime, timedelta
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


DEFAULT_HOST = "192.168.18.1"
DEFAULT_DEVICE_COMMAND = "station_list"
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/151.0.0.0 Safari/537.36",
    "Referer": f"http://{DEFAULT_HOST}/index.html",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
}
_router_opener = None
_router_login_lock = threading.Lock()
_router_cookie = ""
_timed_access_timers: dict[str, threading.Timer] = {}


def _base_url(host: str | None = None) -> str:
    configured = host or os.getenv("ANGELIQUE_WIFI_ROUTER_HOST", DEFAULT_HOST)
    return configured if configured.startswith("http") else f"http://{configured}"


def _open(request: Request, timeout: float):
    return urlopen(request, timeout=timeout)


def login_router(host: str | None = None, password: str | None = None, timeout: float = 5.0) -> dict:
    """Log in to the MF296A and retain its cookie in Angelique's process."""
    global _router_opener, _router_cookie
    with _router_login_lock:
        landing_request = Request(f"{_base_url(host)}/index.html", headers=_BROWSER_HEADERS)
        with urlopen(landing_request, timeout=timeout) as response:
            response.read(1)
        login_data = request_router_command("LD", host=host, timeout=timeout)
        login_digest = str(login_data.get("LD", "")) if isinstance(login_data, dict) else ""
        if not login_digest:
            raise RuntimeError("Router did not return a login challenge")
        raw_password = password if password is not None else os.getenv("ANGELIQUE_WIFI_PASSWORD", "admin")
        first = hashlib.sha256(raw_password.encode("utf-8")).hexdigest().upper()
        encoded_password = hashlib.sha256((first + login_digest).encode("utf-8")).hexdigest().upper()
        payload = urlencode({"isTest": "false", "goformId": "LOGIN", "password": encoded_password}).encode("utf-8")
        request = Request(
            f"{_base_url(host)}/goform/goform_set_cmd_process",
            data=payload,
            headers={**_BROWSER_HEADERS, "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(request, timeout=timeout) as response:
            _router_cookie = response.headers.get("Set-Cookie", "").split(";", 1)[0]
            result = json.loads(response.read().decode("utf-8", errors="replace"))
        if str(result.get("result")) not in {"0", "4", "success"}:
            _router_opener = None
            _router_cookie = ""
            raise RuntimeError(f"Router login failed: {result.get('result', 'unknown error')}")
        return result


def _ensure_router_session(host: str | None = None, timeout: float = 5.0):
    if not _router_cookie:
        login_router(host=host, timeout=timeout)


def request_router_command(command: str, params: dict | None = None, host: str | None = None, timeout: float = 5.0):
    """Call a read command exposed by the router and return decoded JSON."""
    query = {"isTest": "false", "cmd": command}
    query.update(params or {})
    url = f"{_base_url(host)}/goform/goform_get_cmd_process?{urlencode(query)}"
    headers = {**_BROWSER_HEADERS, "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    session = os.getenv("ANGELIQUE_WIFI_SESSION", "")
    headers["Cookie"] = session or _router_cookie
    request = Request(url, headers=headers)
    with _open(request, timeout) as response:
        payload = response.read().decode("utf-8", errors="replace")
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Router returned a non-JSON response") from exc


def _router_ad(host: str | None = None, timeout: float = 5.0) -> str:
    configured = os.getenv("ANGELIQUE_WIFI_AD", "")
    if configured:
        return configured
    versions = request_router_command("Language,cr_version,wa_inner_version", params={"multi_data": "1"}, host=host, timeout=timeout)
    rd_payload = request_router_command("RD", host=host, timeout=timeout)
    if not isinstance(versions, dict) or not isinstance(rd_payload, dict):
        raise RuntimeError("Router did not return authentication parameters")
    rd0 = str(versions.get("wa_inner_version", ""))
    rd1 = str(versions.get("cr_version", ""))
    rd = str(rd_payload.get("RD", ""))
    if not rd:
        raise RuntimeError("Router did not return RD authentication value")
    first = hashlib.sha256((rd0 + rd1).encode("utf-8")).hexdigest().upper()
    return hashlib.sha256((first + rd).encode("utf-8")).hexdigest().upper()


def _write_router_command(form: dict, host: str | None = None, timeout: float = 5.0):
    ad = _router_ad(host=host, timeout=timeout)
    payload = {"isTest": "false", **form, "AD": ad}
    headers = {**_BROWSER_HEADERS, "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    session = os.getenv("ANGELIQUE_WIFI_SESSION", "")
    headers["Cookie"] = session or _router_cookie
    request = Request(
        f"{_base_url(host)}/goform/goform_set_cmd_process",
        data=urlencode(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with _open(request, timeout) as response:
        body = response.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


def _first(record: dict, *keys: str, default: str = ""):
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return default


def _records(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("lan_station_list", "station_list", "stations", "data", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _records(value)
            if nested:
                return nested
    return []


def normalize_devices(payload) -> list[dict]:
    """Convert MF296A records to fields used by Angelique's dashboard."""
    devices = []
    for index, record in enumerate(_records(payload), start=1):
        if not isinstance(record, dict):
            continue
        devices.append({
            "name": _first(record, "hostname", "name", "dev_name", default=f"Device {index}"),
            "mac": _first(record, "mac", "mac_addr", "macAddress", default="—"),
            "ip": _first(record, "ip", "ip_addr", "ipAddress", default="—"),
            "status": _first(record, "status", "online", "connect_status", default="Online"),
            "raw": record,
        })
    return devices


def list_connected_devices(host: str | None = None, timeout: float = 5.0) -> list[dict]:
    _ensure_router_session(host=host, timeout=timeout)
    command = os.getenv("ANGELIQUE_WIFI_DEVICE_COMMAND", DEFAULT_DEVICE_COMMAND)
    return normalize_devices(request_router_command(command, host=host, timeout=timeout))


def add_access_schedule(mac: str, start: str, end: str, day_mask: int = 0, host: str | None = None, timeout: float = 5.0):
    """Add a restricted-access rule using the MF296A's captured payload format."""
    if not mac or not start or not end:
        raise ValueError("mac, start, and end are required")
    _ensure_router_session(host=host, timeout=timeout)
    rule = f"{int(day_mask)}+{start},{end},1;"
    return _write_router_command({
        "goformId": "CHILD_MAC_RULE_ADD",
        "child_mac_rule_info": f"{mac};{rule}",
    }, host=host, timeout=timeout)


def get_access_schedules(mac: str, host: str | None = None, timeout: float = 5.0) -> list[dict]:
    """Read and normalize the restricted-access rules for one managed device."""
    _ensure_router_session(host=host, timeout=timeout)
    payload = request_router_command("child_mac_rule_info", params={"mac_addr": mac}, host=host, timeout=timeout)
    raw = payload.get("child_mac_rule_info", "") if isinstance(payload, dict) else ""
    parts = [part for part in str(raw).split(";") if part]
    schedules = []
    for index, part in enumerate(parts[1:]):
        fields = part.split("+")
        if len(fields) != 2:
            continue
        times = fields[1].split(",")
        if len(times) != 3:
            continue
        schedules.append({"index": index, "day_mask": int(fields[0] or 0), "start": times[0], "end": times[1], "enabled": times[2] == "1"})
    return schedules


def get_access_control_list(host: str | None = None, timeout: float = 5.0) -> dict:
    """Read the router's permanent MAC access-control lists."""
    _ensure_router_session(host=host, timeout=timeout)
    payload = request_router_command("queryDeviceAccessControlList", host=host, timeout=timeout)
    return {
        "mode": str(payload.get("AclMode", "0")) if isinstance(payload, dict) else "0",
        "white_macs": str(payload.get("WhiteMacList", "")) if isinstance(payload, dict) else "",
        "white_names": str(payload.get("WhiteNameList", "")) if isinstance(payload, dict) else "",
        "black_macs": str(payload.get("BlackMacList", "")) if isinstance(payload, dict) else "",
        "black_names": str(payload.get("BlackNameList", "")) if isinstance(payload, dict) else "",
    }


def list_disconnected_devices(host: str | None = None, timeout: float = 5.0) -> list[dict]:
    """Return devices currently held in the router's permanent MAC blacklist."""
    access = get_access_control_list(host=host, timeout=timeout)
    macs = _list_field(access["black_macs"])
    names = _list_field(access["black_names"])
    return [
        {"name": names[index] if index < len(names) else mac, "mac": mac, "ip": "--", "status": "Disconnected"}
        for index, mac in enumerate(macs)
    ]


def set_access_control_list(access: dict, host: str | None = None, timeout: float = 5.0):
    """Persist permanent allow/block MAC lists on the router."""
    return _write_router_command({
        "goformId": "setDeviceAccessControlList",
        "AclMode": access.get("mode", "2"),
        "WhiteMacList": access.get("white_macs", ""),
        "WhiteNameList": access.get("white_names", ""),
        "BlackMacList": access.get("black_macs", ""),
        "BlackNameList": access.get("black_names", ""),
    }, host=host, timeout=timeout)


def _list_field(value: str) -> list[str]:
    return [item for item in value.split(";") if item]


def disconnect_device(mac: str, name: str = "", host: str | None = None, timeout: float = 5.0):
    """Manually disconnect and persistently block a device until allowed again."""
    if not mac:
        raise ValueError("mac is required")
    access = get_access_control_list(host=host, timeout=timeout)
    macs = _list_field(access["black_macs"])
    names = _list_field(access["black_names"])
    if mac not in macs:
        macs.append(mac)
        names.append(name or mac)
    access["mode"] = "2"
    access["black_macs"] = ";".join(macs) + ";"
    access["black_names"] = ";".join(names) + ";"
    return set_access_control_list(access, host=host, timeout=timeout)


def allow_device_forever(mac: str, host: str | None = None, timeout: float = 5.0):
    """Remove permanent blocking and timed restrictions for a device."""
    if not mac:
        raise ValueError("mac is required")
    access = get_access_control_list(host=host, timeout=timeout)
    pairs = [(m, n) for m, n in zip(_list_field(access["black_macs"]), _list_field(access["black_names"])) if m != mac]
    access["black_macs"] = ";".join(item[0] for item in pairs) + (";" if pairs else "")
    access["black_names"] = ";".join(item[1] for item in pairs) + (";" if pairs else "")
    result = set_access_control_list(access, host=host, timeout=timeout)
    remove_access_schedule(mac, host=host, timeout=timeout)
    return result


def _expire_timed_access(mac: str, host: str | None = None, timeout: float = 5.0):
    try:
        disconnect_device(mac, name=mac, host=host, timeout=timeout)
    finally:
        _timed_access_timers.pop(mac, None)


def allow_device_for_duration(mac: str, minutes: int, host: str | None = None, timeout: float = 5.0):
    """Allow a device for a bounded window and then disconnect it when the window expires."""
    if minutes < 1 or minutes > 1440:
        raise ValueError("minutes must be between 1 and 1440")
    now = datetime.now()
    end = now + timedelta(minutes=minutes)
    if end.date() != now.date():
        raise ValueError("Timed access cannot cross midnight on this router")

    existing = _timed_access_timers.pop(mac, None)
    if existing is not None:
        existing.cancel()

    allow_device_forever(mac, host=host, timeout=timeout)
    schedule_result = add_access_schedule(
        mac,
        now.strftime("%H:%M"),
        end.strftime("%H:%M"),
        day_mask=now.weekday() + 1 if now.weekday() < 6 else 0,
        host=host,
        timeout=timeout,
    )

    timer = threading.Timer(minutes * 60, _expire_timed_access, args=(mac,), kwargs={"host": host, "timeout": timeout})
    timer.daemon = True
    _timed_access_timers[mac] = timer
    timer.start()
    return schedule_result


def remove_access_schedule(mac: str, host: str | None = None, timeout: float = 5.0):
    """Remove all restricted-access rules for a managed device."""
    if not mac:
        raise ValueError("mac is required")
    _ensure_router_session(host=host, timeout=timeout)
    return _write_router_command({
        "goformId": "CHILD_MAC_RULE_DELETE",
        "mac_addr": mac,
    }, host=host, timeout=timeout)


def get_router_status(host: str | None = None, timeout: float = 5.0) -> dict:
    """Return a compact status object for the desktop dashboard."""
    devices = list_connected_devices(host=host, timeout=timeout)
    return {"host": (host or os.getenv("ANGELIQUE_WIFI_ROUTER_HOST", DEFAULT_HOST)), "online": True, "device_count": len(devices), "devices": devices}