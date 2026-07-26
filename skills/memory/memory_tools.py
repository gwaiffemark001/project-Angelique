# skills/memory/memory_tools.py
from brain.memory_manager import save_fact_to_db, get_facts_for_entity, semantic_search, get_connection, init_db

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
        response = f"📚 **Memory Search Results for '{query}':**\n"
        for result in semantic_results:
            imp = result.get('importance', 5)
            imp_emoji = "🔥" if imp >= 8 else "⭐" if imp >= 5 else "📌"
            ctx = f" | Context: {result['context']}" if result.get('context') else ""
            response += f"- {imp_emoji} [{imp}/10] {result['entity']}'s {result['key']}: {result['value']}{ctx}\n"
        return response

    # Step 2: Fall back to entity-based lookup
    known_entities = get_all_entities()
    
    # Handle Ambiguity: "What is my friend's favorite dish?"
    if "friend" in query and "which" not in query:
        friends = get_friends_list()
        valid_friends = [f for f in friends if f in known_entities]
        if len(valid_friends) > 1:
            return f"I have multiple friends in my memory: {', '.join(valid_friends)}. Which one are you asking about?"
        elif len(valid_friends) == 1:
            entity = valid_friends[0]
        else:
            return "I don't know any friends yet. Could you tell me about your friends?"
            
    # Dynamic Entity Matching
    matched_entities = [e for e in known_entities if e.lower() in query]
    if matched_entities:
        entity = matched_entities[0]
    else:
        entity = "User" 
        
    data = get_facts_for_entity(entity)
    
    if not data["current"] and not data["history"]:
        return f"I don't have any information about {entity} yet."
        
    response = f"Current facts about {entity} (sorted by importance):\n"
    for fact in data["current"]:
        imp = fact['importance']
        # Add an emoji based on importance
        imp_emoji = "🔥" if imp >= 8 else "⭐" if imp >= 5 else "📌"
        ctx = f" | Context: {fact['context']}" if fact['context'] else ""
        ts = fact['timestamp'].split(' ')[0] if fact['timestamp'] else "Unknown date"
        
        response += f"- {imp_emoji} [{imp}/10] {fact['key']}: {fact['value']} (Learned: {ts}){ctx}\n"
        
    if data["history"]:
        response += f"\nPast history for {entity}:\n"
        for item in data["history"]:
            response += f"- 🕰️ {item}\n"
            
    return response