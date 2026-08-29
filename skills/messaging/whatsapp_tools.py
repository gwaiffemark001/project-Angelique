from __future__ import annotations
import csv, re
from pathlib import Path
import requests
from core import config

CONTACTS_FILE = Path(getattr(config, "WHATSAPP_CONTACTS_FILE", Path(__file__).with_name("contacts.csv")))
if not CONTACTS_FILE.is_absolute():
    CONTACTS_FILE = (config.PROJECT_ROOT / CONTACTS_FILE).resolve()

def _normalize_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9+]", "", str(value))
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if not digits.startswith("+") and digits:
        digits = "+" + digits
    return digits or None

def load_contacts() -> list[dict]:
    if not CONTACTS_FILE.exists():
        return []
    contacts=[]
    with CONTACTS_FILE.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            names=[(row.get(k) or "").strip() for k in ("First Name","Middle Name","Last Name","File As","Nickname","Organization Name")]
            names=[n for n in names if n]
            phones=[]
            for key in ("Phone 1 - Value","Phone 2 - Value"):
                for part in re.split(r"\s*(?:,|;|/|\\|:::)\s*", row.get(key) or ""):
                    phone=_normalize_phone(part)
                    if phone: phones.append(phone)
            if names and phones:
                contacts.append({"names": names, "phones": list(dict.fromkeys(phones))})
    return contacts

def resolve_contact(name: str) -> str | None:
    """Resolve a human contact reference using exact, token and fuzzy matching.

    A single strong match is accepted even when the user omits a middle name or
    a few words added by the command parser. Ties remain ambiguous and are not
    guessed.
    """
    query = re.sub(r"[^a-z0-9 ]", "", str(name or "").lower()).strip()
    if not query:
        return None
    query_tokens = set(query.split())
    contacts = load_contacts()
    scored = []
    for contact in contacts:
        for raw in contact["names"]:
            clean = re.sub(r"[^a-z0-9 ]", "", raw.lower()).strip()
            tokens = set(clean.split())
            score = 0
            if query == clean:
                score = 100
            elif query in clean or clean in query:
                score = 85
            else:
                overlap = len(query_tokens & tokens)
                if overlap:
                    score = 60 + overlap * 8 - abs(len(query_tokens) - len(tokens))
            if score:
                scored.append((score, clean, contact))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], x[1]))
    best_score = scored[0][0]
    best_contacts = []
    seen = set()
    for score, _, contact in scored:
        if score != best_score:
            break
        ident = id(contact)
        if ident not in seen:
            seen.add(ident)
            best_contacts.append(contact)
    if len(best_contacts) != 1:
        return None
    return best_contacts[0]["phones"][0]

def _send_http(phone: str, message: str) -> dict:
    provider=str(getattr(config,"WHATSAPP_PROVIDER","generic") or "generic").lower()
    if provider == "meta":
        token=getattr(config,"WHATSAPP_ACCESS_TOKEN","")
        phone_id=getattr(config,"WHATSAPP_PHONE_NUMBER_ID","")
        if not token or not phone_id:
            raise RuntimeError("WhatsApp Meta provider is not configured: WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are required.")
        version=getattr(config,"WHATSAPP_GRAPH_VERSION","v23.0")
        url=f"https://graph.facebook.com/{version}/{phone_id}/messages"
        headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"}
        payload={"messaging_product":"whatsapp","to":phone.lstrip("+"),"type":"text","text":{"body":message}}
    else:
        url=str(getattr(config,"WHATSAPP_API_URL","") or "").strip()
        if not url: raise RuntimeError("WHATSAPP_API_URL is not configured.")
        headers={"Content-Type":"application/json"}
        token=getattr(config,"WHATSAPP_API_TOKEN","")
        if token: headers["Authorization"]=f"Bearer {token}"
        payload={"to":phone,"message":message}
    response=requests.post(url,headers=headers,json=payload,timeout=8)
    if not response.ok:
        raise RuntimeError(f"WhatsApp gateway HTTP {response.status_code}: {response.text[:500]}")
    try: body=response.json()
    except ValueError: body={"status_code":response.status_code,"text":response.text[:500]}
    return body

def send_whatsapp(contact_name: str | None=None, message: str | None=None, **kwargs) -> dict:
    contact_name=contact_name or kwargs.get("contact") or kwargs.get("contactname")
    if not contact_name or not message:
        raise ValueError("contact_name and message are required")
    phone=resolve_contact(contact_name)
    if not phone:
        raise LookupError(f"Contact '{contact_name}' is not uniquely present in contacts.csv")
    body=_send_http(phone, str(message))
    return {"success":True,"contact":contact_name,"phone":phone,"provider":getattr(config,"WHATSAPP_PROVIDER","generic"),"response":body}

def prepare_whatsapp_message(contact_name: str, message: str, **kwargs) -> dict:
    phone=resolve_contact(contact_name)
    return {"ready":bool(phone),"contact":contact_name,"phone":phone,"message":message}

def draft_whatsapp(contact_name: str, message: str, **kwargs) -> dict:
    return prepare_whatsapp_message(contact_name,message,**kwargs)

def send_whatsapp_approved(contact_name: str, message: str, confirm: bool=False, **kwargs):
    if not confirm:
        return {"confirmation_required":True,"contact":contact_name}
    return send_whatsapp(contact_name,message)

def execute_whatsapp_send(**kwargs):
    return send_whatsapp_approved(**kwargs)

def check_messaging_status() -> dict:
    configured=bool((getattr(config,"WHATSAPP_ACCESS_TOKEN","") and getattr(config,"WHATSAPP_PHONE_NUMBER_ID","")) if getattr(config,"WHATSAPP_PROVIDER","meta")=="meta" else getattr(config,"WHATSAPP_API_URL",""))
    return {"contacts_file":str(CONTACTS_FILE),"contacts_loaded":len(load_contacts()),"provider":getattr(config,"WHATSAPP_PROVIDER","meta"),"configured":configured,"browser_automation":False}
