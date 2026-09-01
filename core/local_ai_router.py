"""Local tri-model router for Angelique.

Qwen Coder handles strict fact extraction, Nomic handles embeddings, and
Llama handles natural-language responses.  The module is deliberately built
on HTTP requests to Ollama so it remains usable even when the optional
``ollama`` Python package is not installed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import requests

from core import config


FACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "extracted_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity": {"type": "string"},
                    "fact": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["entity", "fact", "category"],
                "additionalProperties": False,
            },
        },
        "search_query": {"type": "string"},
    },
    "required": ["extracted_facts", "search_query"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ModelState:
    installed: tuple[str, ...]
    coder: str | None
    embedder: str | None
    responder: str | None


class LocalAIRouter:
    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self.base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self.timeout = float(timeout if timeout is not None else getattr(config, "OLLAMA_REQUEST_TIMEOUT_S", 8.0))
        self._state: ModelState | None = None

    def _get(self, path: str) -> dict[str, Any] | None:
        try:
            response = requests.get(f"{self.base_url}{path}", timeout=min(self.timeout, 3.0))
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def discover_models(self, refresh: bool = False) -> ModelState:
        if self._state is not None and not refresh:
            return self._state
        payload = self._get("/api/tags") or {}
        installed = tuple(str(item.get("name", "")).strip() for item in payload.get("models", []) if item.get("name"))
        self._state = ModelState(
            installed=installed,
            coder=self._resolve(installed, [getattr(config, "OLLAMA_CODER_MODEL", None), getattr(config, "CODER_MODEL", None), "qwen2.5-coder:7b"]),
            embedder=self._resolve(installed, [getattr(config, "OLLAMA_EMBED_MODEL", None), "nomic-embed-text:latest"]),
            responder=self._resolve(installed, [getattr(config, "OLLAMA_CHAT_MODEL", None), getattr(config, "PRIMARY_MODEL", None), getattr(config, "LOCAL_FALLBACK_MODEL", None), "llama3.1:latest"]),
        )
        return self._state

    @staticmethod
    def _resolve(installed: tuple[str, ...] | list[str], preferred: list[str | None]) -> str | None:
        available = [str(item).strip() for item in installed if str(item).strip()]
        normalized = {item.split(":", 1)[0]: item for item in available}
        for candidate in preferred:
            if not candidate:
                continue
            candidate = str(candidate).strip()
            if candidate in available:
                return candidate
            base = candidate.split(":", 1)[0]
            if base in normalized:
                return normalized[base]
        return None

    @staticmethod
    def _json_from_text(text: str) -> dict[str, Any] | None:
        raw = (text or "").strip()
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else None
        except Exception:
            pass
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.IGNORECASE | re.DOTALL)
        if fenced:
            try:
                value = json.loads(fenced.group(1))
                return value if isinstance(value, dict) else None
            except Exception:
                pass
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                value = json.loads(match.group(0))
                return value if isinstance(value, dict) else None
            except Exception:
                return None
        return None

    def _chat(self, model: str | None, messages: list[dict[str, str]], *, temperature: float = 0.0, fmt: Any = None) -> str | None:
        if not model:
            return None
        body: dict[str, Any] = {"model": model, "messages": messages, "stream": False, "options": {"temperature": temperature}}
        if fmt is not None:
            body["format"] = fmt
        try:
            response = requests.post(f"{self.base_url}/api/chat", json=body, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
            content = (((payload or {}).get("message") or {}).get("content"))
            return str(content) if content is not None else None
        except Exception:
            return None

    def extract_facts(self, text: str) -> dict[str, Any] | None:
        state = self.discover_models()
        if not state.coder or not text:
            return None
        prompt = (
            "Extract only facts explicitly stated or directly asked about. "
            "Never invent a fact. For each fact, preserve the person's/entity's exact name. "
            "For questions, return an empty facts array unless the question itself states a fact. "
            "Return only valid JSON matching the supplied schema."
        )
        content = self._chat(
            state.coder,
            [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            temperature=0.0,
            fmt=FACT_SCHEMA,
        )
        data = self._json_from_text(content or "")
        if not data:
            return None
        facts = data.get("extracted_facts", [])
        clean_facts: list[dict[str, str]] = []
        if isinstance(facts, list):
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                entity = str(fact.get("entity", "")).strip()
                statement = str(fact.get("fact", "")).strip()
                category = str(fact.get("category", "general")).strip() or "general"
                if entity and statement:
                    clean_facts.append({"entity": entity, "fact": statement, "category": category})
        return {"extracted_facts": clean_facts, "search_query": str(data.get("search_query", "") or "").strip()}

    def embed(self, texts: str | list[str]) -> list[list[float]] | None:
        state = self.discover_models()
        if not state.embedder:
            return None
        items = [texts] if isinstance(texts, str) else [str(item) for item in texts]
        if not items:
            return []
        body = {"model": state.embedder, "input": items}
        try:
            response = requests.post(f"{self.base_url}/api/embed", json=body, timeout=self.timeout)
            if response.status_code == 404:
                legacy = requests.post(f"{self.base_url}/api/embeddings", json={"model": state.embedder, "prompt": items[0]}, timeout=self.timeout)
                legacy.raise_for_status()
                vector = legacy.json().get("embedding")
                return [vector] if isinstance(vector, list) else None
            response.raise_for_status()
            vectors = response.json().get("embeddings")
            return vectors if isinstance(vectors, list) else None
        except Exception:
            return None

    def tagged_fact(self, entity: str, key: str, value: str, context: str = "") -> str:
        return f"[Entity: {entity}] {entity}'s {key} is {value}. Context: {context}"

    def respond(self, prompt: str, context: list[dict[str, Any]] | str | None = None) -> str | None:
        state = self.discover_models()
        if not state.responder:
            return None
        if isinstance(context, list):
            context_text = json.dumps(context, ensure_ascii=False, default=str)
        else:
            context_text = str(context or "")
        system = (
            "You are Angelique's local response model. Use only the supplied user request and retrieved context. "
            "Do not invent personal facts, preferences, memories, prices, trades, or actions. "
            "When the context does not contain the answer, say that the information is not known."
        )
        messages = [{"role": "system", "content": system}]
        if context_text:
            messages.append({"role": "system", "content": f"Retrieved memory context:\n{context_text}"})
        messages.append({"role": "user", "content": prompt})
        return self._chat(state.responder, messages, temperature=0.2)


_router: LocalAIRouter | None = None


def get_local_router() -> LocalAIRouter:
    global _router
    if _router is None:
        _router = LocalAIRouter()
    return _router


def reset_local_router() -> None:
    global _router
    _router = None
