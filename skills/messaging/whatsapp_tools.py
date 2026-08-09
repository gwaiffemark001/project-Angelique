import os
import re
import time
import json

try:
    from skills.messaging.whatsapp_playwright import prepare_whatsapp_message_sync, execute_whatsapp_send_sync
    _HAS_WPP = True
except ImportError:
    _HAS_WPP = False


def _get_contact(arg_dict):
    return arg_dict.get('contact_name') or arg_dict.get('contact') or arg_dict.get('contactname') or ''


def send_whatsapp(contact_name=None, message=None, **kwargs):
    contact_name = contact_name or _get_contact(kwargs)
    try:
        if not _HAS_WPP:
            return "WhatsApp messaging unavailable (playwright not configured)."
        result = prepare_whatsapp_message_sync(contact_name, message)
        if result.get("error"):
            return f"❌ Draft failed: {result['error']}"
        send_result = execute_whatsapp_send_sync()
        if send_result.get("success"):
            return f"✅ Message sent to {contact_name}."
        return f"❌ Send failed: {send_result.get('error', 'Unknown error')}"
    except Exception as e:
        return f"❌ WhatsApp send failed: {e}"


def draft_whatsapp(contact_name=None, message=None, **kwargs):
    contact_name = contact_name or _get_contact(kwargs)
    try:
        if not _HAS_WPP:
            return "WhatsApp messaging unavailable."
        result = prepare_whatsapp_message_sync(contact_name, message)
        return f"📝 WhatsApp draft for {contact_name}:\n{json.dumps(result, indent=2)}"
    except Exception as e:
        return f"❌ Draft failed: {e}"


def send_whatsapp_approved(contact_name=None, message=None, confirm=False, **kwargs):
    contact_name = contact_name or _get_contact(kwargs)
    if not confirm:
        return f"⚠️ Please confirm sending WhatsApp message to '{contact_name}'. Reply with 'confirm send' to proceed."
    return send_whatsapp(contact_name=contact_name, message=message)


def check_messaging_status() -> str:
    parts = []
    if _HAS_WPP:
        parts.append("WhatsApp Web: 🟢 Available")
    else:
        parts.append("WhatsApp Web: 🔴 Unavailable")
    try:
        from skills.os_control.system_cmds import get_system_health
        h = get_system_health()
        parts.append(f"System: CPU {h.get('cpu_percent', 'N/A')}% | RAM {h.get('memory_percent', 'N/A')}%")
    except Exception:
        parts.append("System info unavailable")
    return " | ".join(parts)


def send_email_simulate(to, subject, body):
    try:
        draft_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "email_drafts"
        )
        os.makedirs(draft_dir, exist_ok=True)
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', subject)[:40]
        draft_path = os.path.join(draft_dir, f"draft_{int(time.time())}_{safe_name}.eml")
        with open(draft_path, "w") as f:
            f.write(f"To: {to}\nSubject: {subject}\n\n{body}")
        return f"📧 Email draft saved to: {draft_path}"
    except Exception as e:
        return f"❌ Email draft failed: {e}"