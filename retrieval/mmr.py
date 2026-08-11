"""MMR 去冗余选择：在重排结果上选最多 k_final 条，限制同一来源/主题占比"""
from __future__ import annotations

from typing import Any

from core.dataclasses import Evidence


def mmr_select(ranked: list[dict],
               evidences: dict[str, Evidence],
               k_final: int = 8,
               lambda_: float = 0.7,
               max_per_source: int = 4,
               max_per_doc: int = 2) -> list[str]:
    """ranked: feature_rerank 输出（按 final 降序）。返回选中的 doc_id 列表

    约束（实施规划 §4.3.2 初始值）：
    - max_per_source: 同一来源类型最多进入上下文的 chunk 数
    - max_per_doc   : 同一篇文献（按 pmid/doi/nct 稳定键）最多进入上下文的 chunk 数
    """
    selected: list[dict] = []
    candidates = list(ranked)
    source_count: dict[str, int] = {}
    doc_count: dict[str, int] = {}

    def _sim(doc_id: str, others: list[dict]) -> float:
        ev = evidences[doc_id]
        s = 0.0
        for o in others:
            ev_o = evidences[o["doc_id"]]
            inter = len(set(ev.text[:800]) & set(ev_o.text[:800]))
            union = len(set(ev.text[:800]) | set(ev_o.text[:800]))
            s += inter / union if union else 0.0
        return s / len(others) if others else 0.0

    def _doc_key(ev: Evidence) -> str:
        return ev.pmid or ev.doi or ev.nct_id or ev.id

    while candidates and len(selected) < k_final:
        best = None
        best_score = -1e9
        for c in candidates:
            ev = evidences[c["doc_id"]]
            if source_count.get(ev.source_type, 0) >= max_per_source:
                continue
            if doc_count.get(_doc_key(ev), 0) >= max_per_doc:
                continue
            mmr = lambda_ * c["final"] - (1 - lambda_) * _sim(c["doc_id"], selected)
            if mmr > best_score:
                best_score = mmr
                best = c
        if best is None:
            break
        selected.append(best)
        candidates.remove(best)
        ev = evidences[best["doc_id"]]
        source_count[ev.source_type] = source_count.get(ev.source_type, 0) + 1
        doc_count[_doc_key(ev)] = doc_count.get(_doc_key(ev), 0) + 1

    return [s["doc_id"] for s in selected]
