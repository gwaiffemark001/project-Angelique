# skills/memory/memory_tools.py
import re
from brain.memory_manager import (
    save_fact_to_db,
    get_facts_for_entity,
    semantic_search,
    search_conversation_memory,
    get_connection,
    init_db,
    get_top_memory_facts,
)

NAME_KEYS = {"name", "full name", "first name", "last name", "legal name", "nickname"}
RELATIONSHIP_KEYWORDS = [
    "girlfriend", "boyfriend", "partner", "spouse", "wife", "husband",
    "friend", "colleague", "boss", "manager", "mother", "father", "mom", "dad"
]


def _format_memory_response(entity: str, key: str, value: str) -> str:
    label = str(key or "detail").strip().replace("_", " ").strip()
    label = re.sub(r"\s+", " ", label)
    label = re.sub(r"\b(my|your)\s+", "", label, flags=re.IGNORECASE)
    entity_label = str(entity or "").strip()
    if not label:
        return f"{value}."

    if label.endswith(" name") and len(label.split()) > 1:
        relation = " ".join(label.split()[:-1])
        label = f"{relation}'s name"

    if entity_label.lower() == "user" or not entity_label:
        return f"Your {label} is {value}."

    return f"{entity_label}'s {label} is {value}."


def _normalize_text(text: str) -> str:
    return (text or "").strip().lower()


def _query_has_first_person(query: str) -> bool:
    return bool(re.search(r"\b(my|me|mine)\b", query))


def _find_relationship_in_query(query: str) -> str | None:
    for rel in RELATIONSHIP_KEYWORDS:
        if re.search(rf"\b{re.escape(rel)}(?:s|'s)?\b", query):
            return rel
    return None


def _looks_like_real_name(value: str, relationship: str | None = None) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return False
    if normalized in {"unknown", "none", "not specified", "n/a"}:
        return False
    if relationship and normalized == relationship:
        return False
    return True


def _score_semantic_result(query: str, result: dict) -> int:
    query_terms = set(re.findall(r"\w+", query.lower()))
    key_terms = set(re.findall(r"\w+", str(result.get("key", "")).lower()))
    value_terms = set(re.findall(r"\w+", str(result.get("value", "")).lower()))

    score = int(result.get("importance", 5)) * 10
    score += len(query_terms & key_terms) * 20
    score += len(query_terms & value_terms) * 10

    if any(term in query_terms for term in {"name", "call", "nickname", "who"}) and "name" in key_terms:
        score += 25
    if any(term in query_terms for term in {"trade", "trading", "risk", "platform", "news", "confirmation", "recommendation", "entry", "stop", "tp", "sl"}):
        if key_terms & query_terms or value_terms & query_terms:
            score += 15

    if "user" == str(result.get("entity", "")).lower() and any(term in query_terms for term in {"my", "me", "mine"}):
        score += 5

    return score


def _pick_best_semantic_result(query: str, results: list[dict]) -> dict | None:
    if not results:
        return None

    normalized_query = _normalize_text(query)
    query_has_my = _query_has_first_person(normalized_query)
    query_relationship = _find_relationship_in_query(normalized_query)

    if query_has_my and "name" in normalized_query:
        user_name_results = [
            r for r in results
            if r.get("entity", "").lower() == "user" and (
                r.get("key", "").lower() in NAME_KEYS
                or "name" in r.get("key", "").lower()
            )
        ]
        if user_name_results:
            return max(user_name_results, key=lambda r: _score_semantic_result(normalized_query, r))

    if query_relationship:
        relationship_results = [
            r for r in results
            if query_relationship in r.get("key", "").lower()
            or query_relationship in r.get("value", "").lower()
            or query_relationship in r.get("entity", "").lower()
        ]
        if relationship_results:
            return max(relationship_results, key=lambda r: _score_semantic_result(normalized_query, r))

    scored = [(r, _score_semantic_result(normalized_query, r)) for r in results]
    scored = [item for item in scored if item[1] > 0]
    if scored:
        return max(scored, key=lambda item: item[1])[0]

    return results[0] if results else None


def _tokenize_query(query: str) -> set[str]:
    return set(re.findall(r"\w+", (query or "").lower()))


def _score_fallback_fact(query_terms: set[str], fact: dict) -> int:
    key = str(fact.get("key", "")).lower()
    value = str(fact.get("value", "")).lower()
    key_terms = set(re.findall(r"\w+", key))
    value_terms = set(re.findall(r"\w+", value))

    score = int(fact.get("importance", 5)) * 5
    score += len(query_terms & key_terms) * 15
    score += len(query_terms & value_terms) * 8

    if "name" in query_terms and "name" in key_terms:
        score += 25
        if key in NAME_KEYS:
            score += 20
    if "platform" in query_terms and "platform" in key_terms:
        score += 25
    if "risk" in query_terms and any(term in key_terms for term in {"risk", "ratio", "reward"}):
        score += 25
    if "trade" in query_terms and any(term in key_terms for term in {"recommend", "confirmation", "avoidance", "platform", "risk", "entry", "sl", "tp"}):
        score += 20
    if "confirmation" in query_terms and "confirmation" in key_terms:
        score += 30
    if "recommend" in query_terms and "recommend" in key_terms:
        score += 30
    if "avoidance" in query_terms and "avoidance" in key_terms:
        score += 30

    if "my" in query_terms or "me" in query_terms or "mine" in query_terms:
        if str(fact.get("entity", "")).lower() == "user":
            score += 5

    return score


def _find_best_fallback_fact(query: str, facts: list[dict]) -> dict | None:
    query_terms = _tokenize_query(query)
    if not query_terms or not facts:
        return None

    if "name" in query_terms:
        name_facts = [
            fact for fact in facts
            if str(fact.get("key", "")).lower() in NAME_KEYS
            or "name" in str(fact.get("key", "")).lower()
        ]
        if name_facts:
            return max(name_facts, key=lambda fact: (fact.get("importance", 5), _score_fallback_fact(query_terms, fact)))

    scored = [(fact, _score_fallback_fact(query_terms, fact)) for fact in facts]
    scored = [item for item in scored if item[1] > 0]
    if not scored:
        return None
    return max(scored, key=lambda item: item[1])[0]


def get_all_entities() -> list:
    """Dynamically fetches all known people/entities from the database."""
    init_db()
    conn = get_connection()
    cursor = conn.execute('SELECT DISTINCT entity FROM memory_log WHERE entity != "User"')
    entities = [row['entity'] for row in cursor.fetchall()]
    conn.close()
    return entities

def get_friends_list() -> list:
    """Dynamically fetches all known friends of the User."""
    init_db()
    conn = get_connection()
    cursor = conn.execute("SELECT value FROM memory_log WHERE entity = 'User' AND key = 'friend' AND is_active = 1")
    friends = [row['value'] for row in cursor.fetchall()]
    conn.close()
    return friends

def _parse_training_text(text: str) -> list[dict]:
    normalized = text.replace('\r', ' ').strip()
    facts: list[dict] = []

    def extract(pattern: str, key: str, context: str = 'core training'):
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            value = match.group(1).strip().rstrip('.').strip()
            if value:
                facts.append({
                    'person': 'User',
                    'key': key,
                    'value': value,
                    'importance': 10,
                    'context': context,
                })

    extract(r'my name is ([\w\s]+?)(?: or |\.|,| because| cause|$)', 'name')
    if re.search(r'call me master', normalized, re.IGNORECASE):
        facts.append({
            'person': 'User',
            'key': 'honorific',
            'value': 'master',
            'importance': 10,
            'context': 'core training',
        })
    extract(r'my primary trading platform is ([\w\s\-0-9]+?)(?:\.|,|$)', 'primary trading platform')
    extract(r'my (?:absolute )?maximum risk per trade is ([0-9]+(?:\.[0-9]+)?%?)', 'maximum risk per trade')
    extract(r'my minimum risk(?: to reward)?(?: ratio)?(?: is)? ([0-9]+:[0-9]+)', 'minimum risk to reward ratio')
    extract(r'i never enter a trade without a minimum ([0-9]+:[0-9]+) risk-to-reward ratio', 'minimum risk to reward ratio')
    extract(r'i do not trade ([^\.]+?)(?:\.|$)', 'trading avoidance policy')
    extract(r'you must always present trade recommendations in a structured format: ([^\.]+?)(?:\.|$)', 'trade recommendation format')
    if re.search(r'you must always ask for my explicit confirmation before executing any trade', normalized, re.IGNORECASE):
        facts.append({
            'person': 'User',
            'key': 'confirmation requirement',
            'value': 'explicit confirmation before executing any trade',
            'importance': 10,
            'context': 'core training',
        })

    # Relationship patterns: detect phrases like "my girlfriend is called X" or "my girlfriend is X".
    for rel in RELATIONSHIP_KEYWORDS:
        # my girlfriend is called NAME
        m = re.search(rf"my\s+{re.escape(rel)}\s+is\s+called\s+([\w\s]+?)(?:\.|,|$)", normalized, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip('.').strip()
            if _looks_like_real_name(val, relationship=rel):
                facts.append({'person': 'User', 'key': f'{rel} name', 'value': val, 'importance': 8, 'context': 'core training'})
                continue
        # my girlfriend is NAME
        m2 = re.search(rf"my\s+{re.escape(rel)}\s+is\s+([\w\s]+?)(?:\.|,|$)", normalized, re.IGNORECASE)
        if m2:
            val = m2.group(1).strip().rstrip('.').strip()
            if _looks_like_real_name(val, relationship=rel):
                facts.append({'person': 'User', 'key': f'{rel} name', 'value': val, 'importance': 8, 'context': 'core training'})
                continue
        # my girlfriend's name is NAME
        m3 = re.search(rf"my\s+{re.escape(rel)}(?:'s|s)?\s+name\s+is\s+([\w\s]+?)(?:\.|,|$)", normalized, re.IGNORECASE)
        if m3:
            val = m3.group(1).strip().rstrip('.').strip()
            if _looks_like_real_name(val, relationship=rel):
                facts.append({'person': 'User', 'key': f'{rel} name', 'value': val, 'importance': 8, 'context': 'core training'})
                continue
    # Assistant renaming: detect when the user gives the assistant a name (e.g., "your name is X", "you are called X", "from now on your name is X")
    assistant_patterns = [
        r"your name (?:from now onward|from now on|now onward|from now)? is ([\w\s]+?)(?:\.|,|$)",
        r"you are called ([\w\s]+?)(?:\.|,|$)",
        r"you will be called ([\w\s]+?)(?:\.|,|$)",
        r"call you ([\w\s]+?)(?:\.|,|$)",
        r"your new name is ([\w\s]+?)(?:\.|,|$)",
    ]
    for pat in assistant_patterns:
        m = re.search(pat, normalized, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip('.').strip()
            if _looks_like_real_name(val):
                facts.append({'person': 'Assistant', 'key': 'name', 'value': val, 'importance': 9, 'context': 'renaming'})
                # prefer the first match
                break

    return facts


def train_angelique(text: str) -> str:
    facts = _parse_training_text(text)
    if not facts:
        return "I did not detect any core training directives in that input."

    saved = []
    for fact in facts:
        save_fact_to_db(
            fact['person'],
            fact['key'],
            fact['value'],
            fact['importance'],
            fact['context'],
        )
        saved.append(fact)

    keys = ", ".join({fact['key'] for fact in saved})
    return f"Training complete. Memorized: {keys}."


def save_fact(**kwargs) -> str:
    """Saves facts, handling the new flat-list JSON format with importance and context."""
    facts_list = []
    
    if isinstance(kwargs, list):
        facts_list = kwargs
    elif 'facts' in kwargs and isinstance(kwargs['facts'], list):
        facts_list = kwargs['facts']
    elif 'person' in kwargs and 'key' in kwargs and 'value' in kwargs:
        facts_list = [kwargs]
    else:
        entity = kwargs.get('entity', 'User').strip()
        facts = kwargs.get('facts', {})
        for k, v in facts.items():
            facts_list.append({"person": entity, "key": k, "value": v})

    saved_log = []
    for item in facts_list:
        if not isinstance(item, dict):
            continue
            
        person = str(item.get('person', 'User')).strip()
        key = str(item.get('key', '')).lower().strip()
        value = str(item.get('value', '')).strip()
        importance = int(item.get('importance', 5))
        context = str(item.get('context', '')).strip()
        
        # Skip empty values or obvious hallucinated placeholders
        if not person or not key or value == "" or value.lower() == "unknown":
            continue
            
        # Clean up accidental possessives
        key = key.replace(f"{person.lower()}'s ", "").replace("my ", "").replace("your ", "").strip()
        
        save_fact_to_db(person, key, value, importance, context)
        saved_log.append(f"{person} / {key} = {value} (Importance: {importance}/10)")
        
    if not saved_log:
        return "No new valid facts extracted."
    return f"Saved: {', '.join(saved_log)}"

def _should_query_conversation_memory(query: str) -> bool:
    normalized = (query or "").strip().lower()
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
        "recall that",
        "recall when",
        "did i say",
        "did i tell you",
    )
    return any(phrase in normalized for phrase in conversation_phrases)


def recall_facts(**kwargs) -> str:
    """
    Dynamically resolves entities and formats memory with emotional/episodic context.
    Uses SEMANTIC SEARCH first (ChromaDB), then falls back to SQL if needed.
    """
    query = kwargs.get('query', '').lower()
    
    if not query:
        return "No query provided. What would you like to know?"

    # Step 1: Try semantic search (powerful, cross-entity)
    semantic_results = semantic_search(query, top_k=5)
    if semantic_results:
        best = _pick_best_semantic_result(query, [r for r in semantic_results if r.get('type', 'fact') == 'fact'])
        if best:
            return _format_memory_response(best.get('entity', ''), best.get('key', 'detail'), best.get('value', ''))

    if _should_query_conversation_memory(query):
        conversation_results = search_conversation_memory(query, top_k=3)
        if conversation_results:
            snippets = []
            for item in conversation_results:
                text = item.get('value', '')
                if not text:
                    continue
                truncated = text if len(text) <= 250 else text[:247] + '...'
                snippets.append(truncated)
            if snippets:
                return " | ".join(snippets)

    if semantic_results:
        response = f"📚 **Memory Search Results for '{query}':**\n"
        for result in semantic_results:
            imp = result.get('importance', 5)
            imp_emoji = "🔥" if imp >= 8 else "⭐" if imp >= 5 else "📌"
            ctx = f" | Context: {result['context']}" if result.get('context') else ""
            response += f"- {imp_emoji} [{imp}/10] {result['entity']}'s {result['key']}: {result['value']}{ctx}\n"
        return response

    # Step 2: Fall back to entity-based lookup
    known_entities = get_all_entities()

    matched_entities = [e for e in known_entities if e.lower() in query]
    if matched_entities:
        entity = matched_entities[0]
    else:
        entity = "User"
        
    data = get_facts_for_entity(entity)
    
    if not data["current"] and not data["history"]:
        return f"I don't have any information about {entity} yet."

    query_relationship = _find_relationship_in_query(query)
    query_has_my = _query_has_first_person(query)
    normalized_query = query.lower()
    query_terms = _tokenize_query(query)

    if query_has_my and "name" in normalized_query:
        name_facts = [
            fact for fact in data["current"]
            if str(fact.get('key', '')).lower() in NAME_KEYS
            or "name" in str(fact.get('key', '')).lower()
        ]
        if name_facts:
            best = max(name_facts, key=lambda fact: (fact.get('importance', 5), _score_fallback_fact(query_terms, fact)))
            return _format_memory_response(entity, best.get('key', 'detail'), best.get('value', ''))

    if query_relationship:
        relationship_matches = [
            fact for fact in data["current"]
            if query_relationship in str(fact.get('key', '')).lower()
            or query_relationship in str(fact.get('value', '')).lower()
        ]
        if relationship_matches:
            best = max(relationship_matches, key=lambda fact: (fact.get('importance', 5), _score_fallback_fact(query_terms, fact)))
            return _format_memory_response(entity, best.get('key', 'detail'), best.get('value', ''))
        return f"I don't have any information about your {query_relationship} yet."

    fallback_fact = _find_best_fallback_fact(query, data["current"])
    if fallback_fact:
        return _format_memory_response(entity, fallback_fact.get('key', 'detail'), fallback_fact.get('value', ''))

    response = f"Current facts about {entity} (sorted by importance):\n"
    for fact in data["current"]:
        imp = fact['importance']
        imp_emoji = "🔥" if imp >= 8 else "⭐" if imp >= 5 else "📌"
        ctx = f" | Context: {fact['context']}" if fact['context'] else ""
        ts = fact['timestamp'].split(' ')[0] if fact['timestamp'] else "Unknown date"
        response += f"- {imp_emoji} [{imp}/10] {fact['key']}: {fact['value']} (Learned: {ts}){ctx}\n"
    
    if data["history"]:
        response += f"\nPast history for {entity}:\n"
        for item in data["history"]:
            response += f"- 🕰️ {item}\n"
            
    return response