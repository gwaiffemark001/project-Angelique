# brain/cognitive_loop.py
import json
import re
import threading
import uuid
from pathlib import Path
from core import audit
from core.tool_registry import GLOBAL_TOOL_REGISTRY
from core.pending_actions import add_pending, find_pending_for_session, confirm_and_remove, get_pending, PENDING_PLAN_SERVICE
from core.execution_gateway import GATEWAY as EXEC_GATEWAY
from core.local_ai_router import get_local_router
import brain.llm_interface as llm_interface
# Compatibility wrappers so tests can patch either `brain.cognitive_loop.query_llm`
# or `brain.llm_interface.query_llm`. Using wrappers ensures runtime calls always
# delegate to the current implementation on `llm_interface`, so monkeypatches on
# either symbol work as expected.
def query_llm(messages, temperature: float = 0.7):
    return llm_interface.query_llm(messages, temperature=temperature)


def _call_through_execute_tool(name, args, user_request=None, session_id=None, timeout=None):
    res = execute_tool(name, args or {}, user_request=user_request, session_id=session_id, timeout=timeout)
    class _ER:
        def __init__(self, success, output=None, error=None):
            self.success = success
            self.output = output
            self.error = error
    if isinstance(res, str) and (res.startswith("Error") or res.lower().startswith("error")):
        return _ER(False, output=None, error=res)
    return _ER(True, output=res, error=None)

def extract_json_from_text(text):
    return llm_interface.extract_json_from_text(text)
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


def _execute_validated_plan(calls: list, user_input: str, session_id: str | None = None) -> dict:
    validated_calls = []
    requires_confirmation = False
    for item in calls:
        if not isinstance(item, dict):
            continue
        tname = item.get("tool")
        targs = item.get("args", {}) or {}
        if not tname:
            return {"source": "error", "answer": "Invalid tool call format. Each call must include a 'tool' key.", "details": {}}

        schema = GLOBAL_TOOL_REGISTRY.get(tname)
        if not schema and tname not in TOOL_REGISTRY:
            audit.record({"action": "unknown_tool_requested", "tool": tname, "session_id": session_id, "user_request": user_input})
            return {"source": "error", "answer": f"Unknown tool requested: {tname}", "details": {}}

        if schema:
            valid, errors = GLOBAL_TOOL_REGISTRY.validate_call(tname, targs)
            if not valid:
                audit.record({"action": "validation_failed", "tool": tname, "errors": errors, "session_id": session_id, "user_request": user_input})
                return {"source": "error", "answer": f"Validation failed for tool {tname}: {errors}", "details": {"errors": errors}}

        validated_calls.append({"tool": tname, "args": targs})
        legacy_meta = TOOL_REGISTRY.get(tname, {})
        if bool(legacy_meta.get("requires_confirmation", False)) or (schema and schema.risk_level in ("SENSITIVE", "DESTRUCTIVE", "FINANCIAL")):
            requires_confirmation = True

    if requires_confirmation:
        plan_id = str(uuid.uuid4())
        plan = {"id": plan_id, "calls": validated_calls, "user_request": user_input, "session_id": session_id}
        try:
            add_pending(plan_id, plan, ttl_seconds=600)
            audit.record({"action": "pending_created", "plan_id": plan_id, "session_id": session_id, "plan": validated_calls})
        except Exception:
            audit.record({"action": "pending_create_failed", "session_id": session_id})
        return {"source": "confirmation_required", "answer": f"The requested action includes sensitive operations and requires confirmation. Reply 'yes' to proceed or 'no' to cancel. To confirm a specific pending action, reply 'confirm {plan_id}'.", "details": {"plan_id": plan_id}}

    outputs = []
    for call in validated_calls:
        tname = call.get("tool")
        targs = call.get("args", {}) or {}
        exec_res = _call_through_execute_tool(tname, targs, user_request=user_input, session_id=session_id)
        outputs.append({"tool": tname, "success": exec_res.success, "output": exec_res.output, "error": exec_res.error})

    return {"source": "tool", "answer": outputs, "details": {"outputs": outputs}}


def resolve_user_query(user_input: str, session_id: str | None = None) -> dict:
    """High-level coordinated query resolver.

    Steps:
    1. "Think": silently extract facts from the user's input and persist them.
    2. Check conversation memory when appropriate.
           "You are Angelique. Answer the user's request naturally and keep recent conversation context in mind.",
    4. Use the LLM to decide whether to answer naturally or issue a tool request.
    5. Persist any new facts discovered from external answers.

    Returns a dict with keys: `source` (one of 'conversation','fact','tool','llm'), `answer`, and `details`.
    """
    text = _strip_training_mode_prefix(user_input)

    # Deterministic facts/actions must never be hallucinated by an LLM.
    normalized_text = (text or "").strip().lower()
    try:
        if (re.search(r"\b(?:what(?:'s| is)?|tell me|give me|show me)\s+(?:the\s+)?(?:current\s+)?(?:time|date|day)\b", normalized_text)
                or re.fullmatch(r"(?:time|date|today|what time is it|what is the date|what is the time and date|what's the time and date)", normalized_text)):
            from datetime import datetime
            now = datetime.now().astimezone()
            wants_time = "time" in normalized_text
            wants_date = any(token in normalized_text for token in ("date", "today", "day"))
            if wants_time and wants_date:
                answer = now.strftime("It is %A, %B %d, %Y and the current time is %I:%M:%S %p (%Z).")
            elif wants_time:
                answer = now.strftime("The current time is %I:%M:%S %p (%Z).")
            else:
                answer = now.strftime("Today is %A, %B %d, %Y (%Y-%m-%d).")
            conv_save(session_id, user_input, answer)
            return {"source": "system", "answer": answer, "details": {"timestamp": now.isoformat()}}
    except Exception:
        pass

    # File-name searches are deterministic. Do not ask an LLM to infer whether a
    # file exists; it should delegate the actual filesystem query.
    try:
        exact_name = re.search(
            r"(?:find|search|look(?:\s+for)?|locate).*?(?:file|folder|directory)\s+(?:named|called|with\s+name)\s+(.+?)(?:\s+(?:on|in|under|within)\s+(?:my\s+)?(?:laptop|computer|pc|home|filesystem).*|$)",
            text, re.IGNORECASE,
        )
        if not exact_name:
            exact_name = re.search(
                r"(?:find|search|look(?:\s+for)?|locate).*?\b(?:named|called)\s+(.+?)(?:\s+(?:on|in|under|within)\s+(?:my\s+)?(?:laptop|computer|pc|home|filesystem).*|$)",
                text, re.IGNORECASE,
            )
        if exact_name:
            query = exact_name.group(1).strip().strip('\"\'')
            query = re.split(r"\s+and\s+(?:tell|show|read)\s+me\b", query, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            query = re.sub(r"\s+(?:on|in|under|within)\s+(?:my\s+)?(?:laptop|computer|pc|home|filesystem).*?$", "", query, flags=re.IGNORECASE).strip()
            result = _call_through_execute_tool("search_files", {"query": query, "root": str(Path.home()), "max_results": 100, "max_depth": 12}, user_request=user_input, session_id=session_id)
            answer = result.output if result.success else result.error
            conv_save(session_id, user_input, answer)
            return {"source": "tool", "answer": answer, "details": {"tool": "search_files", "args": {"query": query, "root": str(Path.home())}}}
    except Exception:
        pass

    # Deterministic action routing must happen before any LLM probe. This keeps
    # filesystem, browser, messaging, system and other explicit actions fast and
    # prevents a slow model from blocking a command that does not need reasoning.
    try:
        h_tool, h_args = nlp_to_tool_mapping(text)
        if h_tool:
            result = _execute_validated_plan(
                [{"tool": h_tool, "args": h_args or {}}],
                user_input=text,
                session_id=session_id,
            )
            answer = result.get("answer")
            conv_save(session_id, user_input, answer)
            return result
    except Exception as exc:
        audit.record({"action": "deterministic_route_failed", "error": str(exc), "user_request": user_input})

    # --- Pending plan follow-up handling -------------------------------------------------
    try:
        normalized = (user_input or "").strip().lower()
        # look up pending plans for this session
        pending_map = find_pending_for_session(session_id or "default")
        if not pending_map:
            # If the user replied with a short yes/no but there are no pending
            # plans for this session, return early so the reply isn't treated as
            # a global confirmation for other sessions.
            if _is_short_followup_reply(normalized):
                return {"source": "user", "answer": "No pending plan found to confirm.", "details": {}}
        if pending_map:
            # check explicit plan id mention
            mentioned_id = None
            for pid in pending_map.keys():
                if pid in normalized:
                    mentioned_id = pid
                    break

            # detect clear affirmative/negative replies
            affirmatives = {"yes", "y", "confirm", "approve", "ok", "okay", "sure", "do it", "go ahead", "proceed"}
            negatives = {"no", "n", "cancel", "abort", "stop", "do not", "don't"}
            is_short = _is_short_followup_reply(normalized)

            # If user explicitly references a plan id, act on that; otherwise require a short explicit reply and only when one pending exists.
            target_pid = mentioned_id
            if not target_pid and len(pending_map) == 1 and is_short:
                target_pid = next(iter(pending_map.keys()))
            if not target_pid and len(pending_map) > 1 and is_short:
                # If multiple pending plans exist and user replied with a short
                # confirmation, assume they mean the most recent pending plan.
                try:
                    target_pid = list(pending_map.keys())[-1]
                except Exception:
                    target_pid = next(iter(pending_map.keys()))

            if target_pid:
                # Confirm/cancel handling
                if any(token in normalized for token in affirmatives):
                    plan = get_pending(target_pid)
                    if not plan:
                        audit.record({"action": "confirm_missing", "plan_id": target_pid, "session_id": session_id})
                        return {"source": "error", "answer": "No pending plan found to confirm.", "details": {}}
                    result = EXEC_GATEWAY.confirm(target_pid, session_id or "default")
                    if result is None:
                        return {"source": "error", "answer": "No pending plan found to confirm.", "details": {}}
                    audit.record({"action": "confirmed_and_executed", "plan_id": target_pid, "session_id": session_id, "outputs": result.get("outputs", [])})
                    return {"source": "tool", "answer": result.get("outputs", []), "details": {"plan_id": target_pid}}
                elif any(token in normalized for token in negatives):
                    plan = confirm_and_remove(target_pid)
                    audit.record({"action": "plan_cancelled", "plan_id": target_pid, "session_id": session_id})
                    return {"source": "user", "answer": "Cancelled the pending plan.", "details": {"plan_id": target_pid}}
                else:
                    # ambiguous; ask for explicit confirmation
                    return {"source": "user", "answer": "I have a pending action awaiting confirmation. Reply 'yes' to proceed or 'no' to cancel.", "details": {"pending_count": len(pending_map)}}
    except Exception:
        # fallthrough to normal handling on any failure here
        pass
    # -------------------------------------------------------------------------------------
    # Quick LLM probe before deterministic heuristics: some tests patch
    # `query_llm` and expect a single lightweight LLM call to drive tool
    # decisions for ambiguous or high-level action requests. Call the
    # module-level `query_llm` once and honor any explicit JSON tool
    # decision it returns. If no decision is returned, continue to
    # deterministic heuristics.
    try:
        probe = None
        try:
            probe = query_llm(_build_messages_with_history(
                "You are Angelique. Decide if the user's request should be executed as a tool or answered normally. Reply with JSON when requesting a tool.",
                text,
                session_id=session_id,
            ), temperature=0.0)
        except Exception:
            probe = None

        if probe:
            probe_decision = extract_json_from_text(probe)
            # If LLM returned a dict or list of tool calls, handle it now
            if isinstance(probe_decision, dict) and probe_decision:
                tname = probe_decision.get("tool")
                targs = probe_decision.get("args", {}) or {}
                if tname:
                    tool_result = _exec_tool(tname, targs)
                    conv_save(session_id, user_input, tool_result)
                    return {"source": "tool", "answer": tool_result, "details": {"tool": tname, "args": targs}}
            elif isinstance(probe_decision, list) and probe_decision:
                # Execute list of steps as in orchestration
                outputs = []
                for step in probe_decision:
                    if not isinstance(step, dict):
                        continue
                    tname = step.get("tool")
                    targs = step.get("args", {}) or {}
                    valid, errors = GLOBAL_TOOL_REGISTRY.validate_call(tname, targs)
                    if not valid:
                        audit.record({"action": "validation_failed_on_probe", "tool": tname, "errors": errors, "session_id": session_id})
                        return {"source": "error", "answer": f"Validation failed for tool {tname}: {errors}", "details": {"errors": errors}}
                    exec_res = _call_through_execute_tool(tname, targs or {}, user_request=user_input, session_id=session_id)
                    outputs.append({"tool": tname, "success": exec_res.success, "output": exec_res.output, "error": exec_res.error})
                conv_save(session_id, user_input, outputs)
                return {"source": "tool", "answer": outputs, "details": {"outputs": outputs}}
    except Exception:
        pass
    # Helper executor that ensures ExecutionGateway receives context
    def _exec_tool(tool_name: str, args: dict | None = None, timeout: float | None = None):
        # Prefer calling the public `execute_tool(tool, args)` signature so
        # tests that patch `brain.cognitive_loop.execute_tool` receive the
        # expected call shape. If that call raises TypeError (old signature),
        # retry with extended context kwargs for the gateway.
        try:
            return execute_tool(tool_name, args or {})
        except TypeError:
            return execute_tool(tool_name, args or {}, user_request=user_input, session_id=session_id, timeout=timeout)

    

    # 0) Deterministic heuristic routing: try to map to a tool BEFORE calling any LLM.
    try:
        h_tool, h_args = nlp_to_tool_mapping(text)
        if h_tool:
            # Check for ambiguity: if the user input contains tokens that
            # match other registered tool names (e.g., 'sensitive' -> test.sensitive),
            # prefer consulting the LLM so sensitive tools can be detected.
            tokens = set(re.findall(r"\w+", text.lower()))
            registered = set(list(GLOBAL_TOOL_REGISTRY.list()) + list(TOOL_REGISTRY.keys()))
            ambiguous = False
            for t in registered:
                if t == h_tool:
                    continue
                name_tokens = set(re.findall(r"\w+", t.lower()))
                if tokens & name_tokens:
                    ambiguous = True
                    break

            if ambiguous:
                # Defer to LLM-driven path
                raise RuntimeError("heuristic_ambiguous")

            try:
                tool_result = _exec_tool(h_tool, h_args or {})
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
                    tool_result = _exec_tool('run_shell_command', {'command': cmd})
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
                    tool_result = _exec_tool('run_shell_command', {'command': cmd})
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
        # If the user's input mentions tokens that overlap with registered tool
        # names (e.g., 'sensitive' -> 'test.sensitive'), the mapping below may
        # be ambiguous; defer to the LLM so schema-driven confirmation can apply.
        tokens = set(re.findall(r"\w+", lower))
        registered = set(list(GLOBAL_TOOL_REGISTRY.list()) + list(TOOL_REGISTRY.keys()))
        for t in registered:
            name_tokens = set(re.findall(r"\w+", t.lower()))
            if tokens & name_tokens:
                raise RuntimeError("heuristic_ambiguous")

        # ========== MESSAGING / WHATSAPP ==========
        # High-confidence natural language forms are parsed deterministically so
        # trailing words like "a message" or "on WhatsApp" never become part of
        # the contact name.
        whatsapp_specific = [
            r"^send\s+(?P<contact>.+?)\s+a\s+message\s+on\s+whatsapp\s+saying\s+(?P<message>.+)$",
            r"^send\s+(?P<contact>.+?)\s+on\s+whatsapp\s+saying\s+(?P<message>.+)$",
            r"^send\s+(?P<contact>.+?)\s+message\s+on\s+whatsapp\s+(?:saying\s+)?(?P<message>.+)$",
            r"^message\s+(?P<contact>.+?)\s+on\s+whatsapp\s+saying\s+(?P<message>.+)$",
        ]
        for pattern in whatsapp_specific:
            m = re.match(pattern, lower.strip(), re.IGNORECASE)
            if m:
                contact = m.group('contact').strip(' ,')
                msg = m.group('message').strip()
                try:
                    tool_result = _exec_tool('send_whatsapp', {'contact_name': contact, 'message': msg})
                except Exception as e:
                    tool_result = f"Error sending WhatsApp: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": "send_whatsapp", "args": {"contact_name": contact, "message": msg}}}

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
                    tool_result = _exec_tool('send_whatsapp', {'contact_name': contact, 'message': msg})
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
                    tool_result = _exec_tool('generate_image', {'prompt': prompt, 'size': size})
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
                    tool_result = _exec_tool('speak', {'text': phrase})
                except Exception:
                    tool_result = _exec_tool('call_skill', {'skill_name': 'skills.voice.voice_interface.speak', 'args': {'text': phrase}})
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
                    tool_result = _exec_tool('cli_open' if action == 'open' else 'cli_cat', {'file_path': fp})
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
                    tool_result = _exec_tool('list_directory', {'path': path})
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
                    tool_result = _exec_tool('manage_files', {'action': 'mkdir', 'path': folder})
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
                    tool_result = _exec_tool('manage_files', {'action': 'delete', 'path': fp})
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
                    tool_result = _exec_tool('manage_files', {'action': 'move', 'path': src, 'new_path': dst})
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
                    tool_result = _exec_tool('manage_files', {'action': 'copy', 'path': src, 'new_path': dst})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'manage_files', 'args': {'action': 'copy', 'path': src, 'new_path': dst}}}

        # ========== APP/PROGRAM LAUNCHING ==========
        app_patterns = [
            # Require explicit 'app'/'application' keyword to avoid over-eager matching like 'run steps'
            r"\b(?:open|launch|start|execute|begin)\s+(?:the\s+)?([a-z0-9\-_ ]+?)\s+(?:app|application|program)\b",
            r"\b(?:open|launch|start)\s+([a-z0-9\-_ ]+?)$",
        ]
        for pattern in app_patterns:
            m = re.search(pattern, lower)
            if m:
                app = m.group(1).strip()
                if app not in {'file', 'folder', 'directory', 'terminal', 'browser', 'chrome', 'firefox', 'code', 'editor'} and not any(x in app for x in {'the', 'a ', 'an '}):
                    try:
                        tool_result = _exec_tool('open_app', {'app_name': app})
                    except Exception as e:
                        tool_result = f"Error: {e}"
                    conv_save(session_id, user_input, tool_result)
                    return {"source": "tool", "answer": tool_result, "details": {"tool": 'open_app', 'args': {'app_name': app}}}

        # ========== SYSTEM CHECKS & MONITORING ==========
        if re.search(r"\b(?:check|get|show|what)\b.*\b(?:status|health|performance|metrics|pc|system|computer)\b", lower):
            try:
                    tool_result = _exec_tool('get_system_health', {})
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
                    tool_result = _exec_tool('search_web', {'query': query})
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
                    tool_result = _exec_tool('recall_memory', {'query': query})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'recall_memory', 'args': {'query': query}}}

        # ========== SAVE/STORE MEMORY ==========
        if re.search(r"\b(?:remember|save|store|note|log|record)\s+(?:that|this|my)\b", lower):
            try:
                tool_result = _exec_tool('save_memory', {'person': 'User', 'key': 'note', 'value': text})
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
                tool_result = _exec_tool('save_text_pdf', {'path': '/tmp/document.pdf', 'text': text})
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
                tool_result = _exec_tool('read_screen', {})
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
                tool_result = _exec_tool('analyze_camera', {})
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
                    tool_result = _exec_tool('check_installation_status', {'target_name': target})
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
                    tool_result = _exec_tool('analyze_market_and_recommend', {'symbol': symbol, 'risk_percent': 1.0})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'analyze_market_and_recommend'}}

        # ========== FOREX/MARKET NEWS ==========
        if re.search(r"\b(?:news|market news|forex news|economic news|events|calendar)\b", lower):
            try:
                tool_result = _exec_tool('get_forex_news', {'symbol': None})
            except Exception as e:
                tool_result = f"Error: {e}"
            conv_save(session_id, user_input, tool_result)
            return {"source": "tool", "answer": tool_result, "details": {"tool": 'get_forex_news'}}

        # ========== LIST APPS / SOFTWARE ==========
        if re.search(r"\b(?:list|show|what)\s+(?:apps|applications|programs|installed software|software)\b", lower):
            try:
                tool_result = _exec_tool('list_apps', {})
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
                    tool_result = _exec_tool('create_and_execute_skill', {'instruction': instruction})
                except Exception as e:
                    tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'create_and_execute_skill'}}

        # ========== CONSOLE / TERMINAL COMMANDS ==========
        if re.search(r"\b(?:run|execute|bash|shell|cmd|command|powershell)\s+(.+)$", lower):
            m = re.search(r"\b(?:run|execute|bash|shell|cmd|command|powershell)\s+(.+)$", lower)
            if m:
                cmd = m.group(1).strip()
                # Avoid treating single-word 'run <word>' as a shell invocation
                # since those are often ambiguous and may be LLM-driven (e.g., 'run steps').
                if len(cmd.split()) == 1:
                    # skip mapping to shell for single-token commands
                    pass
                else:
                    try:
                        tool_result = _exec_tool('run_shell_command', {'command': cmd})
                    except Exception as e:
                        tool_result = f"Error: {e}"
                conv_save(session_id, user_input, tool_result)
                return {"source": "tool", "answer": tool_result, "details": {"tool": 'run_shell_command'}}

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
                # If the LLM returned a list of tool calls, execute them in order
                if isinstance(decision, list):
                    outputs = []
                    for step in decision:
                        if not isinstance(step, dict):
                            continue
                        tname = step.get("tool")
                        targs = step.get("args", {}) or {}
                        # Validate before executing
                        valid, errors = GLOBAL_TOOL_REGISTRY.validate_call(tname, targs)
                        if not valid:
                            audit.record({"action": "validation_failed_on_orchestration", "errors": errors, "session_id": session_id})
                            return {"source": "error", "answer": f"Validation failed for tool {tname}: {errors}", "details": {"errors": errors}}
                        exec_res = _call_through_execute_tool(tname, targs or {}, user_request=user_input, session_id=session_id)
                        outputs.append({"tool": tname, "success": exec_res.success, "output": exec_res.output, "error": exec_res.error})
                    audit.record({"action": "orchestrated_multi_execute", "session_id": session_id, "outputs": outputs})
                    conv_save(session_id, user_input, outputs)
                    return {"source": "tool", "answer": outputs, "details": {"outputs": outputs}}
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
                tool_result = _exec_tool(tool_name, args)
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
                tool_result = _exec_tool(tool_name, args or {})
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
            # Support LLM returning a list of tool calls
            if isinstance(decision, list):
                outputs = []
                for step in decision:
                    if not isinstance(step, dict):
                        continue
                    tname = step.get("tool")
                    targs = step.get("args", {}) or {}
                    valid, errors = GLOBAL_TOOL_REGISTRY.validate_call(tname, targs)
                    if not valid:
                        audit.record({"action": "validation_failed_on_single_pass", "tool": tname, "errors": errors, "session_id": session_id})
                        return {"source": "error", "answer": f"Validation failed for tool {tname}: {errors}", "details": {"errors": errors}}
                    exec_res = _call_through_execute_tool(tname, targs or {}, user_request=user_input, session_id=session_id)
                    outputs.append({"tool": tname, "success": exec_res.success, "output": exec_res.output, "error": exec_res.error})
                conv_save(session_id, user_input, outputs)
                audit.record({"action": "single_pass_multi_execute", "session_id": session_id, "outputs": outputs})
                return {"source": "tool", "answer": outputs, "details": {"outputs": outputs}}
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

            if tool_name:
                # If there's a schema or legacy metadata indicating confirmation
                # is required, create a pending plan instead of executing.
                schema = GLOBAL_TOOL_REGISTRY.get(tool_name)
                legacy_meta = TOOL_REGISTRY.get(tool_name, {})
                if not schema and tool_name not in TOOL_REGISTRY:
                    audit.record({"action": "unknown_tool_requested", "tool": tool_name, "session_id": session_id, "user_request": user_input})
                    conv_save(session_id, user_input, response)
                    return {"source": "error", "answer": f"Unknown tool requested: {tool_name}", "details": {}}

                # Validate args when schema exists
                if schema:
                    valid, errors = GLOBAL_TOOL_REGISTRY.validate_call(tool_name, args or {})
                    if not valid:
                        audit.record({"action": "validation_failed", "tool": tool_name, "errors": errors, "session_id": session_id, "user_request": user_input})
                        conv_save(session_id, user_input, response)
                        return {"source": "error", "answer": f"Validation failed for tool {tool_name}: {errors}", "details": {"errors": errors}}

                requires_confirmation = bool(legacy_meta.get("requires_confirmation", False)) or (schema and schema.risk_level in ("SENSITIVE", "DESTRUCTIVE", "FINANCIAL"))
                if requires_confirmation:
                    plan_id = str(uuid.uuid4())
                    plan = {"id": plan_id, "calls": [{"tool": tool_name, "args": args or {}}], "user_request": user_input, "session_id": session_id}
                    try:
                        add_pending(plan_id, plan, ttl_seconds=600)
                        audit.record({"action": "pending_created", "plan_id": plan_id, "session_id": session_id, "plan": plan["calls"]})
                    except Exception:
                        audit.record({"action": "pending_create_failed", "session_id": session_id})
                    conv_save(session_id, user_input, f"PENDING_PLAN {plan_id}")
                    return {"source": "confirmation_required", "answer": f"The requested action includes sensitive operations and requires confirmation. Reply 'yes' to proceed or 'no' to cancel. To confirm a specific pending action, reply 'confirm {plan_id}'.", "details": {"plan_id": plan_id}}

                # Otherwise execute normally
                tool_result = _exec_tool(tool_name, args)
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
    """Extract explicit facts with the local Qwen parser, then persist them.

    The legacy LLM parser remains a fallback for machines without Ollama.
    """
    if _looks_like_general_query(user_input):
        return
    try:
        routed = get_local_router().extract_facts(user_input)
    except Exception as exc:
        routed = None
        print(f"[DEBUG] Local fact router unavailable: {exc}")
    if routed is not None:
        for item in routed.get("extracted_facts", []):
            entity = str(item.get("entity", "")).strip() or "User"
            key = str(item.get("category", "general")).strip().lower()
            value = str(item.get("fact", "")).strip()
            if not value:
                continue
            # Keep extraction deterministic. The category becomes a stable key
            # while the full explicit statement is preserved as the value.
            if key == "general":
                key = "fact"
            importance = 5
            save_fact_to_db(entity, key, value, importance, "local_qwen_extraction")
        return

    extraction_prompt = (
        "You are a strict cognitive fact-extraction engine. Analyze the user's input below.\n"
        "Extract ALL facts about ANY person mentioned. Return ONLY a valid JSON list of objects.\n"
        "If there are no new facts to extract, return EXACTLY: []\n\n"
        "STRICT RULES: person, key, value, importance, context. Never invent facts.\n"
        f"User input: '{user_input}'"
    )
    try:
        raw_content = query_llm([{"role": "user", "content": extraction_prompt}], temperature=0.0)
        if not raw_content:
            return
        clean_content = raw_content.replace("```json", "").replace("```", "").strip()
        list_match = re.search(r"\[.*\]", clean_content, re.DOTALL)
        obj_match = re.search(r"\{.*\}", clean_content, re.DOTALL)
        json_str = list_match.group(0) if list_match else (obj_match.group(0) if obj_match else clean_content)
        facts = json.loads(json_str)
        for item in facts if isinstance(facts, list) else [facts]:
            if not isinstance(item, dict):
                continue
            person = str(item.get("person", "User")).strip() or "User"
            key = str(item.get("key", "fact")).lower().strip() or "fact"
            value = str(item.get("value", "")).strip()
            if value and value.lower() != "unknown":
                save_fact_to_db(person, key, value, max(1, min(10, int(item.get("importance", 5)))), str(item.get("context", "")).strip())
    except Exception as exc:
        print(f"[DEBUG] Silent extraction failed: {exc}")


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
    # Remember whether the current invocation is an explicit retry request
    original_input = user_input
    was_retry = _is_retry_request(user_input)
    if was_retry and last_user_input:
        user_input = last_user_input

    # Require explicit confirmation for potentially-destructive install/uninstall
    normalized = (user_input or "").strip().lower()
    if re.search(r"\binstall\b|\buninstall\b", normalized):
        # If the user asked as a question or requested instructions, allow normal flow
        if not normalized.endswith("?") and "how" not in normalized and "how to" not in normalized:
            # If this invocation is an explicit retry of a prior request, assume the user is confirming
            if not was_retry:
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

    # Build a detailed tool schema for the LLM so it knows exactly what tools exist,
    # their parameters, and whether they require explicit confirmation.
    def _tool_schema_detailed():
        schema = {}
        for name, info in TOOL_REGISTRY.items():
            schema[name] = {
                "description": info.get("description", ""),
                "parameters": info.get("parameters", {}),
                "requires_confirmation": bool(info.get("requires_confirmation", False)),
            }
        return schema

    tools_schema = json.dumps(_tool_schema_detailed(), indent=2)

    system_prompt = (
        "You are Angelique, a highly advanced, self-evolving autonomous AI companion.\n\n"
        "The system provides you with a strict registry of available tools (names, descriptions, parameters, and whether they require explicit user confirmation).\n"
        "You MUST NOT invent tools or arbitrary shell commands. When an action is required, return either a single JSON object: {\"tool\": \"tool_name\", \"args\": {...}}\n"
        "or a JSON list of such objects to indicate a sequence of tool calls. Example: [{\"tool\": \"get_account_balance\"}, {\"tool\": \"analyze_market_and_recommend\", \"args\": {\"symbol\": \"EURUSD\"}}].\n\n"
        f"Available tools (JSON):\n{tools_schema}\n\n"
        f"{training_memory_text}\n\n"
        "CORE DIRECTIVES:\n"
        "1. If the user asks a question or is conversational, answer naturally with text (no JSON).\n"
        "2. If the user requests actions, return structured JSON using only the tools above.\n"
        "3. If a tool in the plan requires confirmation, mark it clearly (the runtime will enforce confirmation and will not execute until the user approves).\n"
        "4. For multi-step requests, you may return a list of tool calls; the runtime will validate and execute them in order, passing results back for further reasoning.\n"
        "5. NEVER include undocumented tools or use dynamic code execution in the JSON output.\n"
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
    if memory_text and memory_text != "None. You do not know this yet.":
        messages.insert(1, {"role": "system", "content": "RETRIEVED MEMORY (use only these facts; do not infer beyond them):\n" + memory_text})
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
    natural_answer = None

    # Handle empty or invalid JSON: attempt clarification
    if not decision or (not isinstance(decision, (dict, list)) or (isinstance(decision, dict) and len(decision) == 0)):
        if _is_identity_question(user_input):
            conv_save(session_id, user_input, raw_response)
            return raw_response

        refined_decision, clarified_response = _extract_tool_decision(raw_response, user_input, session_id=session_id)
        if isinstance(refined_decision, (dict, list)) and refined_decision:
            decision = refined_decision
        elif clarified_response is not None:
            natural_answer = clarified_response

    # Normalize decision into a list of calls
    calls = []
    if isinstance(decision, dict) and decision:
        if "tool" in decision:
            calls = [decision]
        elif "calls" in decision and isinstance(decision["calls"], list):
            calls = decision["calls"]
        else:
            # Support dict mapping: {"tool_name": {args}}
            for t in TOOL_REGISTRY.keys():
                if t in decision:
                    calls = [{"tool": t, "args": decision[t]}]
                    break
    elif isinstance(decision, list):
        calls = decision

    # If we have planned calls, validate and execute them (strict validation, no silent stripping)
    if calls:
        validated_calls = []
        requires_confirmation = False
        for item in calls:
            if not isinstance(item, dict):
                continue
            tname = item.get("tool")
            targs = item.get("args", {}) or {}
            if not tname:
                conv_save(session_id, user_input, raw_response)
                return {"source": "error", "answer": "Invalid tool call format. Each call must include a 'tool' key.", "details": {}}

            # ensure tool exists in registry
            schema = GLOBAL_TOOL_REGISTRY.get(tname)
            if not schema and tname not in TOOL_REGISTRY:
                audit.record({"action": "unknown_tool_requested", "tool": tname, "session_id": session_id, "user_request": user_input})
                conv_save(session_id, user_input, raw_response)
                return {"source": "error", "answer": f"Unknown tool requested: {tname}", "details": {}}

            # Validate args against schema when available
            if schema:
                valid, errors = GLOBAL_TOOL_REGISTRY.validate_call(tname, targs)
                if not valid:
                    audit.record({"action": "validation_failed", "tool": tname, "errors": errors, "session_id": session_id, "user_request": user_input})
                    conv_save(session_id, user_input, raw_response)
                    return {"source": "error", "answer": f"Validation failed for tool {tname}: {errors}", "details": {"errors": errors}}

            # For legacy tools without a schema, accept but log
            validated_calls.append({"tool": tname, "args": targs})

            # Determine if confirmation required (legacy metadata or schema risk level)
            legacy_meta = TOOL_REGISTRY.get(tname, {})
            if bool(legacy_meta.get("requires_confirmation", False)):
                requires_confirmation = True
            elif schema and schema.risk_level in ("SENSITIVE", "DESTRUCTIVE", "FINANCIAL"):
                requires_confirmation = True

        if requires_confirmation:
            plan_id = str(uuid.uuid4())
            plan = {"id": plan_id, "calls": validated_calls, "user_request": user_input, "session_id": session_id}
            try:
                add_pending(plan_id, plan, ttl_seconds=600)
                audit.record({"action": "pending_created", "plan_id": plan_id, "session_id": session_id, "plan": validated_calls})
            except Exception:
                audit.record({"action": "pending_create_failed", "session_id": session_id})
            conv_save(session_id, user_input, f"PENDING_PLAN {plan_id}")
            return {"source": "confirmation_required", "answer": f"The requested action includes sensitive operations and requires confirmation. Reply 'yes' to proceed or 'no' to cancel. To confirm a specific pending action, reply 'confirm {plan_id}'.", "details": {"plan_id": plan_id}}

        # Execute validated calls sequentially via ExecutionGateway
        outputs = []
        for call in validated_calls:
            tname = call.get("tool")
            targs = call.get("args", {}) or {}
            exec_res = _call_through_execute_tool(tname, targs, user_request=user_input, session_id=session_id)
            outputs.append({"tool": tname, "success": exec_res.success, "output": exec_res.output, "error": exec_res.error})

        # Synthesize final response via LLM using tool outputs
        synth_system = "You are Angelique. Given the user's original request and the tool execution results below, produce a concise, factual, and user-facing summary. Do not invent additional actions."
        synth_user = f"Original user request: {user_input}\n\nTool execution outputs:\n{json.dumps(outputs, indent=2)}"
        try:
            synth_messages = _build_messages_with_history(synth_system, synth_user, session_id=session_id)
            final_text = query_llm(synth_messages, temperature=0.0) or json.dumps(outputs)
            conv_save(session_id, user_input, final_text)
            audit.record({"action": "plan_executed", "session_id": session_id, "outputs": outputs})
            return {"source": "tool", "answer": final_text, "details": {"outputs": outputs}}
        except Exception:
            conv_save(session_id, user_input, str(outputs))
            audit.record({"action": "synthesis_failed", "session_id": session_id, "outputs": outputs})
            return {"source": "tool", "answer": outputs, "details": {"outputs": outputs}}

    # No planned calls detected; fall back to heuristics or natural answer
    if natural_answer is not None:
        # If this invocation was a retry of a previous user request, attempt
        # to map it to a deterministic tool and execute it before returning
        # the (possibly clarified) natural answer. This preserves the UX of
        # 'try again' reusing prior requests while still reporting the LLM's
        # final natural response.
        if was_retry:
            try:
                tname, targs = nlp_to_tool_mapping(user_input)
                if tname:
                    execute_tool(tname, targs or {})
            except Exception:
                pass
        conv_save(session_id, user_input, natural_answer)
        return natural_answer

    # Attempt deterministic heuristics as fallback
    tool_name, args = nlp_to_tool_mapping(user_input)
    if not tool_name:
        tool_name, args = nlp_to_tool_mapping(raw_response or "")

    if args is None:
        args = {}
    if not isinstance(args, dict):
        args = {}

    if tool_name:
        tool_result = _exec_tool(tool_name, args)
        conv_save(session_id, user_input, tool_result)
        return tool_result if isinstance(tool_result, str) else json.dumps(tool_result, ensure_ascii=False)

    final = natural_answer or raw_response
    conv_save(session_id, user_input, final)
    return final
