from brain.memory_manager import save_fact_to_db, search_facts_in_db, get_all_facts

def save_fact(**kwargs) -> str:
    """Saves a fact to the database, intelligently handling unpredictable LLM JSON formatting."""
    
    k = ""
    v = ""

    # 1. Ideal format: {"key": "name", "value": "Mark"}
    if 'key' in kwargs and 'value' in kwargs:
        k = str(kwargs['key']).lower().strip()
        v = str(kwargs['value']).strip()
        
    # 2. LLM hallucinated format: {"name": "Mark", "property": "favorite_dish", "value": ""}
    elif 'property' in kwargs:
        k = str(kwargs['property']).lower().strip()
        v = str(kwargs.get('value', kwargs.get('name', ''))).strip()
        
    # 3. LLM sentence format: {"fact": "Mark's favorite dish is unknown"}
    elif 'fact' in kwargs or 'fact_name' in kwargs:
        raw_fact = str(kwargs.get('fact') or kwargs.get('fact_name', ''))
        if " is " in raw_fact:
            k, v = raw_fact.split(" is ", 1)
            # Clean up the key (remove "Mark's " or "my ")
            k = k.replace("Mark's ", "").replace("my ", "").strip().lower()
            v = v.strip()
        else:
            k = raw_fact.strip().lower()
            v = "unknown"
            
    # 4. Fallback format: {"name": "Mark", "favorite_dish": ""}
    else:
        items = list(kwargs.items())
        if items:
            k = str(items[0][0]).lower().strip()
            v = str(items[0][1]).strip()
        else:
            return "I couldn't figure out what fact to save. Please be specific."
            
    if not k or k == 'unknown_fact':
        return "I couldn't figure out what fact to save. Please be specific."
        
    save_fact_to_db(k, v)
    return f"Fact saved successfully: {k} = {v}"

def recall_facts(**kwargs) -> str:
    """Performs semantic search, gathering all clues from the LLM's unpredictable JSON."""
    
    # Gather all keys and values to form a comprehensive search query
    search_parts = []
    for k, v in kwargs.items():
        search_parts.append(str(k))
        if v:
            search_parts.append(str(v))
            
    search_query = " ".join(search_parts).strip()
    
    if not search_query:
        return "I need to know what topic to search for."
        
    facts = search_facts_in_db(search_query)
    
    if not facts:
        return f"I don't have any information about '{search_query}' in my memory yet."
    
    # Format facts naturally for the user
    if len(facts) == 1:
        k, v = list(facts.items())[0]
        return f"I remember that your {k} is {v}."
    else:
        response = "Here's what I know:\n"
        for k, v in facts.items():
            response += f"- {k}: {v}\n"
        return response