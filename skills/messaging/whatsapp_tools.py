# skills/messaging/whatsapp_tools.py
from skills.messaging.whatsapp_playwright import prepare_whatsapp_message_sync, execute_whatsapp_send_sync

def prepare_whatsapp_message(contact_name: str, message: str) -> str:
    """
    STEP 1: Prepare message for WhatsApp send.
    Searches contact, types message, waits for confirmation.
    """
    result = prepare_whatsapp_message_sync(contact_name, message)
    
    if result.get("status") == "DRAFT_READY":
        return (
            f"📝 **Message to {result['contact']} ready to send:**\n"
            f"Message: \"{result['message']}\"\n"
            f"✋ AWAITING YOUR CONFIRMATION\n"
            f"Say 'send message' or 'confirm' to deliver."
        )
    elif "error" in result:
        return f"❌ WhatsApp Error: {result.get('error')}"
    else:
        return f"⚠️ Unexpected result: {result}"

def execute_whatsapp_send(contact_name: str = None, message: str = None) -> str:
    """
    STEP 2: Send the previously drafted message after user confirmation.
    """
    result = execute_whatsapp_send_sync()
    
    if result.get("status") == "SUCCESS":
        return f"✅ Message sent to {result['contact']}: \"{result['message']}\""
    elif "error" in result:
        return f"❌ Send Failed: {result.get('error')}"
    else:
        return f"⚠️ Unexpected result: {result}"
