"""RRF 融合：BM25 与向量排名合并"""
from __future__ import annotations


def rrf_merge(lists: list[list[tuple[str, float]]], k: int = 60) -> list[tuple[str, float]]:
    """lists: 多个 [(doc_id, score), ...]，按 RRF 融合，返回 [(doc_id, rrf_score)] 降序"""
    scores: dict[str, float] = {}
    for ranked in lists:
        for rank, (doc_id, _) in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
