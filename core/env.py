"""Lightweight .env loader with no third-party dependency."""
from __future__ import annotations

import os
from pathlib import Path

_LOADED = False


def _resolve_env_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    search_roots = [Path.cwd(), *Path.cwd().parents, Path(__file__).resolve().parents[1]]
    for root in search_roots:
        resolved = root / candidate
        if resolved.exists():
            return resolved
    return Path.cwd() / candidate


def load_dotenv(path: str = ".env") -> None:
    """Load .env values without overriding existing environment variables."""
    global _LOADED
    if _LOADED:
        return
    p = _resolve_env_path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and not os.environ.get(key):
                os.environ[key] = val
    _LOADED = True
