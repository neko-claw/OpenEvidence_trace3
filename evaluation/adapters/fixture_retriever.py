from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..schemas import RetrievalResult


TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


def _tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall((text or "").lower()))


class FixtureRetriever:
    """离线确定性检索器，用于 B4 开发，不代表最终生产检索实现。"""

    def __init__(self, evidence_path: Path, qrels_path: Path, index_version: str = "fixture-index-v0.1"):
        self.evidence = self._load_jsonl(evidence_path)
        self.by_id = {record["id"]: record for record in self.evidence}
        self.qrels = self._load_jsonl(qrels_path)
        self.qrel_map: Dict[tuple[str, str], Dict[str, Any]] = {
            (row["question_id"], row["evidence_id"]): row for row in self.qrels
        }
        self.index_version = index_version

    @staticmethod
    def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
        with path.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def _candidate(self, question: Dict[str, Any], record: Dict[str, Any], mode: str, rank: int) -> Dict[str, Any]:
        qrel = self.qrel_map.get((question["id"], record["id"]), {})
        grade = int(qrel.get("relevance_grade", 0))
        query_terms = _tokens(question["question"])
        doc_terms = _tokens(f"{record.get('title', '')} {record.get('abstract_or_chunk', '')}")
        lexical_overlap = len(query_terms & doc_terms)
        stable = int(hashlib.sha256(f"{question['id']}:{record['id']}:{mode}".encode()).hexdigest()[:6], 16) / 0xFFFFFF
        if mode == "bm25":
            score = grade * 10.0 + lexical_overlap * 0.25 + stable * 0.01
        else:
            score = grade * 10.0 + lexical_overlap * 0.15 + stable * 0.01
        return {
            "evidence_id": record["id"],
            "rank": rank,
            "score": round(score, 6),
            "source_type": record.get("source_type"),
            "record_kind": record.get("record_kind"),
            "title": record.get("title"),
            "url": record.get("url"),
            "evidence_level": record.get("evidence_level"),
            "published_at": record.get("published_at"),
            "content_hash": record.get("content_hash"),
            "qrel_grade": grade,
            "qrel_stance": qrel.get("stance"),
            "lexical_overlap": lexical_overlap,
            "retrieval_stage": mode,
        }

    def _rank(self, question: Dict[str, Any], mode: str, k: int = 8) -> List[Dict[str, Any]]:
        candidates = [self._candidate(question, record, mode, 0) for record in self.evidence]
        candidates.sort(key=lambda c: (-c["score"], c["evidence_id"]))
        for rank, candidate in enumerate(candidates[:k], start=1):
            candidate["rank"] = rank
        return candidates[:k]

    @staticmethod
    def _rrf(bm25: List[Dict[str, Any]], vector: List[Dict[str, Any]], k: int = 8) -> List[Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        for result_list in (bm25, vector):
            for item in result_list:
                entry = merged.setdefault(item["evidence_id"], dict(item))
                entry["rrf_score"] = entry.get("rrf_score", 0.0) + 1.0 / (60 + item["rank"])
        ranked = sorted(merged.values(), key=lambda c: (-c["rrf_score"], c["evidence_id"]))[:k]
        for rank, item in enumerate(ranked, start=1):
            item["rank"] = rank
            item["retrieval_stage"] = "rrf"
        return ranked

    @staticmethod
    def _rerank_and_mmr(candidates: List[Dict[str, Any]], final_k: int = 4) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        scored = []
        for item in candidates:
            source_quality = {"guideline": 1.0, "pubmed": 0.8, "europepmc": 0.7, "clinicaltrial": 0.7, "fixture": 0.0}.get(item.get("source_type"), 0.5)
            evidence_level = min(float(item.get("qrel_grade", 0)) / 3.0, 1.0)
            feature_score = (
                0.45 * evidence_level
                + 0.25 * min(item.get("lexical_overlap", 0) / 8.0, 1.0)
                + 0.20 * source_quality
                + 0.10 * min(item.get("rrf_score", 0.0) * 60.0, 1.0)
            )
            entry = dict(item)
            entry["feature_score"] = round(feature_score, 6)
            scored.append(entry)
        scored.sort(key=lambda c: (-c["feature_score"], c["evidence_id"]))
        for rank, item in enumerate(scored, start=1):
            item["rank"] = rank
            item["retrieval_stage"] = "rerank"

        selected: List[Dict[str, Any]] = []
        source_counts: Dict[str, int] = {}
        for item in scored:
            source = item.get("source_type") or "unknown"
            if source_counts.get(source, 0) >= 2 and len(scored) - len(selected) > final_k:
                continue
            entry = dict(item)
            entry["mmr_selected"] = True
            selected.append(entry)
            source_counts[source] = source_counts.get(source, 0) + 1
            if len(selected) >= final_k:
                break
        return scored, selected

    def search(self, question: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> RetrievalResult:
        started = time.perf_counter()
        config = config or {}
        initial_k = int(config.get("initial_k", 8))
        final_k = int(config.get("final_k", 4))
        bm25 = self._rank(question, "bm25", initial_k)
        vector = self._rank(question, "vector", initial_k)
        rrf = self._rrf(bm25, vector, initial_k)
        if config.get("use_rerank", True):
            reranked, selected = self._rerank_and_mmr(rrf, final_k)
        else:
            reranked = [dict(item) for item in rrf]
            selected = [dict(item) for item in rrf[:final_k]]
            for item in selected:
                item["mmr_selected"] = True
        return RetrievalResult(
            question_id=question["id"],
            query=question["question"],
            query_rewrites=[],
            index_version=self.index_version,
            bm25_candidates=bm25,
            vector_candidates=vector,
            rrf_candidates=rrf,
            rerank_candidates=reranked,
            final_evidence=selected,
            feature_scores=[
                {
                    "evidence_id": item["evidence_id"],
                    "feature_score": item.get("feature_score", item.get("rrf_score", item.get("score", 0.0))),
                    "rank": item["rank"],
                }
                for item in reranked
            ],
            latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
        )
