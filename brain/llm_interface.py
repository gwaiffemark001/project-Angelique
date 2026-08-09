import json
import re
import requests
import socket
from typing import Any, Optional
from datetime import datetime
import os
from core import config


def _is_online() -> bool:
    try:
        with socket.create_connection((config.NETWORK_CHECK_HOST, config.NETWORK_CHECK_PORT), timeout=1):
            return True
    except Exception:
        return False

def query_llm(messages: list, temperature: float = 0.7) -> str:
    """Core function to query LLMs with a professional, high-reliability fallback chain."""

    def _try_ollama_model(model_name: str) -> Optional[str]:
        try:
            response = requests.post(
                f"{config.OLLAMA_BASE_URL}/api/chat",
                json={"model": model_name, "messages": messages, "stream": False},
                timeout=45
            )
            if response.status_code == 200:
                return response.json()["message"]["content"]
        except Exception as e:
            print(f"⚠️ [LLM] Ollama model '{model_name}' failed: {e}")
        return None

    # Prefer the installed local models when the network is unavailable.
    if not _is_online() and "ollama" in config.API_PRIORITY:
        for model_name in config.OLLAMA_MODEL_CANDIDATES:
            if not model_name:
                continue
            result = _try_ollama_model(model_name)
            if result:
                return result
    
    # 1. Try NVIDIA NIM (Highest quality, lowest latency)
    if "nvidia" in config.API_PRIORITY and config.NVIDIA_API_KEY:
        try:
            response = requests.post(
                config.NVIDIA_API_URL,
                headers={
                    "Authorization": f"Bearer {config.NVIDIA_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={"model": config.NVIDIA_MODEL, "messages": messages, "temperature": temperature},
                timeout=15
            )
            if response.status_code == 200 and "choices" in response.json():
                return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"⚠️ [LLM] NVIDIA failed: {e}")

    # 2. Try OpenRouter (Excellent for JSON tool calling)
    if "openrouter" in config.API_PRIORITY and config.OPENROUTER_API_KEY:
        try:
            response = requests.post(
                f"{config.OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": config.API_DEFAULT_REFERER,
                    "X-Title": config.API_CLIENT_TITLE
                },
                json={"model": config.OPENROUTER_MODEL, "messages": messages, "temperature": temperature},
                timeout=20
            )
            if response.status_code == 200 and "choices" in response.json():
                return response.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"⚠️ [LLM] OpenRouter failed: {e}")

    # 3. Try Bluesminds
    if "bluesminds" in config.API_PRIORITY and config.BLUESMINDS_API_KEY:
        try:
            response = requests.post(
                f"{config.BLUESMINDS_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.BLUESMINDS_API_KEY}", "Content-Type": "application/json"},
                json={"model": config.BLUESMINDS_MODEL, "messages": messages, "temperature": temperature},
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
                f"{config.GEMINI_BASE_URL}/models/{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}",
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
        for model_name in config.OLLAMA_MODEL_CANDIDATES:
            if not model_name:
                continue
            result = _try_ollama_model(model_name)
            if result:
                return result

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
        log_dir = config.LOG_DIR
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(str(log_dir), 'llm_extractions.log')
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