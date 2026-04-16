"""Secure API key storage for LLM providers.

Keys are stored at ~/.local/share/jobforge/llm_keys.json (outside the repo).
"""

from __future__ import annotations

import json
from pathlib import Path

KEYS_PATH = Path.home() / ".local" / "share" / "jobforge" / "llm_keys.json"


def load_keys() -> dict[str, str]:
    try:
        return json.loads(KEYS_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_key(provider: str, key: str) -> None:
    keys = load_keys()
    if key:
        keys[provider] = key
    else:
        keys.pop(provider, None)
    KEYS_PATH.parent.mkdir(parents=True, exist_ok=True)
    KEYS_PATH.write_text(json.dumps(keys, indent=2))


def get_key(provider: str) -> str | None:
    return load_keys().get(provider)


def mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def get_masked_key(provider: str) -> str | None:
    key = get_key(provider)
    return mask_key(key) if key else None
