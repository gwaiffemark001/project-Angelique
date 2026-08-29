from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# Representative market-centre local hours. These are context windows, not execution guarantees.
SESSIONS = {
    "ASIAN": {"timezone": "Asia/Tokyo", "start": 9, "end": 18},
    "LONDON": {"timezone": "Europe/London", "start": 8, "end": 17},
    "NEW_YORK": {"timezone": "America/New_York", "start": 8, "end": 17},
}


def _active(now: datetime, start: int, end: int, zone_name: str) -> bool:
    local = now.astimezone(ZoneInfo(zone_name))
    decimal_hour = local.hour + local.minute / 60.0
    return start <= decimal_hour < end


def current_session(now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    active = [
        name for name, definition in SESSIONS.items()
        if _active(now, int(definition["start"]), int(definition["end"]), str(definition["timezone"]))
    ]
    overlap = "LONDON" in active and "NEW_YORK" in active
    primary = "LONDON_NEW_YORK_OVERLAP" if overlap else (active[0] if active else "OFF_HOURS")
    return {
        "session": primary,
        "active_sessions": active,
        "overlap": overlap,
        "utc_timestamp": now.isoformat(),
        "timezone": str(SESSIONS.get(active[0], {}).get("timezone", "UTC")) if active else "UTC",
    }
