# brain/cognitive_loop.py
import json
import re
import threading
from brain.llm_interface import query_llm, extract_json_from_text
from brain import memory_manager as memory_manager
from brain.memory_manager import save_fact_to_db
from brain.heuristic_engine import extract_command_heuristically
from core.tools import TOOL_REGISTRY, execute_tool
from skills.memory.memory_tools import recall_facts, get_top_memory_facts, train_angelique
from skills.conversation.chat_skill import (
    save_conversation as conv_save, recall as conv_recall,
    get_session_context as conv_context, summarize_context,
    remember as conv_remember, list_sessions as list_conversations, new_session,
    is_session_closed, get_conversation_history,
)


def review_market_opportunity(opportunity: dict) -> dict:
    """Ask Angelique's main loop to review a deterministic market candidate.

    The brain decides whether the candidate deserves a plan; the deterministic
    trading workflow remains responsible for prices, volume, margin, and safety.
    """
    from skills.trading_skill.journal import read_trades

    recent_trades = read_trades(limit=10)
    prompt = json.dumps({
        "internal_event": "market_opportunity_review",
        "instruction": "Review this candidate using prior trades. Reply with PLAN or WAIT first, then a concise reason. Do not invent prices or execute anything.",
        "candidate": opportunity,
        "recent_trades": recent_trades,
    }, default=str)
    response = run_cognitive_loop(prompt)
    decision = "PLAN" if response.strip().upper().startswith("PLAN") else "WAIT"
    return {"decision": decision, "response": response, "recent_trades": recent_trades}


def _is_short_followup_reply(user_input: str) -> bool:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return False
    if normalized in {"yes", "y", "no", "n", "sure", "ok", "okay", "please", "do it", "go ahead", "correct", "right"}:
        return True
    return len(normalized.split()) <= 3 and any(token in normalized for token in {"yes", "no", "sure", "ok", "okay"})


def _build_messages_with_history(system_prompt: str, user_input: str, session_id: str | None = None) -> list[dict]:
    messages = [{"role": "system", "content": system_prompt}]
    try:
        session_key = session_id or "default"
        entries = get_conversation_history(session_key, limit=6)
        if entries:
            for entry in entries[-4:]:
                user_text = entry.get("user", "")
                agent_text = entry.get("agent", "")
                if isinstance(user_text, str) and user_text and user_text != user_input:
                    messages.append({"role": "user", "content": user_text})
                if isinstance(agent_text, str) and agent_text and agent_text != user_input:
                    messages.append({"role": "assistant", "content": agent_text})
    except Exception:
        pass
    messages.append({"role": "user", "content": user_input})
    return messages


def _is_followup_continuation(user_input: str) -> bool:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return False
    if _is_short_followup_reply(normalized):
        return True

    continuation_prefixes = ("verify", "confirm", "check", "continue", "proceed", "go ahead")
    if any(normalized.startswith(prefix) for prefix in continuation_prefixes):
        return True

    continuation_phrases = (
        "then continue",
        "continue executing",
        "continue with it",
        "continue with that",
        "continue the request",
        "verify that",
        "make sure",
        "double check",
    )
    return any(phrase in normalized for phrase in continuation_phrases)


def _is_retry_request(user_input: str) -> bool:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return False
    retry_phrases = (
        "try again",
        "retry",
        "do it again",
        "run it again",
        "same again",
        "again",
        "another attempt",
        "one more time",
    )
    return any(phrase == normalized or normalized.startswith(f"{phrase} ") for phrase in retry_phrases)


def _is_reexplain_request(user_input: str) -> bool:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return False
    return bool(re.search(r"\b(reexplain|re-explain|explain again|say that again|say it again|repeat that|repeat it)\b", normalized))


def _extract_reexplain_subject(user_input: str) -> str:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return ""

    normalized = normalized.replace("re-explain", "reexplain")
    patterns = [
        r"\breexplain\b(?:\s+(.*))?$",
        r"\bexplain again\b(?:\s+(.*))?$",
        r"\bsay that again\b(?:\s+(.*))?$",
        r"\bsay it again\b(?:\s+(.*))?$",
        r"\brepeat that\b(?:\s+(.*))?$",
        r"\brepeat it\b(?:\s+(.*))?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            subject = (match.group(1) or "").strip(" .?!")
            subject = subject.strip()
            if not subject:
                return ""
            if subject in {"please", "now", "again", "that", "it", "this", "more", "just", "please now", "please again"}:
                return ""
            return subject
    return ""


def _assistant_is_waiting_for_followup(last_response: str) -> bool:
    normalized = (last_response or "").strip().lower()
    if not normalized:
        return False
    question_mark = "?" in normalized
    followup_phrases = (
        "would you like",
        "do you want",
        "should i",
        "shall i",
        "can i",
        "would you like me",
        "do you want me",
        "want me to",
        "need me to",
    )
    return question_mark or any(phrase in normalized for phrase in followup_phrases)


def _is_identity_question(user_input: str) -> bool:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return False
    # Use configurable identity phrases from core.config to avoid hard-coded literals.
    try:
        from core import config as _config
        phrases = getattr(_config, "IDENTITY_QUESTION_PHRASES", [])
    except Exception:
        phrases = []
    if phrases:
        return any(phrase in normalized for phrase in phrases)
    # Fallback to legacy regex patterns if config wasn't available.
    legacy_patterns = [
        r"\bwhat\s+is\s+your\s+name\b",
        r"\bwho\s+are\s+you\b",
        r"\bwhat\s+are\s+you\b",
        r"\bwhat\s+is\s+your\s+identity\b",
        r"\bwhat\s+should\s+i\s+call\s+you\b",
    ]
    return any(re.search(pattern, normalized) for pattern in legacy_patterns)


def _looks_like_action_request(user_input: str) -> bool:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return False
    action_prefixes = (
        "open", "close", "launch", "start", "stop", "create", "make", "delete", "remove",
        "move", "rename", "save", "write", "search", "find", "check", "show", "list",
        "run", "execute", "use", "call", "invoke", "send", "text", "message", "toggle",
        "copy", "install", "uninstall", "browse", "look", "speak", "play"
    )
    if normalized.startswith(action_prefixes):
        return True
    return bool(re.search(r"\b(?:please|now|for me|on the desktop|on my computer|on whatsapp|in the browser)\b", normalized))


def resolve_user_query(user_input: str, session_id: str | None = None) -> dict:
    """High-level coordinated query resolver.

    Steps:
    1. "Think": silently extract facts from the user's input and persist them.
    2. Check conversation memory when appropriate.
    3. Check fact/knowledge memory when appropriate.
    4. Use the LLM to decide whether to answer naturally or issue a tool request.
    5. Persist any new facts discovered from external answers.

    Returns a dict with keys: `source` (one of 'conversation','fact','tool','llm'), `answer`, and `details`.
    """
    text = _strip_training_mode_prefix(user_input)

    

    # 0) Deterministic heuristic routing: try to map to a tool BEFORE calling any LLM.
    try:
        h_tool, h_args = nlp_to_tool_mapping(text)
        if h_tool:
            try:
                tool_result = execute_tool(h_tool, h_args or {})
            except Exception as e:
                tool_result = f"Error executing {h_tool}: {e}"
            try:
                conv_save(session_id, user_input, tool_result)
            except Exception:
                pass
            return {"source": "tool", "answer": tool_result, "details": {"tool": h_tool, "args": h_args}}
    except Exception:
        # If heuristic routing fails, continue to LLM-driven paths below.
        pass

    # If the input looks like an action and heuristics didn't match, map common
    # package manager install/uninstall intents to `run_shell_command` so the
    # skill executes rather than falling back to an LLM conversational reply.
    try:
        if _looks_like_action_request(text):
            lower = (text or "").strip().lower()
            # package manager install/uninstall fallbacks
            m_un = re.search(r"\b(?:uninstall|remove)\s+([a-z0-9_\-\.]+)", lower)
            if m_un:
                pkg = m_un.group(1)
                cmd = f"sudo apt remove {pkg}"
                try:
                    tool_result = execute_tool('run_shell_command', {'command': cmd})
                except Exception as e:
                    tool_result = f"Error executing shell command: {e}"
                try:
                    conv_save(session_id, user_input, tool_result)
                except Exception:
                    pass
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'run_shell_command', 'args': {'command': cmd}}}

            m_inst = re.search(r"\binstall\s+([a-z0-9_\-\.]+)", lower)
            if m_inst:
                pkg = m_inst.group(1)
                cmd = f"sudo apt install {pkg}"
                try:
                    tool_result = execute_tool('run_shell_command', {'command': cmd})
                except Exception as e:
                    tool_result = f"Error executing shell command: {e}"
                try:
                    conv_save(session_id, user_input, tool_result)
                except Exception:
                    pass
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'run_shell_command', 'args': {'command': cmd}}}
    except Exception:
        pass

    # Comprehensive deterministic mappings for action-like phrases.
    # These ensure tool dispatch before LLM fallback for higher reliability.
    try:
        lower = (text or "").strip().lower()

        # ========== MESSAGING / WHATSAPP ==========
        msg_patterns = [
            (r"\b(?:send|message|text|whatsapp|msg)\s+(.+?)\s+(?:to|to:)\s+(.+?)(?:\s+(?:on|via|through|using))?\s*$", lambda m: (m.group(2).strip(), m.group(1).strip())),
            (r"\b(?:tell|message|text|say)\s+(.+?)\s+(?:that|this):\s+(.+)$", lambda m: (m.group(1).strip(), m.group(2).strip())),
            (r"\b(?:message|text|whatsapp)\s+(.+?)\s+with\s+(.+)$", lambda m: (m.group(1).strip(), m.group(2).strip())),
            (r"\b(?:send|write)\s+a\s+(?:message|text)\s+to\s+(.+?)\s+(?:saying|with):\s+(.+)$", lambda m: (m.group(1).strip(), m.group(2).strip())),
            (r"\b(?:text)\s+(.+?)\s+([\w\s]+?)(?:\s+(?:this|saying|with))?\s*$", lambda m: (m.group(1).strip(), m.group(2).strip())),
        ]
        for pattern, extractor in msg_patterns:
            m = re.search(pattern, lower)
            if m:
                contact, msg = extractor(m)
                try:
                    tool_result = execute_tool('send_whatsapp', {'contact_name': contact, 'message': msg})
                except Exception as e:
                    tool_result = f"Error sending WhatsApp: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'send_whatsapp', 'args': {'contact_name': contact, 'message': msg}}}

        # ========== IMAGE GENERATION ==========
        img_patterns = [
            (r"\b(?:generate|create|make|draw|render|paint|sketch|illustrate|visualize)\s+(?:an?|the)?\s*image\s+(?:of\s+)?(.+?)(?: (\d{2,4}x\d{2,4}))?$", lambda m: (m.group(1).strip(), m.group(2))),
            (r"\bimage\s+of\s+(.+?)(?: (\d{2,4}x\d{2,4}))?$", lambda m: (m.group(1).strip(), m.group(2))),
            (r"\b(?:paint|sketch|illustrate|visualize|draw|render)\s+(?:an?|the)?\s*(.+?)(?: (\d{2,4}x\d{2,4}))?$", lambda m: (m.group(1).strip(), m.group(2))),
        ]
        for pattern, extractor in img_patterns:
            m = re.search(pattern, lower)
            if m:
                prompt, size = extractor(m)
                try:
                    tool_result = execute_tool('generate_image', {'prompt': prompt, 'size': size})
                except Exception as e:
                    tool_result = f"Error generating image: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'generate_image', 'args': {'prompt': prompt, 'size': size}}}

        # ========== VOICE / SPEECH / TTS ==========
        speak_patterns = [
            r"\b(?:say|speak|announce|read|tell|pronounce)\s+(.+)$",
            r"\b(?:voice|tts|text.?to.?speech)\s+(.+)$",
            r"\b(?:voice|say):\s*(.+)$",
            r"speak:\s*(.+)$",
        ]
        for pattern in speak_patterns:
            m = re.search(pattern, lower)
            if m:
                phrase = m.group(1).strip().strip('"\'')
                try:
                    tool_result = execute_tool('speak', {'text': phrase})
                except Exception:
                    tool_result = execute_tool('call_skill', {'skill_name': 'skills.voice.voice_interface.speak', 'args': {'text': phrase}})
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'speak', 'args': {'text': phrase}}}

        # ========== FILE OPERATIONS ==========
        # Open/Read file
        file_patterns = [
            (r"\b(?:open|show|display|view|read|cat)\s+([\w\-\.\~/:\\]+\.[a-z0-9]+)\b", 'open'),
            (r"\b(?:open|show|view|preview)\s+the?\s+file\s+([\w\-\.\~/:\\]+)\b", 'open'),
        ]
        for pattern, action in file_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                fp = m.group(1).strip()
                try:
                    tool_result = execute_tool('cli_open' if action == 'open' else 'cli_cat', {'file_path': fp})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'cli_open', 'args': {'file_path': fp}}}

        # List/Show directory
        list_patterns = [
            r"\b(?:what files are in|show me (?:the )?files in|list files in|ls|dir|list)\s+(.+)$",
            r"\b(?:show|display|list)\s+(?:the )?(?:contents|files|contents of|directory|folder)\s+(.+)$",
            r"\b(?:what|what is)\s+in\s+(.+?)(?:\s+folder|\s+directory)?$",
        ]
        for pattern in list_patterns:
            m = re.search(pattern, lower)
            if m:
                path = m.group(1).strip()
                try:
                    tool_result = execute_tool('list_directory', {'path': path})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'list_directory', 'args': {'path': path}}}

        # Create folder/directory
        mkdir_patterns = [
            r"\b(?:create|make|new|mkdir)\s+(?:a\s+)?(?:folder|directory|dir)\s+(?:named|called)?\s*([\w\-\. ]+)\b",
            r"\b(?:create|make)\s+directory\s+([\w\-\. ]+)\b",
            r"\bnew\s+folder:\s*([\w\-\. ]+)\b",
        ]
        for pattern in mkdir_patterns:
            m = re.search(pattern, lower)
            if m:
                folder = m.group(1).strip().replace(' ', '_')
                try:
                    tool_result = execute_tool('manage_files', {'action': 'mkdir', 'path': folder})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'manage_files', 'args': {'action': 'mkdir', 'path': folder}}}

        # Delete/Remove file
        delete_patterns = [
            r"\b(?:delete|remove|rm|erase|trash)\s+(?:file\s+)?([\w\-\.\~/:\\]+)\b",
            r"\b(?:delete|remove)\s+(?:the )?(?:file|folder|directory)\s+([\w\-\.\~/:\\]+)\b",
        ]
        for pattern in delete_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                fp = m.group(1).strip()
                try:
                    tool_result = execute_tool('manage_files', {'action': 'delete', 'path': fp})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'manage_files', 'args': {'action': 'delete', 'path': fp}}}

        # Move/Rename file
        move_patterns = [
            r"\b(?:move|rename|mv)\s+([\w\-\.\~/:\\]+)\s+(?:to|into|as)\s+([\w\-\.\~/:\\]+)\b",
            r"\b(?:move|rename)\s+(?:file\s+)?([\w\-\.\~/:\\]+)\s+to\s+([\w\-\.\~/:\\]+)\b",
            r"\b(?:rename)\s+([\w\-\.\~/:\\]+)\s+([\w\-\.\~/:\\]+)\b",
        ]
        for pattern in move_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                src, dst = m.group(1).strip(), m.group(2).strip()
                try:
                    tool_result = execute_tool('manage_files', {'action': 'move', 'path': src, 'new_path': dst})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'manage_files', 'args': {'action': 'move', 'path': src, 'new_path': dst}}}

        # Copy file
        copy_patterns = [
            r"\b(?:copy|cp|duplicate|backup)\s+([\w\-\.\~/:\\]+)\s+(?:to|into|as)\s+([\w\-\.\~/:\\]+)\b",
            r"\b(?:copy|duplicate)\s+(?:file\s+)?([\w\-\.\~/:\\]+)\s+to\s+([\w\-\.\~/:\\]+)\b",
        ]
        for pattern in copy_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                src, dst = m.group(1).strip(), m.group(2).strip()
                try:
                    tool_result = execute_tool('manage_files', {'action': 'copy', 'path': src, 'new_path': dst})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'manage_files', 'args': {'action': 'copy', 'path': src, 'new_path': dst}}}

        # ========== APP/PROGRAM LAUNCHING ==========
        app_patterns = [
            r"\b(?:open|launch|start|run|execute|begin)\s+(?:the\s+)?([a-z0-9\-_ ]+?)(?:\s+(?:app|application|program))?\b",
            r"\b(?:open|launch|start)\s+([a-z0-9\-_ ]+?)$",
        ]
        for pattern in app_patterns:
            m = re.search(pattern, lower)
            if m:
                app = m.group(1).strip()
                if app not in {'file', 'folder', 'directory', 'terminal', 'browser', 'chrome', 'firefox', 'code', 'editor'} and not any(x in app for x in {'the', 'a ', 'an '}):
                    try:
                        tool_result = execute_tool('open_app', {'app_name': app})
                    except Exception as e:
                        tool_result = f"Error: {e}"
                    conv_save(session_id, user_input, tool_result)
                    return {"source": "tool", "answer": tool_result, "details": {"tool": 'open_app', 'args': {'app_name': app}}}

        # ========== SYSTEM CHECKS & MONITORING ==========
        if re.search(r"\b(?:check|get|show|what)\b.*\b(?:status|health|performance|metrics|pc|system|computer)\b", lower):
            try:
                tool_result = execute_tool('get_system_health', {})
            except Exception as e:
                tool_result = f"Error: {e}"
            conv_save(session_id, user_input, tool_result)
            return {"source": "tool", "answer": tool_result, "details": {"tool": 'get_system_health'}}

        # ========== WEB SEARCH ==========
        if re.search(r"\b(?:search|google|find|look\s+up|research|query)\s+(?:for\s+|about\s+)?(.+)", lower):
            m = re.search(r"\b(?:search|google|find|look\s+up|research|query)\s+(?:for\s+|about\s+)?(.+)", lower)
            if m:
                query = m.group(1).strip()
                try:
                    tool_result = execute_tool('search_web', {'query': query})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'search_web', 'args': {'query': query}}}

        # ========== MEMORY / RECALL ==========
        if re.search(r"\b(?:recall|remember|tell me about|remind me|what do you know about)\b", lower):
            m = re.search(r"\b(?:recall|remember|tell me about|remind me|what do you know about)\s+(.+)$", lower)
            if m:
                query = m.group(1).strip()
                try:
                    tool_result = execute_tool('recall_memory', {'query': query})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'recall_memory', 'args': {'query': query}}}

        # ========== SAVE/STORE MEMORY ==========
        if re.search(r"\b(?:remember|save|store|note|log|record)\s+(?:that|this|my)\b", lower):
            try:
                tool_result = execute_tool('save_memory', {'person': 'User', 'key': 'note', 'value': text})
            except Exception as e:
                tool_result = f"Error: {e}"
            conv_save(session_id, user_input, tool_result)
            return {"source": "tool", "answer": tool_result, "details": {"tool": 'save_memory'}}

        # ========== PDF CREATION ==========
        pdf_patterns = [
            r"\b(?:save|create|generate|make|write|export)\s+(?:as\s+)?(?:pdf|\.pdf|to pdf|a pdf|a pdf file)\b",
            r"\b(?:convert|turn)\s+(?:this|into)\s+(?:pdf|\.pdf)\b",
        ]
        if any(re.search(p, lower) for p in pdf_patterns):
            try:
                tool_result = execute_tool('save_text_pdf', {'path': '/tmp/document.pdf', 'text': text})
            except Exception as e:
                tool_result = f"Error: {e}"
            conv_save(session_id, user_input, tool_result)
            return {"source": "tool", "answer": tool_result, "details": {"tool": 'save_text_pdf'}}

        # ========== VISION / SCREENSHOT ==========
        screenshot_patterns = [
            r"\b(?:screenshot|screen capture|screenshot of|capture screen|take a screenshot|read screen|show screen|snap screen|grab screen|shot|sc)\b",
        ]
        if any(re.search(p, lower) for p in screenshot_patterns):
            try:
                tool_result = execute_tool('read_screen', {})
            except Exception as e:
                tool_result = f"Error: {e}"
            conv_save(session_id, user_input, tool_result)
            return {"source": "tool", "answer": tool_result, "details": {"tool": 'read_screen'}}

        # ========== CAMERA / VISION ==========
        camera_patterns = [
            r"\b(?:camera|webcam|analyze camera|see|what.*?see|capture photo|take photo|webcam feed)\b",
        ]
        if any(re.search(p, lower) for p in camera_patterns):
            try:
                tool_result = execute_tool('analyze_camera', {})
            except Exception as e:
                tool_result = f"Error: {e}"
            conv_save(session_id, user_input, tool_result)
            return {"source": "tool", "answer": tool_result, "details": {"tool": 'analyze_camera'}}

        # ========== INSTALLATION CHECKING ==========
        install_check_patterns = [
            r"\b(?:is|are)\s+(.+?)\s+installed\b",
            r"\b(?:check|verify|confirm)\s+(?:if\s+)?(.+?)\s+(?:is\s+)?installed\b",
            r"\b(?:do i have|did i install|is there)\s+(.+?)\b",
        ]
        for pattern in install_check_patterns:
            m = re.search(pattern, lower)
            if m:
                target = m.group(1).strip()
                try:
                    tool_result = execute_tool('check_installation_status', {'target_name': target})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'check_installation_status', 'args': {'target_name': target}}}

        # ========== TRADING / MARKET ==========
        trading_patterns = [
            r"\b(?:analyze|check|show|get)\s+(?:market|forex|stock|crypto)\s+(.+?)(?:\s+(?:chart|analysis|price|trend))?\b",
            r"\b(?:chart|candle|candlestick|rsi|ema|moving average)\s+(.+?)\b",
            r"\b(?:price|quote|rate|value)\s+(?:of\s+)?(.+?)\b",
            r"\b(?:eurusd|gbpusd|usdjpy|btc|eth|gold)\b",
        ]
        for pattern in trading_patterns:
            m = re.search(pattern, lower)
            if m and m.groups():
                symbol = m.group(1).strip().upper()
                try:
                    tool_result = execute_tool('analyze_market_and_recommend', {'symbol': symbol, 'risk_percent': 1.0})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'analyze_market_and_recommend'}}

        # ========== FOREX/MARKET NEWS ==========
        if re.search(r"\b(?:news|market news|forex news|economic news|events|calendar)\b", lower):
            try:
                tool_result = execute_tool('get_forex_news', {'symbol': None})
            except Exception as e:
                tool_result = f"Error: {e}"
            conv_save(session_id, user_input, tool_result)
            return {"source": "tool", "answer": tool_result, "details": {"tool": 'get_forex_news'}}

        # ========== LIST APPS / SOFTWARE ==========
        if re.search(r"\b(?:list|show|what)\s+(?:apps|applications|programs|installed software|software)\b", lower):
            try:
                tool_result = execute_tool('list_apps', {})
            except Exception as e:
                tool_result = f"Error: {e}"
            conv_save(session_id, user_input, tool_result)
            return {"source": "tool", "answer": tool_result, "details": {"tool": 'list_apps'}}

        # ========== SKILL GENERATION & CODE ==========
        skill_patterns = [
            r"\b(?:generate|create|make|write|code|build)\s+(?:a\s+)?(?:script|code|skill|tool|function)\s+(?:to|that|for)?\s+(.+)$",
            r"\b(?:can you|please|write a script|generate code)\s+(?:to\s+)?(.+)\b",
        ]
        for pattern in skill_patterns:
            m = re.search(pattern, lower)
            if m:
                instruction = m.group(1).strip()
                try:
                    tool_result = execute_tool('create_and_execute_skill', {'instruction': instruction})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'create_and_execute_skill'}}

        # ========== CONSOLE / TERMINAL COMMANDS ==========
        if re.search(r"\b(?:run|execute|bash|shell|cmd|command|powershell)\s+(.+)$", lower):
            m = re.search(r"\b(?:run|execute|bash|shell|cmd|command|powershell)\s+(.+)$", lower)
            if m:
                cmd = m.group(1).strip()
                try:
                    tool_result = execute_tool('run_shell_command', {'command': cmd})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'run_shell_command'}}

    except Exception:
        pass
    except Exception:
        pass

    with _REQUEST_LOCK:
        # 1) Think: silently extract facts and persist them for non-action requests
        try:
            if not _looks_like_action_request(text):
                extract_facts_silently(text)
        except Exception:
            pass

    # 2) Conversation memory check
    if _should_query_conversation_memory(text):
        conv_hits = memory_manager.query_conversation_memory(text, top_k=5)
        if conv_hits:
            return {"source": "conversation", "answer": conv_hits, "details": {"count": len(conv_hits)}}

    # 3) Fact memory check
    if _should_query_memory(text):
        fact_hits = memory_manager.query_fact_memory(text, top_k=5)
        if fact_hits:
            return {"source": "fact", "answer": fact_hits, "details": {"count": len(fact_hits)}}

    # 4) Fall back to external models / LLMs. Use orchestration selectively.
    try:
        if _should_use_orchestration(text):
            orchestration = orchestrate_models(text, session_id=session_id)
            final_answer = orchestration.get("final_answer") if isinstance(orchestration, dict) else orchestration

            # If the orchestration output contains a tool request, execute it.
            tool_name = None
            args = {}
            if isinstance(final_answer, str):
                decision = extract_json_from_text(final_answer)
                if isinstance(decision, dict) and decision:
                    if "tool" in decision:
                        tool_name = decision["tool"]
                        args = decision.get("args", {})
                    else:
                        for t in TOOL_REGISTRY.keys():
                            if t in decision:
                                tool_name = t
                                args = decision[t]
                                break
                else:
                    refined_decision, clarified_response = _extract_tool_decision(final_answer, text, session_id=session_id)
                    if isinstance(refined_decision, dict) and refined_decision:
                        if "tool" in refined_decision:
                            tool_name = refined_decision["tool"]
                            args = refined_decision.get("args", {})
                        else:
                            for t in TOOL_REGISTRY.keys():
                                if t in refined_decision:
                                    tool_name = t
                                    args = refined_decision[t]
                                    break
                    elif clarified_response is not None:
                        final_answer = clarified_response

            if args is None:
                args = {}
            if not isinstance(args, dict):
                args = {}

            if tool_name:
                # Let execute_tool handle alias mapping and skill discovery/fallbacks.
                tool_result = execute_tool(tool_name, args)
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": tool_name, "args": args}}

            # If orchestration didn't yield a tool decision, try deterministic heuristics
            if not tool_name:
                try:
                    # first try mapping from the original user input
                    h_tool, h_args = nlp_to_tool_mapping(text)
                    if not h_tool:
                        # then try mapping from the LLM raw response
                        h_tool, h_args = nlp_to_tool_mapping(final_answer or "")
                    if h_tool:
                        tool_name = h_tool
                        args = h_args or {}
                except Exception:
                    pass

            # Save any extracted facts from the final answer silently
            try:
                extract_facts_silently(final_answer)
            except Exception:
                pass
            details = orchestration.get("details", {}) if isinstance(orchestration, dict) else {}
            details["orchestrated"] = True
            # If we found a tool via heuristics above, execute it; otherwise return LLM answer
            if tool_name:
                tool_result = execute_tool(tool_name, args or {})
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": tool_name, "args": args}}
            return {"source": "llm", "answer": final_answer, "details": details}
        else:
            # Single-pass lightweight LLM call for simple queries
            response = query_llm(_build_messages_with_history(
                "You are Angelique. Answer the user's request naturally and keep recent conversation context in mind.",
                text,
                session_id=session_id,
            ), temperature=0.2)
            if response is None:
                return {"source": "llm", "answer": "I'm having a little trouble connecting to my brain right now.", "details": {"orchestrated": False}}

            decision = extract_json_from_text(response)
            tool_name = None
            args = {}
            if isinstance(decision, dict) and decision:
                if "tool" in decision:
                    tool_name = decision["tool"]
                    args = decision.get("args", {})
                else:
                    for t in TOOL_REGISTRY.keys():
                        if t in decision:
                            tool_name = t
                            args = decision[t]
                            break
            else:
                    refined_decision, clarified_response = _extract_tool_decision(response, text, session_id=session_id)
                    if isinstance(refined_decision, dict) and refined_decision:
                        if "tool" in refined_decision:
                            tool_name = refined_decision["tool"]
                            args = refined_decision.get("args", {})
                        else:
                            for t in TOOL_REGISTRY.keys():
                                if t in refined_decision:
                                    tool_name = t
                                    args = refined_decision[t]
                                    break
                    elif clarified_response is not None:
                        response = clarified_response
            if args is None:
                args = {}
            if not isinstance(args, dict):
                args = {}

            if tool_name and tool_name in TOOL_REGISTRY:
                tool_result = execute_tool(tool_name, args)
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": tool_name, "args": args}}

            try:
                extract_facts_silently(response)
            except Exception:
                pass
            return {"source": "llm", "answer": response, "details": {"orchestrated": False}}
    except Exception as e:
        return {"source": "error", "answer": None, "details": {"error": str(e)}}


def _is_simple_question(user_input: str) -> bool:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return False

    words = re.findall(r"\b[\w']+\b", normalized)
    if len(words) > 14:
        return False

    question_prefixes = (
        "what",
        "who",
        "where",
        "when",
        "why",
        "how",
        "did",
        "does",
        "is",
        "are",
        "can",
        "could",
        "would",
        "should",
        "will",
    )

    if normalized.endswith("?"):
        return True
    if words and words[0] in question_prefixes:
        return True

    return False


def _should_query_memory(user_input: str) -> bool:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return False
    if _is_identity_question(user_input) or _is_simple_question(user_input):
        return False

    try:
        from core import config as _config
        memory_trigger_phrases = getattr(_config, "MEMORY_TRIGGER_PHRASES", [])
    except Exception:
        memory_trigger_phrases = []

    if memory_trigger_phrases and any(phrase in normalized for phrase in memory_trigger_phrases):
        return True

    # Fallback token check
    personal_tokens = ("my", "me", "mine", "your", "name", "favorite", "favourite", "remember", "recall")
    return any(token in normalized for token in personal_tokens)


def _should_query_conversation_memory(user_input: str) -> bool:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return False

    conversation_phrases = (
        "what did i tell you",
        "what did i say",
        "do you remember",
        "remember when",
        "something i said",
        "as we discussed",
        "as you said",
        "conversation",
        "chat",
    )
    return any(phrase in normalized for phrase in conversation_phrases)


def _strip_training_mode_prefix(user_input: str) -> str:
    text = (user_input or "").strip()
    if not text:
        return ""
    prefix_patterns = [
        r"^\s*\[\[TRAINING_MODE\]\]\s*",
        r"^\s*TRAINING MODE:\s*",
        r"^\s*TRAINING:\s*",
    ]
    for pattern in prefix_patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text.strip()


def _is_training_intent(user_input: str) -> bool:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return False

    if "[[training_mode]]" in normalized or "training mode:" in normalized or normalized.startswith("training:"):
        return True

    if normalized.endswith("?"):
        return False

    try:
        from core import config as _config
        training_terms = getattr(_config, "TRAINING_DIRECTIVE_MARKERS", [])
    except Exception:
        training_terms = []

    if training_terms and any(term in normalized for term in training_terms):
        return True

    # Fallback heuristic markers (legacy)
    directive_markers = (
        "my name is",
        "my primary trading platform is",
        "my maximum risk per trade is",
        "my absolute maximum risk per trade is",
        "my minimum risk to reward ratio",
        "i never enter a trade without",
        "i do not trade",
        "you must always",
        "you should always",
        "you need to always",
        "you must",
        "you should",
        "you need to",
        "structured format",
        "trade recommendations",
        "explicit confirmation before executing any trade",
    )
    if any(marker in normalized for marker in directive_markers):
        return True
    return False

    return False

def nlp_to_tool_mapping(text: str):
    """
    Comprehensive deterministic routing using heuristic engine.
    Replaces partial hardcoded mappings with full coverage.
    """
    try:
        from core import config as _cfg
        _debug = bool(getattr(_cfg, 'DEBUG_HEURISTICS', False))
    except Exception:
        _debug = False

    tool_name, args = extract_command_heuristically(text)
    if _debug:
        print(f"🔍 [NL2TOOL] input='{text}' -> tool='{tool_name}' args={args}")
    return tool_name, args

def _looks_like_general_query(user_input: str) -> bool:
    normalized = (user_input or "").strip().lower()
    if not normalized:
        return True
    if normalized.endswith("?"):
        return True
    words = re.findall(r"\b[\w']+\b", normalized)
    if len(words) <= 2:
        return True
    question_starters = ("what ", "who ", "when ", "where ", "why ", "how ", "do ", "does ", "did ", "is ", "are ", "can ", "could ", "would ", "should ", "will ")
    return normalized.startswith(question_starters)


_REQUEST_LOCK = threading.Lock()

def _should_use_orchestration(user_input: str) -> bool:
    """Decide whether to run multi-LLM orchestration for a given input.

    Heuristics:
    - Disabled via `core.config.ENABLE_MULTI_LLM_ORCHESTRATION`.
    - Never for identity, simple questions, or explicit action requests.
    - Use for inputs with at least `ORCHESTRATION_MIN_WORDS` words or containing
      one of the `ORCHESTRATION_KEYWORDS`.
    """
    try:
        from core import config as _config
        enabled = getattr(_config, "ENABLE_MULTI_LLM_ORCHESTRATION", True)
        min_words = int(getattr(_config, "ORCHESTRATION_MIN_WORDS", 8))
        keywords = list(getattr(_config, "ORCHESTRATION_KEYWORDS", [
            "explain", "compare", "analyze", "evaluate", "why", "how", "recommend", "design", "strategy",
        ]))
    except Exception:
        enabled = True
        min_words = 8
        keywords = ["explain", "compare", "analyze", "evaluate", "why", "how", "recommend", "design", "strategy"]

    if not enabled:
        return False

    if not user_input or not user_input.strip():
        return False

    if _is_identity_question(user_input) or _is_simple_question(user_input) or _looks_like_action_request(user_input):
        return False

    words = re.findall(r"\b[\w']+\b", user_input)
    if len(words) >= min_words:
        return True

    normalized = user_input.lower()
    if any(k in normalized for k in keywords):
        return True

    return False


def _extract_tool_decision(raw_response: str, user_input: str, session_id: str | None = None) -> tuple[dict | None, str | None]:
    decision = extract_json_from_text(raw_response)
    if isinstance(decision, dict) and decision:
        return decision, None

    clarification_prompt = (
        "You are Angelique. The user may have requested an action. "
        "If the user wants to perform a tool action, respond with ONLY a single valid JSON object like ``{\"tool\": \"tool_name\", \"args\": { ... }}.`` "
        "If the user is asking a normal question or chatting, answer naturally without JSON. "
        f"User request: '{user_input}'\n"
        f"Previous assistant output: '{raw_response}'\n"
        "Return only valid JSON if an action is required, otherwise return a natural answer."
    )
    # Ensure the clarification pass contains the original user request explicitly
    clarification_messages = _build_messages_with_history(
        "You are a reasoning assistant tasked with producing a strict JSON tool request when appropriate.",
        user_input,
        session_id=session_id,
    )
    # Add the clarification prompt as an additional user message so the model sees both the original request and the clarification instructions
    clarification_messages.append({"role": "user", "content": clarification_prompt})
    clarified = query_llm(clarification_messages, temperature=0.0)

    refined = extract_json_from_text(clarified or "")
    if isinstance(refined, dict) and refined:
        return refined, None
    return None, clarified or None


def extract_facts_silently(user_input: str):
    """Silently extracts facts, scoring their emotional importance and episodic context."""
    if _looks_like_general_query(user_input):
        return

    extraction_prompt = (
        "You are a strict cognitive fact-extraction engine. Analyze the user's input below.\n"
        "Extract ALL facts about ANY person mentioned. Return ONLY a valid JSON list of objects.\n"
        "If there are no new facts to extract (e.g., the user is just asking a question), return EXACTLY: []\n\n"
        "STRICT RULES:\n"
        "- Output ONLY a JSON list. No markdown, no explanations.\n"
        "- Each object MUST have exactly five keys: 'person', 'key', 'value', 'importance', 'context'.\n"
        "- 'person': If about the speaker ('I', 'my'), set to 'User'. Otherwise, use their exact name.\n"
        "- 'key': A short, lowercase phrase (e.g., 'favorite dish', 'spouse name').\n"
        "- 'value': The specific detail. NEVER use empty strings.\n"
        "- 'importance': An integer from 1 to 10. \n"
        "   * 1-3: Trivial (e.g., favorite color, what they ate for lunch).\n"
        "   * 4-6: Normal (e.g., their job, their hobbies, a friend's name).\n"
        "   * 7-9: Highly Important (e.g., their spouse's name, a major life event, a medical condition).\n"
        "   * 10: Critical (e.g., life-threatening allergy, deep personal trauma, core life goal).\n"
        "- 'context': A very brief (3-5 words) description of the situation (e.g., 'talking about weekend', 'discussing work').\n\n"
        f"User input: '{user_input}'"
    )
    
    try:
        raw_content = query_llm([{"role": "user", "content": extraction_prompt}], temperature=0.0)
        if raw_content is None:
            print("⚠️ [DEBUG] Silent extraction skipped: LLM returned None")
            return
            
        clean_content = raw_content.replace("```json", "").replace("```", "").strip()
        list_match = re.search(r'\[.*\]', clean_content, re.DOTALL)
        obj_match = re.search(r'\{.*\}', clean_content, re.DOTALL)
        json_str = list_match.group(0) if list_match else (obj_match.group(0) if obj_match else clean_content)
        
        facts = json.loads(json_str)
        facts_list = facts if isinstance(facts, list) else [facts]
        
        for item in facts_list:
            if isinstance(item, dict) and "person" in item and "key" in item:
                person = str(item.get("person", "User")).strip()
                key = str(item.get("key", "")).lower().strip()
                value = str(item.get("value", "")).strip()
                
                # Extract new emotional/episodic data
                importance = int(item.get("importance", 5))
                context = str(item.get("context", "")).strip()
                
                if not person or not key or value == "" or value.lower() == "unknown":
                    continue
                    
                key = key.replace(f"{person.lower()}'s ", "").replace("my ", "").replace("your ", "").strip()
                save_fact_to_db(person, key, value, importance, context)
                
                imp_emoji = "🔥" if importance >= 8 else "⭐" if importance >= 5 else "📌"
                print(f"🧠 [Memory Update] {imp_emoji} [{importance}/10] '{person}' / '{key}' = '{value}' (Context: {context})")
    except Exception as e:
        print(f"⚠️ [DEBUG] Silent extraction failed: {e}")


def orchestrate_models(user_text: str, session_id: str | None = None) -> dict:
    """Run a small ensemble of LLM passes to simulate chain-of-thought style reasoning.

    Passes:
    - thinker: ask for step-by-step reasoning and a provisional answer
    - critic: ask for critique of the provisional answer
    - synthesizer: produce a concise final answer using thinker+critic

    Returns a dict with `final_answer` and `details` containing each pass output.
    """
    if not user_text:
        return {"final_answer": "", "details": {}}

    details = {}
    try:
        # Thinker: ask for step-by-step reasoning
        thinker_prompt = _build_messages_with_history(
            "You are a careful step-by-step reasoning assistant. Show your chain-of-thought clearly, then provide a provisional answer.",
            f"Analyze and reason about the following request step-by-step, then give a provisional answer:\n\n{user_text}",
            session_id=session_id,
        )
        thinker_out = query_llm(thinker_prompt, temperature=0.2)
        details["thinker"] = thinker_out

        # Critic: ask another pass to critique the provisional answer
        critic_prompt = _build_messages_with_history(
            "You are a critical reviewer. Given a user's request and a provisional answer, point out mistakes, missing assumptions, and potential improvements.",
            f"User request:\n{user_text}\n\nProvisional answer:\n{thinker_out}\n\nProvide concise critique and corrections.",
            session_id=session_id,
        )
        critic_out = query_llm(critic_prompt, temperature=0.1)
        details["critic"] = critic_out

        # Synthesizer: produce final concise answer, considering thinker and critic
        synth_prompt = _build_messages_with_history(
            "You are an assistant that synthesizes multiple opinions into a clear final answer. Use the reasoning and criticism provided to produce a concise, actionable response.",
            f"User request:\n{user_text}\n\nReasoning (thinker):\n{thinker_out}\n\nCritique (critic):\n{critic_out}\n\nProduce a single final answer (no internal chain-of-thought).",
            session_id=session_id,
        )
        final_out = query_llm(synth_prompt, temperature=0.0)
        details["synthesizer"] = final_out

        return {"final_answer": final_out, "details": details}
    except Exception as e:
        return {"final_answer": f"Error composing answers: {e}", "details": {"error": str(e)}}

def run_cognitive_loop(user_input: str) -> str:
    session_id = "default"
    if is_session_closed(session_id):
        return "Angelique session has been closed."
    session_context = conv_context(session_id)
    last_response = session_context.get("last_response", "")
    last_user_input = session_context.get("last_user", "")
    if _is_retry_request(user_input) and last_user_input:
        user_input = last_user_input

    # Require explicit confirmation for potentially-destructive install/uninstall
    normalized = (user_input or "").strip().lower()
    if re.search(r"\binstall\b|\buninstall\b", normalized):
        # If the user asked as a question or requested instructions, allow normal flow
        if not normalized.endswith("?") and "how" not in normalized and "how to" not in normalized:
            # If there's no clear confirmation keyword, ask for clarification
            if not any(k in normalized for k in ("confirm", "perform", "yes", "do it", "proceed")):
                clarification = "Do you want me to perform this install/uninstall now? Reply 'yes' to proceed or 'instructions' for step-by-step guidance."
                conv_save(session_id, user_input, clarification)
                return clarification

    if _assistant_is_waiting_for_followup(last_response) and _is_followup_continuation(user_input):
        followup_prompt = (
            "You are Angelique continuing a previous exchange. The user has replied to your last question. "
            "Treat this as a continuation of the conversation, not a brand new command, unless the reply clearly introduces one. "
            "Answer naturally and stay within the context of the prior assistant message."
        )
        followup_messages = _build_messages_with_history(
            followup_prompt,
            user_input,
            session_id="default",
        )
        if last_response:
            followup_messages = [
                {"role": "system", "content": followup_prompt},
                {"role": "assistant", "content": last_response},
            ] + followup_messages[1:]
        followup_response = query_llm(followup_messages, temperature=0.2)
        final_response = followup_response or "I’m continuing from the previous point. What would you like me to do next?"
        conv_save(session_id, user_input, final_response)
        return final_response

    if _is_reexplain_request(user_input) and not _extract_reexplain_subject(user_input):
        clarification = "Sure, what exactly would you like me to reexplain?"
        conv_save(session_id, user_input, clarification)
        return clarification

    # Handle identity questions by consulting stored facts/conversation before asking external LLMs.
    if _is_identity_question(user_input):
        try:
            # 1) Check explicit fact memory for any 'name' facts
            # First, prefer deterministic SQLite facts for Assistant (avoid relying solely on vector search results).
            chosen = None
            try:
                assistant_facts = memory_manager.get_facts_for_entity('Assistant')
                current = assistant_facts.get('current', []) if isinstance(assistant_facts, dict) else []
                # Find any 'name' keys in Assistant facts
                assistant_name_candidates = [f for f in current if 'name' in str(f.get('key','')).lower() and f.get('value')]
                if assistant_name_candidates:
                    chosen = max(assistant_name_candidates, key=lambda x: int(x.get('importance', x.get('importance_score', 5))))
            except Exception:
                chosen = None

            # If no Assistant fact found in SQLite, fall back to semantic/vector fact search
            if not chosen:
                fact_hits = memory_manager.query_fact_memory("name", top_k=10)
                # Prefer facts whose key contains 'name' and highest importance
                assistant_priorities = [f for f in fact_hits if "name" in str(f.get("key", "")).lower() and str(f.get("entity", "")).lower() in ("assistant", "angelique")]
                if assistant_priorities:
                    chosen = max(assistant_priorities, key=lambda x: int(x.get("importance", 5)))
                else:
                    # Fallback to any 'name' facts sorted by importance
                    for f in sorted(fact_hits, key=lambda x: int(x.get("importance", 5)), reverse=True):
                        k = str(f.get("key", "")).lower()
                        v = f.get("value") or f.get("value", "")
                        if "name" in k and v:
                            chosen = f
                            break

            # 2) If none found, scan recent conversation for user-provided renaming statements
            if not chosen:
                history = conv_context(session_id)
                # inspect recent conversation file for lines where the user declared a name
                try:
                    from skills.conversation.chat_skill import get_conversation_history
                    hist = get_conversation_history(session_id, limit=30)
                    for entry in reversed(hist):
                        u = entry.get("user", "")
                        if isinstance(u, str) and "your name" in u.lower() or "you are" in u.lower() and "called" in u.lower():
                            # naive parse: extract last capitalized words
                            parts = re.findall(r"[A-Z][a-z]+(?:\s[A-Z][a-z]+)*", u)
                            if parts:
                                chosen = {"key": "new name", "value": parts[-1], "importance": 7, "entity": "User"}
                                break
                except Exception:
                    pass

            if chosen:
                name = chosen.get("value")
                resp = f"My name is {name}."
                conv_save(session_id, user_input, resp)
                return resp
            # No stored name found; let the normal reasoning path answer instead of forcing a prompt.
        except Exception:
            # fall through to normal handling if memory check fails
            pass

    if _is_training_intent(user_input):
        stripped_input = _strip_training_mode_prefix(user_input)
        training_response = train_angelique(stripped_input or user_input)
        conv_save(session_id, user_input, training_response)
        return training_response

    # 1. Silent memory extraction only for substantive, fact-bearing turns.
    if not _is_identity_question(user_input):
        extract_facts_silently(user_input)

    # Deterministic handlers for common system queries to avoid LLM hallucination
    normalized = (user_input or "").strip().lower()
    if re.search(r"\b(date|time|what's the time|what is the time)\b", normalized):
        from datetime import datetime
        now = datetime.now()
        resp = now.strftime("%A, %B %d, %Y %I:%M:%S %p")
        conv_save(session_id, user_input, resp)
        return resp

    if re.search(r"\b(system diagnostics|system diagnostics|system status|system configuration|system info|system diagnostic)\b", normalized):
        try:
            from skills.os_control.system_cmds import get_system_health
            info = get_system_health()
            resp = json.dumps(info, indent=2)
            conv_save(session_id, user_input, resp)
            return resp
        except Exception:
            pass

    # 2. Avoid preloading memory for plain questions. Let the model reason first,
    #    and only use memory later when the response clearly needs it.
    if _should_query_memory(user_input):
        memory_check = recall_facts(query=user_input)
        has_memory = "don't have any information" not in memory_check.lower() and "no new valid facts" not in memory_check.lower()
        memory_text = memory_check if has_memory else "None. You do not know this yet."
    else:
        memory_text = "None. You do not know this yet."

    top_memory_facts = get_top_memory_facts(min_importance=8, limit=6)
    if top_memory_facts:
        top_memory_lines = [
            f"- {fact['entity']} / {fact['key']} = {fact['value']} (importance {fact['importance']})"
            for fact in top_memory_facts
        ]
        training_memory_text = "CORE TRAINING MEMORY (high importance):\n" + "\n".join(top_memory_lines)
    else:
        training_memory_text = "CORE TRAINING MEMORY: None."

    tools_schema = json.dumps({name: info["description"] for name, info in TOOL_REGISTRY.items()}, indent=2)

    system_prompt = (
        "You are Angelique, a highly advanced, self-evolving autonomous AI companion.\n\n"
        f"You have access to the following tools:\n{tools_schema}\n\n"
        f"{training_memory_text}\n\n"
        f"RELEVANT MEMORY ABOUT THE USER (Sorted by emotional importance):\n{memory_text}\n\n"
        "CORE DIRECTIVES:\n"
        "1. Think carefully before you answer. Determine whether the user is asking a question or asking you to perform an action.\n"
        "2. If the user requests an action, respond with ONLY one JSON object: {\"tool\": \"tool_name\", \"args\": { ... }}.\n"
        "3. If the user is asking a question or having a conversation, answer naturally without JSON.\n"
        "4. Avoid hardcoded keyword matching; infer intent from the user's full request.\n"
        "5. Use the tool schema above to choose the best tool when an action is required.\n\n"
        "EXAMPLES:\n"
        "User: open Firefox\n"
        "Assistant: {\"tool\": \"open_app\", \"args\": {\"app_name\": \"Firefox\"}}\n\n"
        "User: uninstall cmatrix\n"
        "Assistant: {\"tool\": \"run_shell_command\", \"args\": {\"command\": \"apt-get remove cmatrix\"}}\n\n"
        "User: what is your name?\n"
        "Assistant: I am Angelique, your assistant. How can I help?\n"
    )

    recent_history = []
    try:
        history = conv_context(session_id)
        last_response = history.get("last_response", "")
        last_user = history.get("last_user", "")
        if last_user or last_response:
            recent_history.append({"role": "user", "content": last_user})
            recent_history.append({"role": "assistant", "content": last_response})
    except Exception:
        recent_history = []

    messages = _build_messages_with_history(system_prompt, user_input, session_id=session_id)
    # Ensure the current user input is present as the final user message
    try:
        if not any(m.get("role") == "user" and m.get("content") == user_input for m in messages):
            messages.append({"role": "user", "content": user_input})
    except Exception:
        messages.append({"role": "user", "content": user_input})

    raw_response = query_llm(messages, temperature=0.0)
    if raw_response is None:
        return "I'm having a little trouble connecting to my brain right now."

    decision = extract_json_from_text(raw_response)
    tool_name = None
    args = {}
    natural_answer = None

    # Handle LLM responses that return empty or invalid JSON
    if not decision or not isinstance(decision, dict) or len(decision) == 0:
        if _is_identity_question(user_input):
            conv_save(session_id, user_input, raw_response)
            return raw_response

        refined_decision, clarified_response = _extract_tool_decision(raw_response, user_input, session_id=session_id)
        if isinstance(refined_decision, dict) and len(refined_decision) > 0:
            decision = refined_decision
        elif clarified_response is not None:
            natural_answer = clarified_response

    if isinstance(decision, dict) and len(decision) > 0:
        if "tool" in decision:
            tool_name = decision["tool"]
            args = decision.get("args", {})
        else:
            for t in TOOL_REGISTRY.keys():
                if t in decision:
                    tool_name = t
                    args = decision[t]
                    break
    else:
        if not _is_identity_question(user_input):
            # Always attempt deterministic heuristic mapping from the user input
            # or the LLM raw response. This ensures retry requests still execute
            # previously-intended actions even when a clarified natural answer
            # was also produced by the LLM.
            tool_name, args = nlp_to_tool_mapping(user_input)
            if not tool_name:
                tool_name, args = nlp_to_tool_mapping(raw_response or "")

    # Ensure args is always a valid dict
    if args is None:
        args = {}
    if not isinstance(args, dict):
        args = {}

    if tool_name:
        print(f"🧠 [Thought] Using tool: {tool_name} with args {args}")
        tool_result = execute_tool(tool_name, args)
        print(f"🔍 [DEBUG] Tool Result: {repr(tool_result)}")
        # Persist the tool result in the conversation history
        conv_save(session_id, user_input, tool_result)
        # Prefer any clarified natural answer; otherwise return the tool result as a string
        if natural_answer is not None:
            return natural_answer
        return tool_result if isinstance(tool_result, str) else json.dumps(tool_result, ensure_ascii=False)

    final = natural_answer or raw_response
    conv_save(session_id, user_input, final)
    return final