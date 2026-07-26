# brain/cognitive_loop.py
import json
import re
from brain.llm_interface import query_llm, extract_json_from_text
from brain.memory_manager import save_fact_to_db
from brain.heuristic_engine import extract_command_heuristically
from core.tools import TOOL_REGISTRY, execute_tool
from skills.memory.memory_tools import recall_facts
from skills.voice.wake_word_system import is_awake, activation_protocol

def nlp_to_tool_mapping(text: str):
    """
    Comprehensive deterministic routing using heuristic engine.
    Replaces partial hardcoded mappings with full coverage.
    """
    tool_name, args = extract_command_heuristically(text)
    return tool_name, args

def extract_facts_silently(user_input: str):
    """Silently extracts facts, scoring their emotional importance and episodic context."""
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

def run_cognitive_loop(user_input: str) -> str:
    # 0. CHECK WAKE-WORD STATUS
    if not is_awake():
        # Still listen for activation trigger
        if "angelique" in user_input.lower():
            print("🎤 Angelique wake-word detected. Awaiting clap confirmation...")
            # Note: In actual usage, we'd need audio samples for clap detection
            # For now, if "angelique" is mentioned, we activate
            from skills.voice.wake_word_system import wake_up
            wake_up()
            return "🌟 I'm awake! How can I help?"
        else:
            return "😴 I'm sleeping. Say 'Angelique' to wake me up."
    
    # 1. Silent memory extraction
    extract_facts_silently(user_input)

    # 2. Retrieve relevant memory
    memory_check = recall_facts(query=user_input)
    has_memory = "don't have any information" not in memory_check.lower() and "no new valid facts" not in memory_check.lower()
    memory_text = memory_check if has_memory else "None. You do not know this yet."

    tools_schema = json.dumps({name: info["description"] for name, info in TOOL_REGISTRY.items()}, indent=2)

    system_prompt = (
        "You are Angelique, a highly advanced, self-evolving autonomous AI companion.\n\n"
        f"You have access to the following tools:\n{tools_schema}\n\n"
        f"RELEVANT MEMORY ABOUT THE USER (Sorted by emotional importance):\n{memory_text}\n\n"
        "CORE DIRECTIVES:\n"
        "1. ACTION REQUESTS: If the user asks you to do something, you MUST reply with ONLY a JSON object for the tool.\n"
        "   Format: {\"tool\": \"tool_name\", \"args\": {\"param1\": \"value1\"}}\n"
        "2. CONVERSATION: If the user is just chatting, reply naturally. DO NOT output JSON.\n"
        "3. MEMORY USAGE: Use the RELEVANT MEMORY to personalize your responses. Notice the importance scores (🔥 is high, 📌 is low). Prioritize highly important facts.\n"
        "4. NEVER hallucinate facts. Only use facts present in RELEVANT MEMORY.\n\n"
        "EXAMPLES:\n"
        "User: open Firefox\n"
        "Assistant: {\"tool\": \"open_app\", \"args\": {\"app_name\": \"Firefox\"}}\n\n"
        "User: what is your name?\n"
        "Assistant: I am Angelique, your assistant. How can I help?\n"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]

    raw_response = query_llm(messages, temperature=0.0)
    if raw_response is None:
        return "I'm having a little trouble connecting to my brain right now."

    decision = extract_json_from_text(raw_response)

    tool_name = None
    args = {}
    
    if not decision:
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

    if args is None: args = {}

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
            'execute_generated_code'
        }

        if tool_name in direct_return_tools:
            return tool_result

        reflection_messages = messages + [
            {"role": "assistant", "content": raw_response},
            {"role": "user", "content": f"[System Output from {tool_name}]: {tool_result}. Now reply naturally to the user based on this result."}
        ]
        return query_llm(reflection_messages, temperature=0.7)

    return raw_response