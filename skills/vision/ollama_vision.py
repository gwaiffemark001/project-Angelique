from __future__ import annotations

import base64
from pathlib import Path
import requests
from core import config


def analyze_image_with_model(image_path: str, prompt: str = "Describe what is visible in this image and identify important details.") -> str:
    path=Path(image_path).expanduser().resolve()
    if not path.exists(): raise FileNotFoundError(path)
    encoded=base64.b64encode(path.read_bytes()).decode("ascii")
    from brain.llm_interface import _discover_ollama_models
    models=[m for m in _discover_ollama_models() if any(x in m.lower() for x in ('vision','vl','qwen'))]
    if config.PRIMARY_MODEL and config.PRIMARY_MODEL not in models: models.insert(0,config.PRIMARY_MODEL)
    if not models: raise RuntimeError("No Ollama vision-capable model was discovered.")
    errors=[]
    for model in models[:4]:
        try:
            response=requests.post(f"{config.OLLAMA_BASE_URL}/api/chat",json={"model":model,"messages":[{"role":"user","content":prompt,"images":[encoded]}],"stream":False},timeout=config.OLLAMA_REQUEST_TIMEOUT_S)
            if response.ok:
                text=((response.json().get('message') or {}).get('content') or '').strip()
                if text:return text
            errors.append(f"{model}: HTTP {response.status_code}")
        except Exception as exc: errors.append(f"{model}: {exc}")
    raise RuntimeError("Ollama vision request failed: " + "; ".join(errors[:3]))
