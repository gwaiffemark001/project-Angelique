from __future__ import annotations
"""Local calendar adapter: read .ics files when available, otherwise use a local JSON store.

Provides safe, offline calendar access without Google OAuth.
"""
import os
import json
from pathlib import Path
from typing import List, Dict, Optional
import uuid
from datetime import datetime

CAL_DIR_CANDIDATES = [
    Path.home() / "Calendar",
    Path.home() / "Calendars",
    Path.home() / ".calendar",
    Path.home() / ".local" / "share" / "calendar",
]

LOCAL_STORE = Path(__file__).resolve().parent.parent.parent / "data" / "local_calendar.json"


def _ensure_store():
    if not LOCAL_STORE.parent.exists():
        LOCAL_STORE.parent.mkdir(parents=True, exist_ok=True)
    if not LOCAL_STORE.exists():
        LOCAL_STORE.write_text(json.dumps({"events": []}, indent=2))


def list_calendars() -> List[str]:
    found = []
    for p in CAL_DIR_CANDIDATES:
        if p.exists() and p.is_dir():
            for f in p.iterdir():
                if f.suffix.lower() in (".ics",):
                    found.append(str(f))
    # Always include local store as a calendar option
    found.append(str(LOCAL_STORE))
    return found


def _parse_simple_ics(path: Path) -> List[Dict]:
    events = []
    try:
        text = path.read_text(errors="ignore")
    except Exception:
        return events
    blocks = text.split("BEGIN:VEVENT")
    for blk in blocks[1:]:
        try:
            end = blk.split("END:VEVENT")[0]
            ev = {}
            for line in end.splitlines():
                if line.startswith("SUMMARY:"):
                    ev["summary"] = line.partition(":")[2].strip()
                if line.startswith("DTSTART"):
                    ev["start"] = line.split(":",1)[1].strip()
                if line.startswith("DTEND"):
                    ev["end"] = line.split(":",1)[1].strip()
                if line.startswith("DESCRIPTION:"):
                    ev["description"] = line.partition(":")[2].strip()
            ev["id"] = str(uuid.uuid4())
            events.append(ev)
        except Exception:
            continue
    return events


def get_events(date: Optional[str] = None, calendar_path: Optional[str] = None) -> List[Dict]:
    """Return events for a given ISO date (YYYY-MM-DD). If no date provided, return upcoming events from both .ics and local store."""
    results = []
    # Scan ICS files if specified or in calendar list
    calendars = [Path(calendar_path)] if calendar_path else [Path(p) for p in list_calendars()]
    for cal in calendars:
        if not cal.exists():
            continue
        if cal.suffix.lower() == ".ics":
            results.extend(_parse_simple_ics(cal))
        elif cal.name == LOCAL_STORE.name:
            _ensure_store()
            try:
                data = json.loads(LOCAL_STORE.read_text())
                for ev in data.get("events", []):
                    results.append(ev)
            except Exception:
                continue

    if date:
        filtered = []
        for ev in results:
            start = ev.get("start", "")
            try:
                if start.startswith("TZID"):
                    # naive handling
                    start_date = start.split(":",1)[1][:10]
                else:
                    start_date = start[:10]
                if start_date == date:
                    filtered.append(ev)
            except Exception:
                continue
        return filtered
    return results


def add_event(title: str, start_iso: str, end_iso: Optional[str] = None, description: Optional[str] = None, calendar_path: Optional[str] = None) -> Dict:
    """Add an event to the local JSON store. start_iso/end_iso are ISO datetimes (YYYY-MM-DDTHH:MM).

    Returns the created event dict.
    """
    _ensure_store()
    try:
        data = json.loads(LOCAL_STORE.read_text())
    except Exception:
        data = {"events": []}
    ev = {
        "id": str(uuid.uuid4()),
        "summary": title,
        "start": start_iso,
        "end": end_iso or start_iso,
        "description": description or "",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    data.setdefault("events", []).append(ev)
    LOCAL_STORE.write_text(json.dumps(data, indent=2))
    return ev


def remove_event(event_id: str) -> bool:
    _ensure_store()
    try:
        data = json.loads(LOCAL_STORE.read_text())
    except Exception:
        return False
    orig = len(data.get("events", []))
    data["events"] = [e for e in data.get("events", []) if e.get("id") != event_id]
    LOCAL_STORE.write_text(json.dumps(data, indent=2))
    return len(data.get("events", [])) < orig


__all__ = ["list_calendars", "get_events", "add_event", "remove_event"]
