from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import load_config
from core.dataclasses import Evidence
from retrieval.index import EvidenceStore
from retrieval.query_expansion import expand_query

from ..schemas import RetrievalResult


class HybridReferenceRetriever:
    """B4 adapter for the repository's BM25 + vector + RRF retrieval stack.

    The adapter deliberately keeps retrieval implementation details in ``retrieval/``
    and only translates them into the B4 ``RetrievalResult`` contract. It never reads
    qrels and does not depend on A5 or Track 1 runtime code.
    """

    def __init__(
        self,
        evidence_path: Path,
        config_path: Optional[Path] = None,
        embedding_backend: str = "fallback",
        use_vector: bool = True,
        use_rerank: bool = True,
        final_k: int = 4,
    ):
        self.evidence_path = evidence_path
        self.embedding_backend = embedding_backend
        self.use_vector = use_vector
        self.use_rerank = use_rerank
        self.final_k = final_k
        self.config = load_config(config_path)
        self.config.data["embedding"]["backend"] = embedding_backend
        self.config.data["retrieval"]["k_final"] = final_k
        self.store = EvidenceStore(self.config, str(evidence_path))
        self.store.load().build_index(emb_backend=embedding_backend, build_vector=use_vector)
        mode = "vector" if use_vector else "bm25-only"
        self.index_version = f"hybrid-{mode}-{embedding_backend}-{self.store.index_version}"

    @property
    def index_stats(self) -> Dict[str, Any]:
        embedding = self.config["embedding"]
        retrieval = self.config["retrieval"]
        return {
            "index_type": "bm25_vector_rrf",
            "source_path": str(self.evidence_path),
            "document_count": len(self.store.evidences),
            "embedding_backend": self.embedding_backend,
            "embedding_model": embedding.get("local_model") if self.embedding_backend == "local" else embedding.get("backend"),
            "use_vector": self.use_vector,
            "k_bm25": retrieval["k_bm25"],
            "k_vec": retrieval["k_vec"],
            "k_rrf": retrieval["k_rrf"],
            "rrf_k": retrieval["rrf_k"],
            "use_rerank": self.use_rerank,
            "index_version": self.index_version,
            "corpus_version": self.store.corpus_version,
        }

    def _candidate(
        self,
        row: Dict[str, Any],
        stage: str,
        metadata_cache: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        evidence_id = row["doc_id"]
        ev = metadata_cache.get(evidence_id)
        if ev is None:
            record = self.store.get(evidence_id)
            if record is None:
                ev = {"evidence_id": evidence_id}
            else:
                ev = record.to_dict()
                ev["evidence_id"] = record.id
                ev["abstract_or_chunk"] = record.text
                ev["record_kind"] = "guideline" if record.source_type == "guideline" else "abstract"
            metadata_cache[evidence_id] = ev
        item = dict(ev)
        item["evidence_id"] = evidence_id
        item["rank"] = row.get("rank")
        item["score"] = row.get("score", row.get("final", 0.0))
        item["retrieval_stage"] = stage
        if "rrf" in row:
            item["rrf_score"] = row["rrf"]
        if "final" in row:
            item["feature_score"] = row["final"]
        if "feature_score" in row:
            item["feature_score"] = row["feature_score"]
        item.update({key: value for key, value in row.items() if key not in {"doc_id", "rank", "score", "final"}})
        return item

    def search(self, question: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> RetrievalResult:
        started = time.perf_counter()
        config = config or {}
        final_k = int(config.get("final_k", self.final_k))
        stats: Dict[str, Any] = {}
        query = question.get("question", "")
        freshness = question.get("freshness", "stable")
        evidences, features = self.store.retrieve(
            query,
            use_rerank=self.use_rerank,
            use_vector=self.use_vector,
            k_final=final_k,
            stats=stats,
            q_freshness=freshness,
        )
        metadata_cache: Dict[str, Dict[str, Any]] = {}
        bm25_candidates = [
            self._candidate(row, "bm25", metadata_cache)
            for row in stats.get("bm25_candidates", [])
        ]
        vector_candidates = [
            self._candidate(row, "vector", metadata_cache)
            for row in stats.get("vector_candidates", [])
        ]
        rrf_candidates = [
            self._candidate(row, "rrf", metadata_cache)
            for row in stats.get("rrf_candidates", [])
        ]
        rerank_candidates = [
            self._candidate(row, "feature_rerank", metadata_cache)
            for row in stats.get("rerank_candidates", [])
        ]
        feature_by_id = {row.get("doc_id"): row for row in features}
        final_evidence: List[Dict[str, Any]] = []
        for rank, raw in enumerate(evidences, start=1):
            evidence_id = raw["id"]
            item = dict(raw)
            item["evidence_id"] = evidence_id
            item["abstract_or_chunk"] = raw.get("text", "")
            item["record_kind"] = "guideline" if raw.get("source_type") == "guideline" else "abstract"
            item["rank"] = rank
            item["mmr_selected"] = True
            item["retrieval_stage"] = "mmr_selected" if self.use_rerank else "rrf_topk"
            feature = feature_by_id.get(evidence_id, {})
            if feature:
                item["rrf_score"] = feature.get("rrf", feature.get("final"))
                item["feature_score"] = feature.get("final", feature.get("rrf"))
                item["rerank_features"] = dict(feature)
            final_evidence.append(item)

        return RetrievalResult(
            question_id=question["id"],
            query=query,
            query_rewrites=expand_query(query).split(),
            index_version=self.index_version,
            bm25_candidates=bm25_candidates,
            vector_candidates=vector_candidates,
            rrf_candidates=rrf_candidates,
            rerank_candidates=rerank_candidates,
            final_evidence=final_evidence,
            feature_scores=[dict(row) for row in features],
            index_stats={**self.index_stats, "cache_hit": bool(stats.get("cache_hit", False))},
            latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
        )
