# brain/cognitive_loop.py
import json
import re
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


def resolve_user_query(user_input: str, session_id: str | None = None) -> dict:
    """High-level coordinated query resolver.

    Steps:
    1. "Think": silently extract facts from the user's input and persist them.
    2. Check conversation memory when appropriate.
    3. Check fact/knowledge memory when appropriate.
    4. If nothing is found, query external LLMs (and other models) via `query_llm`.
    5. Persist any new facts discovered from external answers.

    Returns a dict with keys: `source` (one of 'conversation','fact','llm'), `answer`, and `details`.
    """
    text = _strip_training_mode_prefix(user_input)

    # 1) Think: extract facts silently and persist them
    try:
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
            # Save any extracted facts from the final answer silently
            try:
                extract_facts_silently(final_answer)
            except Exception:
                pass
            details = orchestration.get("details", {}) if isinstance(orchestration, dict) else {}
            details["orchestrated"] = True
            return {"source": "llm", "answer": final_answer, "details": details}
        else:
            # Single-pass lightweight LLM call for simple queries
            response = query_llm(_build_messages_with_history(
                "You are Angelique. Answer the user's request naturally and keep recent conversation context in mind.",
                text,
                session_id=session_id,
            ), temperature=0.2)
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
    tool_name, args = extract_command_heuristically(text)
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


def _should_use_orchestration(user_input: str) -> bool:
    """Decide whether to run multi-LLM orchestration for a given input.

    Heuristics:
    - Disabled via `core.config.ENABLE_MULTI_LLM_ORCHESTRATION`.
    - Never for identity or simple questions.
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

    if _is_identity_question(user_input) or _is_simple_question(user_input):
        return False

    words = re.findall(r"\b[\w']+\b", user_input)
    if len(words) >= min_words:
        return True

    normalized = user_input.lower()
    if any(k in normalized for k in keywords):
        return True

    return False


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
        "1. ACTION REQUESTS: If the user asks you to do something, you MUST reply with ONLY a JSON object for the tool.\n"
        "   Format: {\"tool\": \"tool_name\", \"args\": {\"param1\": \"value1\"}}\n"
        "2. CONVERSATION: If the user is just chatting, reply naturally. DO NOT output JSON.\n"
        "3. MEMORY USAGE: Use the RELEVANT MEMORY to personalize your responses. Notice the importance scores (🔥 is high, 📌 is low). Prioritize highly important facts.\n"
        "4. NEVER hallucinate facts. Only use facts present in RELEVANT MEMORY.\n"
        "5. TRADING NEWS: When the user asks about forex news, market events, or the economic calendar, use the get_forex_news and get_market_calendar tools immediately.\n\n"
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

    raw_response = query_llm(messages, temperature=0.0)
    if raw_response is None:
        return "I'm having a little trouble connecting to my brain right now."

    decision = extract_json_from_text(raw_response)
    tool_name = None
    args = {}

    # Handle LLM responses that return empty or invalid JSON
    if not decision or not isinstance(decision, dict) or len(decision) == 0:
        if _is_identity_question(user_input):
            conv_save(session_id, user_input, raw_response)
            return raw_response
        tool_name, args = nlp_to_tool_mapping(user_input)
        if not tool_name:
            tool_name, args = nlp_to_tool_mapping(raw_response or "")
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

    # Ensure args is always a valid dict
    if args is None:
        args = {}
    if not isinstance(args, dict):
        args = {}

    if tool_name and tool_name in TOOL_REGISTRY:
        print(f"🧠 [Thought] Using tool: {tool_name} with args {args}")
        tool_result = execute_tool(tool_name, args)
        print(f"🔍 [DEBUG] Tool Result: {repr(tool_result)}")

        direct_return_tools = {
            'get_system_health',
            'get_running_processes',
            'get_account_balance',
            'check_mt5_status',
            'recall_memory',
            'create_and_execute_skill',
            'execute_generated_code',
            'list_apps',
            'get_installed_apps',
            'list_directory',
            'disk_usage',
            'get_network_info',
            'get_network_interfaces',
            'get_logs',
            'get_forex_news',
            'get_market_calendar',
        }

        if tool_name in direct_return_tools:
            conv_save(session_id, user_input, tool_result)
            return tool_result

        reflection_messages = messages + [
            {"role": "assistant", "content": raw_response},
            {"role": "user", "content": f"[System Output from {tool_name}]: {tool_result}. Now reply naturally to the user based on this result."}
        ]
        final_response = query_llm(reflection_messages, temperature=0.7)
        if final_response is None:
            final_response = "I have the result, but I need another moment to explain it clearly."
        conv_save(session_id, user_input, final_response)
        return final_response

    conv_save(session_id, user_input, raw_response)
    return raw_response