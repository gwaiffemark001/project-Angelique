import csv
import json
import os
import re
import time
import urllib.parse
import webbrowser
import requests
from core import config

CONTACTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contacts.csv")
WHATSAPP_SEND_URL = "https://web.whatsapp.com/send"


def _normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    cleaned = re.sub(r"[^\d\+]+", "", str(phone))
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    return cleaned or None


def _load_whatsapp_contacts() -> list[dict]:
    contacts = []
    if not os.path.exists(CONTACTS_FILE):
        return contacts

    try:
        with open(CONTACTS_FILE, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                phones = []
                for key in ("Phone 1 - Value", "Phone 2 - Value"):
                    value = (row.get(key) or "").strip()
                    if not value:
                        continue
                    for part in re.split(r"[,:;\\/]+| ::: | and ", value):
                        normalized = _normalize_phone(part)
                        if normalized:
                            phones.append(normalized)
                if not phones:
                    continue

                names = []
                for key in ("First Name", "Last Name", "File As", "Nickname", "Organization Name"):
                    value = (row.get(key) or "").strip()
                    if value:
                        names.append(value)

                contacts.append({
                    "names": names,
                    "phones": phones,
                })
    except Exception:
        pass

    return contacts


def _find_contact_phone(contact_name: str) -> str | None:
    if not contact_name:
        return None

    normalized_target = contact_name.strip().lower()
    if not normalized_target:
        return None

    contacts = _load_whatsapp_contacts()
    if not contacts:
        return None

    for contact in contacts:
        for name in contact["names"]:
            normalized_name = name.lower().strip()
            if normalized_name == normalized_target:
                return contact["phones"][0]
            if normalized_target in normalized_name or normalized_name in normalized_target:
                return contact["phones"][0]

    for contact in contacts:
        for name in contact["names"]:
            cleaned_name = re.sub(r"[^a-z0-9 ]", "", name.lower())
            if cleaned_name and (normalized_target in cleaned_name or cleaned_name in normalized_target):
                return contact["phones"][0]

    return None


def _build_whatsapp_url(phone: str, message: str | None = None) -> str:
    params = {"phone": phone}
    if message:
        params["text"] = message
    return f"{WHATSAPP_SEND_URL}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"


def _open_whatsapp_browser(phone: str, message: str | None = None) -> dict:
    try:
        url = _build_whatsapp_url(phone, message)
        webbrowser.open(url)
        return {"success": True, "url": url, "phone": phone}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _get_contact(arg_dict):
    return arg_dict.get('contact_name') or arg_dict.get('contact') or arg_dict.get('contactname') or ''


def send_whatsapp(contact_name=None, message=None, **kwargs):
    contact_name = contact_name or _get_contact(kwargs)
    if not contact_name:
        return "❌ WhatsApp messaging unavailable: no contact provided."
    # 1) Preferred: Use configured WhatsApp API if available (server-side send)
    api_url = getattr(config, "WHATSAPP_API_URL", "")
    api_token = getattr(config, "WHATSAPP_API_TOKEN", "")
    if api_url:
        try:
            payload = {"contact_name": contact_name, "message": message or ""}
            headers = {"Content-Type": "application/json"}
            if api_token:
                headers["Authorization"] = f"Bearer {api_token}"
            resp = requests.post(api_url, json=payload, headers=headers, timeout=10)
            try:
                jr = resp.json()
            except Exception:
                jr = {"status": resp.status_code, "text": resp.text}
            if resp.status_code >= 200 and resp.status_code < 300:
                return f"✅ WhatsApp API accepted message for '{contact_name}': {jr}"
            return f"❌ WhatsApp API failed: {resp.status_code} {jr}"
        except Exception as e:
            # Surface API errors to help debugging instead of silently falling back
            return f"❌ WhatsApp API error: {e}"

    # 2) Playwright automation only when explicitly enabled in config
    if getattr(config, "WHATSAPP_USE_PLAYWRIGHT", False):
        try:
            from skills.messaging.whatsapp_playwright import prepare_whatsapp_message_sync
            result = prepare_whatsapp_message_sync(contact_name, message or "")
            if isinstance(result, dict) and result.get("status") == "DRAFT_READY":
                return f"📝 WhatsApp draft ready for '{contact_name}'. Confirm to send."
            if isinstance(result, dict) and result.get("status") == "SUCCESS":
                return f"✅ WhatsApp message sent to '{contact_name}'."
            return json.dumps(result, ensure_ascii=False)
        except Exception:
            # Fall through to non-Playwright fallback
            pass

    phone = _find_contact_phone(contact_name)
    if not phone:
        return f"❌ WhatsApp messaging unavailable: contact '{contact_name}' was not found in contacts.csv."

    result = _open_whatsapp_browser(phone, message)
    if result.get("success"):
        return f"✅ WhatsApp browser chat opened for '{contact_name}'. Complete send in the browser."
    return f"❌ WhatsApp browser open failed: {result.get('error') or 'unknown error'}"


def draft_whatsapp(contact_name=None, message=None, **kwargs):
    contact_name = contact_name or _get_contact(kwargs)
    if not contact_name:
        return "❌ WhatsApp draft unavailable: no contact provided."

    phone = _find_contact_phone(contact_name)
    if not phone:
        return f"❌ WhatsApp draft unavailable: contact '{contact_name}' was not found in contacts.csv."

    result = _open_whatsapp_browser(phone, message)
    if result.get("success"):
        return f"📝 WhatsApp draft opened for '{contact_name}' in browser."
    return f"❌ WhatsApp browser open failed: {result.get('error') or 'unknown error'}"


def send_whatsapp_approved(contact_name=None, message=None, confirm=False, **kwargs):
    contact_name = contact_name or _get_contact(kwargs)
    if not confirm:
        return f"⚠️ Please confirm sending WhatsApp message to '{contact_name}'. Reply with 'confirm send' to proceed."
    return send_whatsapp(contact_name=contact_name, message=message)


def check_messaging_status() -> str:
    parts = []
    if os.path.exists(CONTACTS_FILE):
        parts.append("WhatsApp Direct: 🟢 contacts.csv loaded")
    else:
        parts.append("WhatsApp Direct: 🔴 contacts.csv missing")
    try:
        from skills.os_control.system_cmds import get_system_health
        h = get_system_health()
        parts.append(f"System: CPU {h.get('cpu_percent', 'N/A')}% | RAM {h.get('memory_percent', 'N/A')}%")
    except Exception:
        parts.append("System info unavailable")
    return " | ".join(parts)


# Removed unused helper `send_email_simulate` which belonged to unrelated email draft functionality.