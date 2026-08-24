from datetime import datetime

from skills.wifi_control.router_client import normalize_devices


def test_allow_device_for_duration_uses_now_to_window_end(monkeypatch):
    from skills.wifi_control import router_client

    captured = {}
    fixed_now = datetime(2026, 8, 19, 12, 0, 0)

    class FakeDateTime(datetime):
        @classmethod
        def now(cls):
            return fixed_now

    class FakeTimer:
        def __init__(self, delay, callback, args=None, kwargs=None):
            captured["delay"] = delay
            captured["callback"] = callback
            captured["args"] = args or ()
            captured["kwargs"] = kwargs or {}
            self.cancelled = False
        def cancel(self):
            self.cancelled = True
        def start(self):
            captured["started"] = True

    monkeypatch.setattr(router_client, "datetime", FakeDateTime)
    monkeypatch.setattr(router_client, "allow_device_forever", lambda mac, **kwargs: {"ok": True})
    monkeypatch.setattr(router_client, "add_access_schedule", lambda mac, start, end, day_mask=0, **kwargs: captured.update({"mac": mac, "start": start, "end": end, "day_mask": day_mask}) or {"ok": True})
    monkeypatch.setattr(router_client.threading, "Timer", FakeTimer)

    router_client.allow_device_for_duration("AA:BB", 1)

    assert captured["mac"] == "AA:BB"
    assert captured["start"] == "12:00"
    assert captured["end"] == "12:01"
    assert captured["day_mask"] == 3
    assert captured["delay"] == 60
    assert captured["started"] is True


def test_normalize_mf296a_device_records():
    payload = {"lan_station_list": [{"hostname": "Dell", "mac": "AA:BB", "ip": "192.168.18.4", "status": "Online"}]}

    assert normalize_devices(payload) == [{
        "name": "Dell",
        "mac": "AA:BB",
        "ip": "192.168.18.4",
        "status": "Online",
        "raw": payload["lan_station_list"][0],
    }]


def test_normalize_unknown_payload_is_empty():
    assert normalize_devices({"unexpected": "shape"}) == []


def test_schedule_payload_uses_captured_mf296a_format(monkeypatch):
    captured = {}
    monkeypatch.setenv("ANGELIQUE_WIFI_AD", "test-ad")
    from skills.wifi_control import router_client

    monkeypatch.setattr(router_client, "_router_opener", None)
    monkeypatch.setattr(router_client, "_ensure_router_session", lambda **kwargs: None)
    monkeypatch.setattr(router_client, "urlopen", lambda request, timeout: captured.update({"body": request.data}) or _FakeResponse())
    router_client.add_access_schedule("AA:BB", "23:55", "23:56", day_mask=10)

    assert b"goformId=CHILD_MAC_RULE_ADD" in captured["body"]
    assert b"child_mac_rule_info=AA%3ABB%3B10%2B23%3A55%2C23%3A56%2C1%3B" in captured["body"]


def test_router_ad_uses_mf296a_sha256_chain(monkeypatch):
    from skills.wifi_control import router_client

    responses = iter([
        {"wa_inner_version": "web", "cr_version": "firmware"},
        {"RD": "router-random"},
    ])
    monkeypatch.delenv("ANGELIQUE_WIFI_AD", raising=False)
    monkeypatch.setattr(router_client, "request_router_command", lambda *args, **kwargs: next(responses))
    first = router_client.hashlib.sha256(b"webfirmware").hexdigest().upper()
    expected = router_client.hashlib.sha256((first + "router-random").encode()).hexdigest().upper()

    assert router_client._router_ad() == expected


def test_access_schedule_response_is_normalized(monkeypatch):
    from skills.wifi_control import router_client

    monkeypatch.setattr(router_client, "_ensure_router_session", lambda **kwargs: None)
    monkeypatch.setattr(router_client, "request_router_command", lambda *args, **kwargs: {
        "child_mac_rule_info": "AA:BB;10+23:55,23:56,1;2+08:00,09:00,0;"
    })

    assert router_client.get_access_schedules("AA:BB") == [
        {"index": 0, "day_mask": 10, "start": "23:55", "end": "23:56", "enabled": True},
        {"index": 1, "day_mask": 2, "start": "08:00", "end": "09:00", "enabled": False},
    ]


def test_access_list_fields_are_normalized(monkeypatch):
    from skills.wifi_control import router_client

    monkeypatch.setattr(router_client, "_ensure_router_session", lambda **kwargs: None)
    monkeypatch.setattr(router_client, "request_router_command", lambda *args, **kwargs: {"AclMode": "2", "BlackMacList": "AA:BB;", "BlackNameList": "Phone;"})

    assert router_client.get_access_control_list() == {"mode": "2", "white_macs": "", "white_names": "", "black_macs": "AA:BB;", "black_names": "Phone;"}


def test_disconnected_devices_come_from_blacklist(monkeypatch):
    from skills.wifi_control import router_client

    monkeypatch.setattr(router_client, "_ensure_router_session", lambda **kwargs: None)
    monkeypatch.setattr(router_client, "get_access_control_list", lambda **kwargs: {
        "mode": "2", "white_macs": "", "white_names": "",
        "black_macs": "AA:BB;CC:DD;", "black_names": "Phone;Tablet;",
    })

    assert router_client.list_disconnected_devices() == [
        {"name": "Phone", "mac": "AA:BB", "ip": "--", "status": "Disconnected"},
        {"name": "Tablet", "mac": "CC:DD", "ip": "--", "status": "Disconnected"},
    ]


def test_login_hash_uses_router_ld_challenge(monkeypatch):
    from skills.wifi_control import router_client

    monkeypatch.setattr(router_client, "request_router_command", lambda *args, **kwargs: {"LD": "challenge"})
    captured = {}

    def fake_urlopen(request, timeout):
        if request.data:
            captured["body"] = request.data
            return _FakeResponse(b'{"result":"0"}')
        return _FakeResponse()

    monkeypatch.setattr(router_client, "urlopen", fake_urlopen)
    router_client.login_router(password="admin")
    first = router_client.hashlib.sha256(b"admin").hexdigest().upper()
    expected = router_client.hashlib.sha256((first + "challenge").encode()).hexdigest().upper()
    assert expected.encode() in captured["body"]


class _FakeResponse:
    def __init__(self, body=b"{}"):
        self.body = body
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, *_args):
        return self.body