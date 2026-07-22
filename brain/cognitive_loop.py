import json
import re
from core import config
from brain.llm_interface import query_llm
from skills.memory.memory_tools import recall_facts
from brain.memory_manager import save_fact_to_db

def extract_facts_silently(user_input: str):
    """Silently extracts facts using a hyper-strict prompt and saves them directly."""
    extraction_prompt = f"""
    You are a strict fact-extraction engine. Analyze the user's input below.
    If the user states a permanent fact about themselves, their preferences, environment, or relationships, extract it as a JSON object.
    If there are no new permanent facts, return EXACTLY and ONLY: {{}}
    
    STRICT RULES:
    - Output ONLY valid JSON. No markdown, no explanations.
    - Keys must be short, lowercase phrases (e.g., "name", "favorite dish", "girlfriend's name").
    - Values must be the specific detail.
    
    User input: "{user_input}"
    """
    
    try:
        # Temperature 0.0 forces deterministic, strict JSON output
        raw_content = query_llm([{"role": "user", "content": extraction_prompt}], temperature=0.0)
        print(f"🔍 [DEBUG] Extraction Raw: {repr(raw_content)}")
        
        clean_content = raw_content.replace("```json", "").replace("```", "").strip()
        json_match = re.search(r'\{.*\}', clean_content, re.DOTALL)
        json_str = json_match.group(0) if json_match else clean_content
        
        facts = json.loads(json_str)
        if isinstance(facts, dict) and len(facts) > 0:
            for key, value in facts.items():
                k = str(key).lower().strip()
                v = str(value).strip()
                # Clean up possessives for better database keys
                k = k.replace("mark's ", "").replace("my ", "").replace("your ", "").strip()
                save_fact_to_db(k, v)
                print(f"🧠 [Memory Update] Learned: '{k}' = '{v}'")
        else:
            print("🔍 [DEBUG] No facts extracted.")
    except Exception as e:
        print(f"⚠️ [DEBUG] Silent extraction failed: {e}")

def run_cognitive_loop(user_input: str) -> str:
    # 🔥 STEP 1: Silently extract and save any new facts in the background
    extract_facts_silently(user_input)
    
    # 🔥 STEP 2: Retrieve relevant memory (RAG)
    memory_check = recall_facts(query=user_input)
    has_memory = "don't have any information" not in memory_check.lower()
    
    # 🔥 STEP 3: Chat prompt (NO JSON required here, just natural conversation)
    system_prompt = f"""
    You are Angelique, a helpful, warm AI companion.
    
    RELEVANT MEMORY ABOUT THE USER:
    {memory_check if has_memory else "None. You do not know this yet."}
    
    CRITICAL RULES:
    1. ONLY use the facts provided in the RELEVANT MEMORY section above. 
    2. NEVER guess, assume, or hallucinate facts about the user. If the memory says "None", politely say you don't know yet.
    3. Reply with normal, friendly, conversational text. Do NOT output JSON or tool calls.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]

    # 🔥 STEP 4: Get natural response (Temperature 0.7 for creativity)
    raw_response = query_llm(messages, temperature=0.7)
    print(f"🔍 [DEBUG] Chat Response: {repr(raw_response)}")
    
    return raw_response