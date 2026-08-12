from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from ..schemas import RetrievalResult


# 英文医学术语按词切分；中文只保留连续短语，避免把“的/是/有”等单字
# 当成高频 BM25 查询词。
TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}")

QUERY_EXPANSIONS = {
    "高血压": ["hypertension", "blood pressure"],
    "血压": ["blood pressure", "hypertension"],
    "血脂": ["dyslipidemia", "dyslipidaemia", "lipid", "cholesterol"],
    "血脂异常": ["dyslipidemia", "dyslipidaemia", "hyperlipidemia"],
    "胆固醇": ["cholesterol", "ldl", "lipoprotein"],
    "低密度脂蛋白": ["ldl", "low-density lipoprotein"],
    "他汀": ["statin", "statins"],
    "一级预防": ["primary prevention"],
    "二级预防": ["secondary prevention"],
    "指南": ["guideline", "guidelines", "recommendation"],
    "饮食": ["diet", "dietary"],
    "DASH": ["dash", "dietary approaches to stop hypertension"],
    "低钠": ["low sodium", "sodium reduction", "salt reduction"],
    "限盐": ["salt reduction", "sodium reduction"],
    "替米沙坦": ["telmisartan"],
    "氯沙坦": ["losartan"],
    "糖尿病": ["diabetes", "diabetic"],
    "临床试验": ["clinical trial", "randomized", "trial"],
    "成人": ["adult", "adults"],
    "患者": ["patient", "patients"],
    "研究": ["study", "studies", "research"],
}


def _tokens(text: str) -> List[str]:
    return [token.lower() for token in TOKEN_RE.findall(text or "")]


def _parse_jsonish(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return " ".join(str(item) for item in parsed)
        except json.JSONDecodeError:
            pass
    return str(value)


class ReferenceRetriever:
    """基于完整 evidence.jsonl 的纯 Python BM25 reference retriever。

    这是 B4 的本地参考实现：不调用网络、不使用 qrels 排序、不依赖赛道一。
    它暂时只有 BM25 单路召回，后续可在同一 RetrievalResult 契约下增加向量和 RRF。
    """

    def __init__(
        self,
        evidence_path: Path,
        index_version: str = "reference-bm25-v0.1",
        k1: float = 1.2,
        b: float = 0.75,
        rerank: bool = False,
    ):
        self.evidence_path = evidence_path
        self.index_version = index_version
        self.k1 = k1
        self.b = b
        self.rerank = rerank
        self.records: List[Dict[str, Any]] = []
        self.doc_tokens: List[Counter[str]] = []
        self.doc_lengths: List[int] = []
        self.document_frequency: Counter[str] = Counter()
        self.postings: Dict[str, Set[int]] = defaultdict(set)
        self._build_index()

    def _build_index(self) -> None:
        with self.evidence_path.open(encoding="utf-8") as f:
            source_records = [json.loads(line) for line in f if line.strip()]

        for record in source_records:
            title = record.get("title") or ""
            body = record.get("abstract_or_chunk") or ""
            keywords = _parse_jsonish(record.get("keywords"))
            mesh_terms = _parse_jsonish(record.get("mesh_terms"))
            topics = _parse_jsonish(record.get("topics"))
            # 标题重复三次，保留医学标题和标识符对 BM25 的影响。
            text = " ".join([title, title, title, body, keywords, mesh_terms, topics])
            tokens = Counter(_tokens(text))
            if not tokens:
                continue
            doc_index = len(self.records)
            self.records.append(record)
            self.doc_tokens.append(tokens)
            self.doc_lengths.append(sum(tokens.values()))
            for token in tokens:
                self.document_frequency[token] += 1
                self.postings[token].add(doc_index)

        self.document_count = len(self.records)
        self.average_document_length = (
            sum(self.doc_lengths) / self.document_count if self.document_count else 0.0
        )

    @property
    def index_stats(self) -> Dict[str, Any]:
        return {
            "index_type": "bm25",
            "source_path": str(self.evidence_path),
            "document_count": self.document_count,
            "vocabulary_size": len(self.document_frequency),
            "average_document_length": round(self.average_document_length, 3),
            "k1": self.k1,
            "b": self.b,
            "index_version": self.index_version,
        }

    def _expand_query(self, question: Dict[str, Any]) -> List[str]:
        text = question.get("question", "")
        terms = set(_tokens(text))
        for key, expansions in QUERY_EXPANSIONS.items():
            if key.lower() in text.lower():
                for expansion in expansions:
                    terms.update(_tokens(expansion))
        configured = question.get("query_rewrites") or question.get("query_terms") or []
        for rewrite in configured:
            terms.update(_tokens(str(rewrite)))
        return sorted(terms)

    def _score(self, query_terms: Iterable[str], doc_index: int) -> float:
        if not self.document_count or not self.average_document_length:
            return 0.0
        tokens = self.doc_tokens[doc_index]
        length = self.doc_lengths[doc_index]
        score = 0.0
        for term in query_terms:
            frequency = tokens.get(term, 0)
            if not frequency:
                continue
            df = self.document_frequency.get(term, 0)
            idf = math.log(1.0 + (self.document_count - df + 0.5) / (df + 0.5))
            denominator = frequency + self.k1 * (1 - self.b + self.b * length / self.average_document_length)
            score += idf * (frequency * (self.k1 + 1)) / denominator
        return score

    def _candidate(self, record: Dict[str, Any], score: float, rank: int, query_terms: List[str]) -> Dict[str, Any]:
        return {
            "evidence_id": record["id"],
            "rank": rank,
            "score": round(score, 6),
            "bm25_score": round(score, 6),
            "source_type": record.get("source_type"),
            "record_kind": record.get("record_kind"),
            "title": record.get("title"),
            "url": record.get("url"),
            "evidence_level": record.get("evidence_level"),
            "published_at": record.get("published_at"),
            "content_hash": record.get("content_hash"),
            "query_terms": query_terms,
            "retrieval_stage": "bm25",
        }

    @staticmethod
    def _select_final(candidates: List[Dict[str, Any]], final_k: int) -> List[Dict[str, Any]]:
        selected: List[Dict[str, Any]] = []
        source_counts: Dict[str, int] = {}
        for candidate in candidates:
            source = candidate.get("source_type") or "unknown"
            if source_counts.get(source, 0) >= 2 and len(candidates) - len(selected) > final_k:
                continue
            item = dict(candidate)
            item["mmr_selected"] = True
            selected.append(item)
            source_counts[source] = source_counts.get(source, 0) + 1
            if len(selected) >= final_k:
                break
        return selected

    @staticmethod
    def _feature_rerank(candidates: List[Dict[str, Any]], query_terms: List[str]) -> List[Dict[str, Any]]:
        """Apply a deterministic, inspectable rerank over BM25 candidates."""
        query_set = {term.lower() for term in query_terms if term.isascii() and len(term) > 1}
        max_bm25 = max((float(item.get("bm25_score", 0.0)) for item in candidates), default=0.0)
        reranked: List[Dict[str, Any]] = []
        for item in candidates:
            title_terms = set(_tokens(item.get("title") or ""))
            title_overlap = len(query_set & title_terms)
            title_coverage = title_overlap / max(1, len(query_set))
            authority_bonus = 0.0
            if item.get("record_kind") == "guideline" or item.get("evidence_level") == "guideline":
                authority_bonus = 0.35
            elif item.get("evidence_level") in {"systematic_review", "review"}:
                authority_bonus = 0.12
            normalized_bm25 = (float(item.get("bm25_score", 0.0)) / max_bm25) if max_bm25 else 0.0
            rerank_score = (
                normalized_bm25
                + 0.08 * min(title_overlap, 8)
                + 0.4 * title_coverage
                + authority_bonus
            )
            updated = dict(item)
            updated["title_overlap"] = title_overlap
            updated["title_coverage"] = round(title_coverage, 6)
            updated["authority_bonus"] = authority_bonus
            updated["rerank_score"] = round(rerank_score, 6)
            updated["feature_score"] = round(rerank_score, 6)
            updated["retrieval_stage"] = "feature_rerank"
            reranked.append(updated)
        reranked.sort(key=lambda item: (-item["rerank_score"], item["evidence_id"]))
        for rank, item in enumerate(reranked, start=1):
            item["rank"] = rank
        return reranked

    def search(self, question: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> RetrievalResult:
        started = time.perf_counter()
        config = config or {}
        initial_k = int(config.get("initial_k", 50))
        final_k = int(config.get("final_k", 6))
        query_terms = self._expand_query(question)
        scored = [
            (self._score(query_terms, index), index)
            for index in range(self.document_count)
        ]
        scored.sort(key=lambda pair: (-pair[0], self.records[pair[1]]["id"]))
        top = [
            self._candidate(self.records[index], score, rank, query_terms)
            for rank, (score, index) in enumerate(scored[:initial_k], start=1)
            if score > 0
        ]
        rerank_candidates = self._feature_rerank(top, query_terms) if self.rerank else top
        for item in rerank_candidates:
            item["rrf_score"] = item["bm25_score"]
            if not self.rerank:
                item["feature_score"] = item["bm25_score"]
                item["retrieval_stage"] = "bm25_reference"
        final_evidence = self._select_final(rerank_candidates, final_k)
        return RetrievalResult(
            question_id=question["id"],
            query=question["question"],
            query_rewrites=query_terms,
            index_version=self.index_version,
            bm25_candidates=top,
            vector_candidates=[],
            rrf_candidates=top,
            rerank_candidates=rerank_candidates,
            final_evidence=final_evidence,
            feature_scores=[
                {"evidence_id": item["evidence_id"], "feature_score": item["feature_score"], "rank": item["rank"]}
                for item in rerank_candidates
            ],
            index_stats=self.index_stats,
            latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
        )
