import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from core import config

CONVERSATION_HISTORY = Path(config.DATA_DIR) / "conversations"
CONVERSATION_HISTORY.mkdir(parents=True, exist_ok=True)

SESSION_CONTEXT = {}
SESSION_CLOSED = set()


def _session_is_closed(session_id: str) -> bool:
    return session_id in SESSION_CLOSED


def save_conversation(session_id: str, user_message: str, agent_response: str) -> str:
    if _session_is_closed(session_id):
        return "⚪ Session closed; conversation updates skipped"
    try:
        history_file = CONVERSATION_HISTORY / f"{session_id}.json"
        history = []
        if history_file.exists():
            with open(history_file, "r") as f:
                history = json.load(f)

        user_text = user_message if isinstance(user_message, str) else str(user_message)
        agent_text = agent_response if isinstance(agent_response, str) else json.dumps(agent_response, ensure_ascii=False)

        entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "user": user_text,
            "agent": agent_text,
        }
        history.append(entry)

        if len(history) > 500:
            history = history[-500:]

        with open(history_file, "w") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        SESSION_CONTEXT[session_id] = {
            "last_user": user_text,
            "last_response": agent_text,
            "turn_count": len(history),
            "updated_at": entry["timestamp"],
            "pending_followup": bool(re.search(r'\?|\b(would you like|do you want|should i|shall i|can i|need me to|want me to)\b', agent_text.lower())),
        }

        try:
            from brain.memory_manager import save_conversation_memory
            save_conversation_memory(session_id, "User", user_text, importance=5, context="conversation")
            save_conversation_memory(session_id, "Angelique", agent_text, importance=5, context="conversation")
        except Exception:
            pass

        return f"✅ Conversation saved ({len(history)} turns)"
    except Exception as e:
        return f"❌ Failed to save conversation: {e}"


def get_conversation_history(session_id: str, limit: int = 20) -> list:
    try:
        history_file = CONVERSATION_HISTORY / f"{session_id}.json"
        if not history_file.exists():
            return []
        with open(history_file, "r") as f:
            history = json.load(f)
        return history[-limit:]
    except Exception:
        return []


def get_session_context(session_id: str = "default") -> dict:
    if session_id in SESSION_CONTEXT:
        return SESSION_CONTEXT[session_id]
    history = get_conversation_history(session_id)
    if history:
        last = history[-1]
        last_user = last.get("user", "")
        if not isinstance(last_user, str):
            last_user = str(last_user)

        last_response = last.get("agent", "")
        if not isinstance(last_response, str):
            try:
                last_response = json.dumps(last_response, ensure_ascii=False)
            except Exception:
                last_response = str(last_response)

        return {
            "last_user": last_user,
            "last_response": last_response,
            "turn_count": len(history),
            "updated_at": last.get("timestamp", ""),
            "pending_followup": bool(re.search(r'\?|\b(would you like|do you want|should i|shall i|can i|need me to|want me to)\b', last_response.lower())),
        }
    return {"turn_count": 0, "last_user": "", "last_response": "", "pending_followup": False}


def summarize_context(session_id: str = "default") -> str:
    context = get_session_context(session_id)
    history = get_conversation_history(session_id, limit=10)
    if not history:
        return "No conversation history available. This is a fresh session."

    summary_parts = [f"Session has {context['turn_count']} turns."]

    topics = set()
    for entry in history:
        user = entry.get("user", "")
        words = re.findall(r'\b\w{4,}\b', user.lower())
        topics.update(words[:5])

    if topics:
        summary_parts.append(f"Recent topics include: {', '.join(sorted(topics)[:10])}")

    last_user = context.get("last_user", "")
    if last_user:
        summary_parts.append(f"Last user message: \"{last_user[:200]}\"")

    return " ".join(summary_parts)


def remember(context: dict, key: str, value: str, importance: int = 5):
    try:
        from brain.memory_manager import save_fact_to_db

        entity = context.get("user", "User")
        save_fact_to_db(entity, key, value, importance=importance, context="conversation")
        return f"🧠 Remembered: '{key}' = '{value}' (importance: {importance})"
    except Exception as e:
        return f"⚠️ Could not save to memory: {e}"


def recall(context: dict, query: str) -> str:
    try:
        from brain.memory_manager import recall_facts
        return recall_facts(query=query)
    except Exception as e:
        return f"⚠️ Recall failed: {e}"


def clear_session(session_id: str = "default") -> str:
    SESSION_CONTEXT.pop(session_id, None)
    SESSION_CLOSED.discard(session_id)
    history_file = CONVERSATION_HISTORY / f"{session_id}.json"
    if history_file.exists():
        history_file.unlink()
    return f"🗑️ Session '{session_id}' cleared."


def close_session(session_id: str = "default") -> str:
    SESSION_CLOSED.add(session_id)
    SESSION_CONTEXT.pop(session_id, None)
    return f"🔒 Session '{session_id}' closed."


def is_session_closed(session_id: str = "default") -> bool:
    return _session_is_closed(session_id)


def list_sessions() -> list:
    if not CONVERSATION_HISTORY.exists():
        return []
    return sorted([f.stem for f in CONVERSATION_HISTORY.glob("*.json")], reverse=True)


def new_session() -> str:
    session_id = f"session_{int(time.time())}"
    SESSION_CONTEXT[session_id] = {
        "last_user": "",
        "last_response": "",
        "turn_count": 0,
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "pending_followup": False,
    }
    return session_id


def handle_user_message(session_id: str, user_message: str) -> dict:
    """High-level handler: routes user message through cognitive resolver,
    saves conversation, and returns structured result.

    Returns: { 'session_id', 'source', 'answer', 'details' }
    """
    try:
        from brain.cognitive_loop import resolve_user_query
    except Exception:
        return {"error": "Cognitive resolver unavailable"}

    result = resolve_user_query(user_message, session_id=session_id)
    # Save conversation (best-effort)
    try:
        agent_text = result.get("answer") if isinstance(result, dict) else str(result)
        save_conversation(session_id, user_message, agent_text)
    except Exception:
        pass

    return {"session_id": session_id, "source": result.get("source"), "answer": result.get("answer"), "details": result.get("details", {})}