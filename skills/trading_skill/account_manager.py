from __future__ import annotations

import time
from typing import Any

from .account import account_snapshot, normalize_mode
from .bridge import WineBridgeClient
from .event_logging import log_event
from .models import AccountSnapshot

LIVE_MODES = {"live", "real"}
DEFAULT_MODE = "demo"
CACHE_TTL_SECONDS = 5.0


class AccountSessionManager:
    def __init__(self, bridge_client: Any = None, refresh_interval: float = CACHE_TTL_SECONDS):
        self.bridge = bridge_client or WineBridgeClient()
        self.refresh_interval = refresh_interval
        self._cache: dict[str, tuple[AccountSnapshot, float]] = {}

    def resolve_mode(self, requested_mode: str | None = None) -> str:
        return "real" if str(requested_mode or DEFAULT_MODE).lower() in LIVE_MODES else DEFAULT_MODE

    def _fetch_snapshot(self, requested_mode: str) -> AccountSnapshot:
        raw = self.bridge.request("account", {"account_mode": requested_mode})
        snapshot = account_snapshot(raw, requested_mode)
        log_event(20, "account_manager.fetch_snapshot", requested_mode=requested_mode, actual_mode=snapshot.actual_mode, connected=snapshot.connected, error=snapshot.error)
        return snapshot

    def get_snapshot(self, requested_mode: str = DEFAULT_MODE, force_refresh: bool = False) -> AccountSnapshot:
        mode = self.resolve_mode(requested_mode)
        cached = self._cache.get(mode)
        if cached is not None and not force_refresh:
            snapshot, timestamp = cached
            if time.monotonic() - timestamp < self.refresh_interval:
                return snapshot
        snapshot = self._fetch_snapshot(mode)
        self._cache[mode] = (snapshot, time.monotonic())
        return snapshot

    def validate_authorization(self, requested_mode: str = DEFAULT_MODE) -> tuple[bool, str, AccountSnapshot]:
        mode = self.resolve_mode(requested_mode)
        snapshot = self.get_snapshot(mode, force_refresh=(mode == "real"))
        if mode == "real" and not snapshot.connected:
            message = "LIVE authorization required and the actual MT5 account does not match the requested real mode."
            log_event(40, "account_manager.live_authorization_failed", requested_mode=requested_mode, actual_mode=snapshot.actual_mode, error=snapshot.error)
            return False, message, snapshot
        return True, "Authorization valid.", snapshot


account_manager = AccountSessionManager()
