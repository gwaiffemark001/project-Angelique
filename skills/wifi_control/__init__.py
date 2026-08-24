"""Local router access-control skill for Angelique."""

from .router_client import (
    add_access_schedule,
    allow_device_forever,
    allow_device_for_duration,
    disconnect_device,
    get_access_schedules,
    get_access_control_list,
    get_router_status,
    login_router,
    list_connected_devices,
    list_disconnected_devices,
    remove_access_schedule,
    request_router_command,
)

__all__ = ["add_access_schedule", "allow_device_forever", "allow_device_for_duration", "disconnect_device", "get_access_control_list", "get_access_schedules", "get_router_status", "list_connected_devices", "list_disconnected_devices", "login_router", "remove_access_schedule", "request_router_command"]