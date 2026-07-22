import json
import re
import requests
from typing import Any, Dict
from core import config

def query_llm(messages: list, temperature: float = 0.7) -> str:
    """Core function to query LLMs with a professional fallback chain."""
    
    # 1. Try Ollama (Local)
    if "ollama" in config.API_PRIORITY:
        try:
            response = requests.post(
                config.OLLAMA_URL,
                json={"model": config.OLLAMA_MODEL, "messages": messages, "stream": False},
                timeout=45
            )
            if response.status_code == 200:
                return response.json()["message"]["content"]
        except Exception as e:
            print(f"️ [LLM] Ollama failed: {e}")

    # 2. Try Bluesminds (Cloud Fallback 1)
    if "bluesminds" in config.API_PRIORITY and config.BLUESMINDS_API_KEY:
        try:
            response = requests.post(
                f"{config.BLUESMINDS_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.BLUESMINDS_API_KEY}", "Content-Type": "application/json"},
                json={"model": "meta/llama-3.1-8b-instruct", "messages": messages, "temperature": temperature},
                timeout=20
            )
            if response.status_code == 200 and "choices" in response.json():
                return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"⚠️ [LLM] Bluesminds failed: {e}")

    # 3. Try Gemini (Cloud Fallback 2)
    if "gemini" in config.API_PRIORITY and config.GEMINI_API_KEY:
        try:
            gemini_contents = []
            last_role = None
            system_prompt = ""
            for msg in messages:
                if msg["role"] == "system":
                    system_prompt = msg["content"]
                    continue
                current_role = "user" if msg["role"] == "user" else "model"
                if current_role == last_role:
                    gemini_contents[-1]["parts"][0]["text"] += " " + msg["content"]
                else:
                    gemini_contents.append({"role": current_role, "parts": [{"text": msg["content"]}]})
                    last_role = current_role
            
            payload: Dict[str, Any] = {"contents": gemini_contents}
            if system_prompt:
                payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
                
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={config.GEMINI_API_KEY}",
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=20
            )
            if response.status_code == 200 and "candidates" in response.json():
                return response.json()["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            print(f"⚠️ [LLM] Gemini failed: {e}")

    return "I'm having a little trouble connecting to my brain right now."

def extract_json_from_text(text: str) -> dict:
    """Safely extracts JSON from LLM output, ignoring conversational yapping and fixing typos."""
    clean_content = text.replace("```json", "").replace("```", "").strip()
    json_match = re.search(r'\{.*\}', clean_content, re.DOTALL)
    
    if json_match:
        json_str = json_match.group(0)
    else:
        json_str = clean_content
        
    # Fix common LLM JSON typos (like empty keys)
    json_str = json_str.replace('{""}', '{}').replace("''", '""')
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {}