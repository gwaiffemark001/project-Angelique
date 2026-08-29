import json
import re
import requests
import socket
from typing import Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import os
import time
from core import config

_OLLAMA_DISCOVERY_CACHE = {"at": 0.0, "models": []}


def _is_online() -> bool:
    """Fast connectivity probe that does not rely on DNS/53 egress being allowed.

    The previous check used a raw TCP connection to 8.8.8.8:53. On many
    networks that port is blocked even though normal HTTPS internet access is
    working, which incorrectly forced Angelique into offline/local mode.
    """
    probes = (
        "https://www.google.com/generate_204",
        "https://www.cloudflare.com/cdn-cgi/trace",
    )
    for url in probes:
        try:
            response = requests.get(
                url,
                timeout=0.8,
                allow_redirects=False,
                headers={"User-Agent": getattr(config, "DEFAULT_HTTP_USER_AGENT", "Angelique/1.0")},
            )
            if response.status_code < 500:
                return True
        except Exception:
            continue
    try:
        with socket.create_connection((config.NETWORK_CHECK_HOST, config.NETWORK_CHECK_PORT), timeout=0.4):
            return True
    except Exception:
        return False

def _discover_ollama_models() -> list[str]:
    now = time.monotonic()
    if now - float(_OLLAMA_DISCOVERY_CACHE.get("at", 0.0)) < 30.0:
        return list(_OLLAMA_DISCOVERY_CACHE.get("models", []))
    try:
        response = requests.get(
            f"{config.OLLAMA_BASE_URL}/api/tags",
            timeout=min(float(getattr(config, "OLLAMA_REQUEST_TIMEOUT_S", 8)), 3.0),
        )
        if not response.ok:
            return []
        payload = response.json()
        models = payload.get("models", []) if isinstance(payload, dict) else []
        discovered = [
            str(item.get("name", "")).strip()
            for item in models
            if isinstance(item, dict) and str(item.get("name", "")).strip()
        ]
        _OLLAMA_DISCOVERY_CACHE.update({"at": now, "models": discovered})
        return discovered
    except Exception:
        _OLLAMA_DISCOVERY_CACHE.update({"at": now, "models": []})
        return []


def _ordered_ollama_candidates() -> list[str]:
    configured = list(getattr(config, "OLLAMA_MODEL_CANDIDATES", []) or [])
    discovered = _discover_ollama_models()
    preferred = []
    for candidate in (config.CODER_MODEL, config.PRIMARY_MODEL, config.LOCAL_FALLBACK_MODEL):
        if candidate:
            preferred.append(candidate)
    # Prefer configured models, then explicit primary/coder/fallback models,
    # then any models discovered from the running Ollama server.
    seen = set()
    ordered = []
    discovered_cf = {m.casefold(): m for m in discovered}
    for model_name in configured + preferred + discovered:
        candidate = (model_name or "").strip()
        if not candidate:
            continue
        # If an env alias is missing but a discovered tag shares its base name,
        # use the actual Ollama tag (e.g. qwen2.5-coder:latest).
        actual = discovered_cf.get(candidate.casefold())
        if not actual:
            base = candidate.split(":", 1)[0].casefold()
            actual = next((m for m in discovered if m.split(":",1)[0].casefold() == base), None)
        candidate = actual or candidate
        if candidate in seen:
            continue
        if discovered and actual is None:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered[:3]


def _try_ollama_model(model_name: str, messages: list) -> Optional[str]:
    try:
        timeout = float(getattr(config, "OLLAMA_REQUEST_TIMEOUT_S", 8.0))
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={"model": model_name, "messages": messages, "stream": False, "options": {"temperature": 0.2}},
            timeout=max(2.0, min(timeout, 8.0)),
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
    ] or ["openrouter", "nvidia", "bluesminds", "gemini"]

    provider_handlers = {
        "nvidia": lambda: _call_nvidia(messages, temperature),
        "openrouter": lambda: _call_openrouter(messages, temperature),
        "bluesminds": lambda: _call_bluesminds(messages, temperature),
        "gemini": lambda: _call_gemini(messages, temperature),
    }

    # Online: race configured cloud providers so one slow/dead provider cannot
    # stall Angelique behind a chain of 12-second requests.
    futures = {}
    pool = ThreadPoolExecutor(max_workers=min(4, max(1, len(ordered_providers))))
    try:
        for provider in ordered_providers:
            handler = provider_handlers.get(provider)
            if handler:
                futures[pool.submit(handler)] = provider
        try:
            for future in as_completed(futures, timeout=10):
                provider = futures[future]
                try:
                    result = future.result()
                    if result:
                        return result
                except Exception as exc:
                    print(f"⚠️ [LLM] {provider} failed: {exc}")
        except TimeoutError:
            pass
    finally:
        # Do not wait for a dead cloud provider before falling back locally.
        pool.shutdown(wait=False, cancel_futures=True)

    # Online fallback: choose one installed local model, not every guessed alias.
    result = _call_ollama(messages)
    if result:
        return result
    print("[LLM] Cloud providers and local Ollama fallback failed.")
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
    candidates = _ordered_ollama_candidates()
    if not candidates:
        return None

    # Do not load several local models simultaneously. Racing a 3B model
    # against a 7B coder model can thrash RAM/VRAM and make both slower.
    # Pick the first installed candidate and keep it warm for subsequent turns.
    model = candidates[0]
    try:
        timeout = max(2.0, float(getattr(config, "OLLAMA_REQUEST_TIMEOUT_S", 8.0)))
        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": "15m",
                "options": {"temperature": 0.2},
            },
            timeout=min(timeout, 12.0),
        )
        if response.status_code == 200:
            payload = response.json()
            message = payload.get("message") if isinstance(payload, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content.strip():
                return content
    except Exception as exc:
        print(f"⚠️ [LLM] Ollama model '{model}' failed: {exc}")

    # One bounded fallback only if the preferred model really failed.
    for fallback in candidates[1:2]:
        result = _try_ollama_model(fallback, messages)
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