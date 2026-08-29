from __future__ import annotations
from pathlib import Path
import requests
from core import config


def download_file(url: str, output_path: str, timeout: float = 15.0) -> str:
    if not str(url).startswith(("http://", "https://")):
        raise ValueError("Only HTTP(S) downloads are supported")
    target = Path(output_path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": config.DEFAULT_HTTP_USER_AGENT}) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(1024 * 256):
                if chunk:
                    handle.write(chunk)
    return str(target)
