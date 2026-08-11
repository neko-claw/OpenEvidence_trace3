"""轻量 .env 加载（无外部依赖）：key 只放 .env，不进入日志或仓库"""
from __future__ import annotations

import os
from pathlib import Path

_LOADED = False


def load_dotenv(path: str = ".env") -> None:
    """读取项目根目录 .env，已存在的环境变量优先（不覆盖）"""
    global _LOADED
    if _LOADED:
        return
    p = Path(path)
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
