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

def _ordered_ollama_candidates() -> list[str]:
    seen = set()
    ordered = []
    for model_name in config.OLLAMA_MODEL_CANDIDATES:
        candidate = (model_name or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered


def _try_ollama_model(model_name: str, messages: list) -> Optional[str]:
    try:
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={"model": model_name, "messages": messages, "stream": False},
            timeout=15,
        )
        if response.status_code == 200:
            j = response.json()
            # Ollama may return either {'message': {'content': '...'}} or {'content': '...'} depending on version
            if isinstance(j, dict):
                if "message" in j and isinstance(j["message"], dict) and "content" in j["message"]:
                    content = j["message"]["content"]
                    return content if isinstance(content, str) and content.strip() else None
                if "content" in j and isinstance(j["content"], str):
                    return j["content"] if j["content"].strip() else None
            # Fallback: try to extract nested content keys
            try:
                # attempt common keyed extraction
                return j.get("choices", [])[0].get("message", {}).get("content")
            except Exception:
                return None
    except Exception as e:
        print(f"⚠️ [LLM] Ollama model '{model_name}' failed: {e}")
    return None


def query_llm(messages: list, temperature: float = 0.7) -> str:
    """Query cloud providers online, then Ollama; use Ollama directly offline."""
    if not _is_online():
        result = _call_ollama(messages)
        if result:
            return result
        print("[LLM] Offline mode: all local Ollama candidates failed; see the model diagnostics above.")
        return "I'm having a little trouble connecting to my brain right now."

    ordered_providers = [
        provider.strip().lower()
        for provider in (config.API_PRIORITY or [])
        if provider and provider.strip() and provider.strip().lower() != "ollama"
    ]
    if not ordered_providers:
        ordered_providers = ["openrouter", "nvidia", "bluesminds", "gemini"]

    provider_handlers = {
        "nvidia": lambda: _call_nvidia(messages, temperature),
        "openrouter": lambda: _call_openrouter(messages, temperature),
        "bluesminds": lambda: _call_bluesminds(messages, temperature),
        "gemini": lambda: _call_gemini(messages, temperature),
        "ollama": lambda: _call_ollama(messages),
    }

    for provider in ordered_providers:
        if provider not in provider_handlers:
            continue
        try:
            result = provider_handlers[provider]()
            if result:
                return result
        except Exception as exc:
            print(f"⚠️ [LLM] {provider} failed: {exc}")

    result = _call_ollama(messages)
    if result:
        return result

    print("[LLM] Cloud providers and all local Ollama candidates failed; see the provider diagnostics above.")
    return "I'm having a little trouble connecting to my brain right now."


def _call_nvidia(messages: list, temperature: float) -> Optional[str]:
    if not getattr(config, "NVIDIA_API_KEY", ""):
        return None
    response = requests.post(
        config.NVIDIA_API_URL,
        headers={
            "Authorization": f"Bearer {config.NVIDIA_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"model": config.NVIDIA_MODEL, "messages": messages, "temperature": temperature},
        timeout=12,
    )
    if response.status_code == 200 and "choices" in response.json():
        return response.json()["choices"][0]["message"]["content"]
    return None


def _call_openrouter(messages: list, temperature: float) -> Optional[str]:
    if not getattr(config, "OPENROUTER_API_KEY", ""):
        return None
    response = requests.post(
        f"{config.OPENROUTER_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": config.API_DEFAULT_REFERER,
            "X-Title": config.API_CLIENT_TITLE,
        },
        json={"model": config.OPENROUTER_MODEL, "messages": messages, "temperature": temperature},
        timeout=12,
    )
    if response.status_code == 200 and "choices" in response.json():
        return response.json()["choices"][0]["message"]["content"]
    return None


def _call_bluesminds(messages: list, temperature: float) -> Optional[str]:
    if not getattr(config, "BLUESMINDS_API_KEY", ""):
        return None
    response = requests.post(
        f"{config.BLUESMINDS_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {config.BLUESMINDS_API_KEY}", "Content-Type": "application/json"},
        json={"model": config.BLUESMINDS_MODEL, "messages": messages, "temperature": temperature},
        timeout=12,
    )
    if response.status_code == 200 and "choices" in response.json():
        return response.json()["choices"][0]["message"]["content"]
    return None


def _call_gemini(messages: list, temperature: float) -> Optional[str]:
    if not getattr(config, "GEMINI_API_KEY", ""):
        return None
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
        timeout=12,
    )
    if response.status_code == 200 and "candidates" in response.json():
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    return None


def _call_ollama(messages: list) -> Optional[str]:
    for model_name in _ordered_ollama_candidates():
        result = _try_ollama_model(model_name, messages)
        if result:
            return result
    return None

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