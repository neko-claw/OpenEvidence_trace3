from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

from .hybrid_retriever import HybridReferenceRetriever


class A5EvidenceRetrieverAdapter:
    """Expose Track 3 retrieval through the A5 EvidenceRetriever protocol.

    A5 remains responsible for planning, tool budgets, Gate2, tracing, claim
    verification, and release decisions. This adapter only maps evidence and
    retrieval diagnostics; it does not alter the A5 state machine.
    """

    def __init__(
        self,
        evidence_path: Path,
        a5_root: Path,
        config_path: Optional[Path] = None,
        embedding_backend: str = "fallback",
        use_rerank: bool = True,
        final_k: int = 4,
    ):
        self.a5_root = a5_root.resolve()
        if str(self.a5_root) not in sys.path:
            sys.path.insert(0, str(self.a5_root))
        self.retriever = HybridReferenceRetriever(
            evidence_path,
            config_path=config_path,
            embedding_backend=embedding_backend,
            use_rerank=use_rerank,
            final_k=final_k,
        )

    @staticmethod
    def _record_payload(item: dict[str, Any], evidence_record_type: Any) -> Any:
        evidence_id = item["evidence_id"]
        content = item.get("abstract_or_chunk") or item.get("text") or ""
        if not content.strip():
            return None
        raw_score = item.get("feature_score", item.get("rrf_score", item.get("score")))
        retrieval_score = raw_score if isinstance(raw_score, (int, float)) and 0 <= raw_score <= 1 else None
        source_metadata = {
            "url": item.get("url"),
            "pmid": item.get("pmid"),
            "doi": item.get("doi"),
            "nct_id": item.get("nct_id"),
            "published_at_raw": item.get("published_at"),
            "content_hash": item.get("content_hash"),
            "retrieval_stage": item.get("retrieval_stage"),
            "rank": item.get("rank"),
            "score": item.get("score"),
            "rrf_score": item.get("rrf_score"),
            "feature_score": item.get("feature_score"),
            "retrieval_features": item.get("rerank_features", {}),
        }
        return evidence_record_type.model_validate({
            "id": evidence_id,
            "content": content,
            "source_type": item.get("source_type") or "unknown",
            "title": item.get("title") or evidence_id,
            "source_metadata": source_metadata,
            "population": item.get("population"),
            "intervention": item.get("intervention"),
            "comparator": item.get("comparator"),
            "outcome": item.get("outcome"),
            "retrieval_score": retrieval_score,
            "evidence_level": item.get("evidence_level"),
            "spans": [],
            "mock": False,
        })

    def retrieve(self, question: Any, plan: Any, request: Any) -> Any:
        from a5.domain.models import RetrievalResult

        result = self.retriever.search(
            {"id": question.question_id, "question": question.text},
            {"final_k": self.retriever.final_k},
        )
        records = []
        for item in result.final_evidence:
            record = self._record_payload(item, __import__("a5.domain.models", fromlist=["EvidenceRecord"]).EvidenceRecord)
            if record is not None:
                records.append(record)
        diagnostics = {
            "adapter": type(self).__name__,
            "tool_name": "track3_hybrid_search",
            "source_type": request.source_type,
            "tool_call_index": request.tool_call_index,
            "query_count": len(plan.queries),
            "index_version": result.index_version,
            "index_stats": result.index_stats,
            "candidate_counts": {
                "bm25": len(result.bm25_candidates),
                "vector": len(result.vector_candidates),
                "rrf": len(result.rrf_candidates),
                "rerank": len(result.rerank_candidates),
                "final": len(result.final_evidence),
            },
            "retrieval_trace": {
                "bm25_candidates": result.bm25_candidates,
                "vector_candidates": result.vector_candidates,
                "rrf_candidates": result.rrf_candidates,
                "rerank_candidates": result.rerank_candidates,
                "feature_scores": result.feature_scores,
            },
        }
        return RetrievalResult(
            evidence=records,
            tool_name="track3_hybrid_search",
            diagnostics=diagnostics,
        )
