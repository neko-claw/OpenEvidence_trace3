from __future__ import annotations

from typing import Any, Dict


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
        "stress_rule": "drop_gold_v1",
        "require_citations": True,
        "tool_budget": 0,
    },
}


def get_condition_config(condition: str) -> Dict[str, Any]:
    condition = condition.upper()
    if condition not in CONDITION_DEFAULTS:
        raise ValueError(f"unsupported B4 condition: {condition}")
    return dict(CONDITION_DEFAULTS[condition])

