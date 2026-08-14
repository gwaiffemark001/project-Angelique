"""Adapters for integrating external helper projects into Angelique.

This package contains adapters that load modules from `base projects/` and
expose thin wrappers that match Angelique skill interfaces.
"""

from .jarvis_adapter import get_jarvis_assistant, time, date, system_info
from .local_calendar_adapter import list_calendars, get_events, add_event, remove_event

__all__ = [
	"get_jarvis_assistant",
	"time",
	"date",
	"system_info",
	"list_calendars",
	"get_events",
	"add_event",
	"remove_event",
]
