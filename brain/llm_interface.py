import json
import re
import requests
from typing import Any, Optional
from datetime import datetime
import os
from core import config

def query_llm(messages: list, temperature: float = 0.7) -> str:
    """Core function to query LLMs with a professional, high-reliability fallback chain."""
    
    # 1. Try OpenRouter (Best for strict JSON tool calling)
    if "openrouter" in config.API_PRIORITY and config.OPENROUTER_API_KEY:
        try:
            response = requests.post(
                f"{config.OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost",
                    "X-Title": "Angelique AI"
                },
                # Qwen 2.5 Coder 32B is exceptionally reliable at JSON formatting
                json={"model": "qwen/qwen-2.5-coder-32b-instruct", "messages": messages, "temperature": temperature},
                timeout=20
            )
            if response.status_code == 200 and "choices" in response.json():
                return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"⚠️ [LLM] OpenRouter failed: {e}")

    # 2. Try NVIDIA NIM (High-quality Llama 3.1 70B)
    if "nvidia" in config.API_PRIORITY and config.NVIDIA_API_KEY:
        try:
            response = requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.NVIDIA_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={"model": "meta/llama-3.1-70b-instruct", "messages": messages, "temperature": temperature},
                timeout=20
            )
            if response.status_code == 200 and "choices" in response.json():
                return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"⚠️ [LLM] NVIDIA failed: {e}")

    # 3. Try Bluesminds
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

    # 4. Try Gemini
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
            
            payload: dict[str, Any] = {"contents": gemini_contents}
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

    # 5. Try Ollama (Local Fallback)
    if "ollama" in config.API_PRIORITY:
        try:
            response = requests.post(
                f"{config.OLLAMA_BASE_URL}/api/chat",
                json={"model": config.PRIMARY_MODEL, "messages": messages, "stream": False},
                timeout=45
            )
            if response.status_code == 200:
                return response.json()["message"]["content"]
        except Exception as e:
            print(f"⚠️ [LLM] Ollama failed: {e}")

    return "I'm having a little trouble connecting to my brain right now."

def extract_json_from_text(text: Optional[str]) -> Any:
    """Safely extracts JSON from LLM output, ignoring conversational yapping.

    Returns an empty dict when no valid JSON object/list is found or if input is None.
    """
    if text is None:
        parsed = {}
    else:
        # Try to unwrap string-encoded JSON responses like '"{...}"' or single-quoted variants
        try:
            loaded = json.loads(text)
            if isinstance(loaded, str):
                text = loaded
        except Exception:
            try:
                # Handle single-quoted JSON by normalizing quotes before parsing
                loaded = json.loads(text.replace("'", '"'))
                if isinstance(loaded, str):
                    text = loaded
            except Exception:
                pass

        clean_content = text.replace("```json", "").replace("```", "").strip()

        # Prefer JSON list or object if present
        list_match = re.search(r"\[.*\]", clean_content, re.DOTALL)
        obj_match = re.search(r"\{.*\}", clean_content, re.DOTALL)

        if list_match:
            json_str = list_match.group(0)
        elif obj_match:
            json_str = obj_match.group(0)
        else:
            json_str = clean_content

        json_str = json_str.replace('{""}', '{}').replace("''", '""')

        try:
            parsed = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            parsed = {}

    # Logging: append raw input and parsed result to data/logs/llm_extractions.log
    try:
        log_dir = os.path.join(os.getcwd(), 'data', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, 'llm_extractions.log')
        with open(log_path, 'a', encoding='utf-8') as f:
            entry = {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'raw': (text if text is not None else ''),
                'parsed': parsed
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return parsed