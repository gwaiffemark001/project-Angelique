# skills/messaging/whatsapp_playwright.py
"""
Real WhatsApp automation using Playwright.
Two-step protocol: Draft → Confirm → Send (safety first)
"""
import asyncio
from pathlib import Path
from typing import Optional
from core import config

# Global state for message drafting
DRAFT_STATE = {
    "contact": None,
    "message": None,
    "is_ready_to_send": False
}

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
except ImportError:
    print("⚠️ [WhatsApp] Playwright not installed. Install: pip install playwright")
    async_playwright = None


async def initialize_whatsapp(headless: bool = False) -> tuple[Browser, BrowserContext, Page] | tuple[None, None, None]:
    """Initialize Playwright browser for WhatsApp Web."""
    if not async_playwright:
        return None, None, None
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            page = await context.new_page()
            
            # Navigate to WhatsApp Web
            await page.goto(config.WHATSAPP_WEB_URL, timeout=30000)
            
            # Wait for QR code or chat list
            print("📱 [WhatsApp] Please scan QR code or wait for login...")
            try:
                await page.wait_for_selector('[data-testid="chat-list-container"]', timeout=60000)
                print("✅ [WhatsApp] Successfully logged in!")
                return browser, context, page
            except Exception as e:
                print(f"⚠️ [WhatsApp] Login timeout: {e}")
                await browser.close()
                return None, None, None
    except Exception as e:
        print(f"❌ [WhatsApp] Initialization failed: {e}")
        return None, None, None


async def search_contact(page: Page, contact_name: str) -> bool:
    """Search for a contact in WhatsApp Web."""
    try:
        # Click search box
        search_box = await page.query_selector('[data-testid="search_input"]')
        if not search_box:
            return False
        
        await search_box.fill(contact_name)
        await page.wait_for_timeout(500)  # Let search results appear
        
        # Click first result
        chat_item = await page.query_selector('[data-testid="chat-list-item"]')
        if chat_item:
            await chat_item.click()
            return True
        
        return False
    except Exception as e:
        print(f"⚠️ [WhatsApp] Search failed: {e}")
        return False


async def draft_message(page: Page, message_text: str) -> bool:
    """Type message in message box (draft, don't send yet)."""
    try:
        # Find message input box
        msg_box = await page.query_selector('[data-testid="msg-input"]')
        if not msg_box:
            msg_box = await page.query_selector('div[contenteditable="true"]')
        
        if not msg_box:
            return False
        
        await msg_box.click()
        await msg_box.type(message_text, delay=50)  # Simulate human typing
        
        DRAFT_STATE["message"] = message_text
        print(f"📝 [WhatsApp] Message drafted: '{message_text[:50]}...'")
        return True
    except Exception as e:
        print(f"⚠️ [WhatsApp] Draft failed: {e}")
        return False


async def send_message(page: Page) -> bool:
    """Send the drafted message."""
    try:
        # Find and click send button
        send_button = await page.query_selector('[data-testid="send"]')
        if not send_button:
            # Alt: press Ctrl+Enter or look for other send button
            await page.press('[data-testid="msg-input"] div[contenteditable="true"]', "Control+Enter")
        else:
            await send_button.click()
        
        await page.wait_for_timeout(1000)  # Wait for message to send
        DRAFT_STATE["is_ready_to_send"] = False
        DRAFT_STATE["message"] = None
        print("✅ [WhatsApp] Message sent successfully!")
        return True
    except Exception as e:
        print(f"❌ [WhatsApp] Send failed: {e}")
        return False


async def whatsapp_send_2step(contact_name: str, message_text: str) -> dict:
    """
    Two-step WhatsApp send with confirmation:
    Step 1: Search contact + draft message
    Step 2: (Requires user confirmation) send message
    
    Returns dict with status and draft info.
    """
    if not async_playwright:
        return {
            "error": "Playwright not installed",
            "contact": contact_name,
            "message": message_text,
            "step": "initialization"
        }
    
    browser, context, page = None, None, None
    try:
        # Initialize browser
        browser, context, page = await initialize_whatsapp(headless=True)
        if not page:
            return {"error": "Failed to initialize WhatsApp Web", "step": "initialization"}
        
        # Step 1: Search contact
        found = await search_contact(page, contact_name)
        if not found:
            return {
                "error": f"Contact '{contact_name}' not found",
                "contact": contact_name,
                "step": "search"
            }
        
        # Step 2: Draft message (don't send yet)
        drafted = await draft_message(page, message_text)
        if not drafted:
            return {
                "error": "Failed to draft message",
                "contact": contact_name,
                "message": message_text,
                "step": "draft"
            }
        
        # Update global state for user confirmation
        DRAFT_STATE["contact"] = contact_name
        DRAFT_STATE["message"] = message_text
        DRAFT_STATE["is_ready_to_send"] = True
        
        return {
            "status": "DRAFT_READY",
            "contact": contact_name,
            "message": message_text[:100] + "..." if len(message_text) > 100 else message_text,
            "action": "awaiting_confirmation",
            "next": "Please confirm to send this message. Say 'send message' or 'confirm'."
        }
        
    except Exception as e:
        return {"error": f"Exception: {str(e)}", "step": "execution"}
    finally:
        if browser:
            await browser.close()


async def whatsapp_confirm_and_send() -> dict:
    """
    Step 2: User confirmed. Send the drafted message.
    Requires DRAFT_STATE to be populated from previous step.
    """
    if not DRAFT_STATE.get("is_ready_to_send"):
        return {
            "error": "No pending message to send. Use 'message X to Y' first.",
            "status": "NO_DRAFT"
        }
    
    if not async_playwright:
        return {"error": "Playwright not installed", "status": "INIT_FAILED"}
    
    browser, context, page = None, None, None
    try:
        # Re-initialize for sending
        browser, context, page = await initialize_whatsapp(headless=True)
        if not page:
            return {"error": "Failed to initialize WhatsApp Web for send", "step": "reinitialization"}
        
        # Search contact and draft again (in case of session reset)
        contact = DRAFT_STATE.get("contact")
        message = DRAFT_STATE.get("message")
        
        found = await search_contact(page, contact)
        if not found:
            return {"error": f"Could not find contact '{contact}' on retry", "step": "search"}
        
        drafted = await draft_message(page, message)
        if not drafted:
            return {"error": "Could not re-draft message", "step": "redraft"}
        
        # Send
        sent = await send_message(page)
        if sent:
            return {
                "status": "SUCCESS",
                "contact": contact,
                "message": message[:100] + "..." if len(message) > 100 else message,
                "action": "message_sent"
            }
        else:
            return {"error": "Send button click failed", "step": "send"}
            
    except Exception as e:
        return {"error": f"Exception during send: {str(e)}", "step": "execution"}
    finally:
        if browser:
            await browser.close()


def prepare_whatsapp_message_sync(contact_name: str, message_text: str) -> dict:
    """Synchronous wrapper for async draft."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    result = loop.run_until_complete(whatsapp_send_2step(contact_name, message_text))
    return result


def execute_whatsapp_send_sync() -> dict:
    """Synchronous wrapper for async send."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    result = loop.run_until_complete(whatsapp_confirm_and_send())
    return result
