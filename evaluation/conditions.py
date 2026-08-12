from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


CONDITION_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "A": {
        "name": "closed_book",
        "retrieval_mode": "none",
        "require_citations": False,
        "tool_budget": 0,
    },
    "B": {
        "name": "base_rag",
        "retrieval_mode": "bm25_vector_rrf",
        "require_citations": True,
        "tool_budget": 0,
    },
    "C": {
        "name": "rerank_rag",
        "retrieval_mode": "bm25_vector_rrf_rerank_mmr",
        "require_citations": True,
        "tool_budget": 0,
    },
    "D": {
        "name": "full_system",
        "retrieval_mode": "full_system_adapter",
        "require_citations": True,
        "tool_budget": 3,
        "system_version": "mock-system-v0.1",
    },
    "E": {
        "name": "degraded_rag",
        "base_condition": "C",
        "stress_rule": "drop_all_gold_v1",
        "require_citations": True,
        "tool_budget": 0,
    },
}

# 占位值（未冻结）：配置中写 TO_BE_FILLED 时保留代码默认，防止合入后行为被占位符覆盖
_PLACEHOLDER_VALUES = {"", "to_be_filled", None}


def _load_conditions_yaml(path: Optional[str | os.PathLike]) -> Dict[str, Dict[str, Any]]:
    """从 configs/conditions.yaml 读取 conditions 段（存在时）；失败静默回退代码默认。"""
    if yaml is None or not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # pragma: no cover - 配置文件损坏时回退默认，不让实验中断
        return {}
    return data.get("conditions") or {}


def get_condition_config(
    condition: str,
    yaml_path: Optional[str | os.PathLike] = None,
) -> Dict[str, Any]:
    """返回条件配置：代码默认 + configs/conditions.yaml 覆盖（版本化配置真正生效）。

    yaml 值若为占位符（TO_BE_FILLED）则不覆盖代码默认，避免合入后行为漂移。
    """
    condition = condition.upper()
    if condition not in CONDITION_DEFAULTS:
        raise ValueError(f"unsupported B4 condition: {condition}")
    merged = dict(CONDITION_DEFAULTS[condition])
    for key, value in (_load_conditions_yaml(yaml_path).get(condition) or {}).items():
        placeholder = isinstance(value, str) and value.strip().lower() in _PLACEHOLDER_VALUES
        if placeholder or value is None:
            continue
        merged[key] = value
    return merged

