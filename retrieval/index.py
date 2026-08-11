"""EvidenceStore：加载 evidence.jsonl，构建 BM25 + 向量索引，提供统一检索接口

- search(query, use_rerank) -> (top_ids, features)
- 支持 build_index_version 哈希用于 Run.index_version
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

from core.config import Config
from core.dataclasses import Evidence, load_jsonl
from core.embeddings import EmbeddingClient
from retrieval.bm25 import BM25Index
from retrieval.mmr import mmr_select
from retrieval.query_expansion import expand_query
from retrieval.rerank import feature_rerank
from retrieval.rrf import rrf_merge
from retrieval.vector import VectorIndex


class EvidenceStore:
    def __init__(self, cfg: Config, evidence_path: Optional[str] = None):
        self.cfg = cfg
        self.path = evidence_path or str(cfg.path("evidence"))
        self.evidences: dict[str, Evidence] = {}
        self.bm25: Optional[BM25Index] = None
        self.vector: Optional[VectorIndex] = None
        self.emb_client: Optional[EmbeddingClient] = None
        self.index_version = "empty"
        self.corpus_version = "empty"   # 证据语料版本：内容 hash 集合
        self._retrieve_cache: dict[tuple, tuple[list, list]] = {}   # 确定性检索缓存

    # ---------- 构建 ----------
    def add_evidence(self, rec: dict) -> None:
        ev = rec if isinstance(rec, Evidence) else Evidence.from_dict(rec)
        # 去重：同 stable id 保留内容 hash 更新版本
        if ev.id in self.evidences:
            old = self.evidences[ev.id]
            if old.content_hash == ev.content_hash:
                return
        self.evidences[ev.id] = ev

    def load(self, path: Optional[str] = None) -> "EvidenceStore":
        p = path or self.path
        if not os.path.exists(p):
            raise FileNotFoundError(f"证据文件不存在: {p}。请先运行数据采集或构建样例。")
        for rec in load_jsonl(p):
            self.add_evidence(rec)
        return self

    def build_index(self, emb_backend: str | None = None) -> "EvidenceStore":
        """构建 BM25 + 向量索引。embedding 后端可从 config 覆盖。"""
        if not self.evidences:
            raise ValueError("证据库为空，无法构建索引")
        docs = [{"id": e.id, "title": e.title, "text": e.text} for e in self.evidences.values()]
        self.bm25 = BM25Index(docs)

        emb_cfg = dict(self.cfg["embedding"])
        if emb_backend:
            emb_cfg["backend"] = emb_backend
        self.emb_client = EmbeddingClient(emb_cfg)
        self.vector = VectorIndex(docs, self.emb_client)

        h = hashlib.sha1()
        h.update(json.dumps(sorted(e.id for e in self.evidences.values())).encode())
        h.update(emb_cfg.get("local_model", "").encode())
        self.index_version = h.hexdigest()[:12]

        # 语料版本：内容 hash 集合（用于审计 Run.corpus_version）
        ch = hashlib.sha1()
        ch.update(json.dumps(sorted(
            e.content_hash or f"{e.id}|{e.text[:200]}" for e in self.evidences.values())).encode())
        self.corpus_version = ch.hexdigest()[:12]
        self._retrieve_cache.clear()   # 语料/索引变化后缓存失效
        return self

    # ---------- 检索 ----------
    def retrieve(self, query: str, *, use_rerank: bool, k_final: int | None = None,
                 verbose: bool = False, stats: Optional[dict] = None) -> tuple[list[dict], list[dict]]:
        """统一检索入口。

        返回 (top_evidences, features)：
        - use_rerank=False: B 条件，RRF 合并后直接取 top-k（无特征重排）
        - use_rerank=True : C/D 条件，特征重排 + MMR

        检索对同一 (查询, 索引版本, rerank) 是确定性的，结果做内存缓存；
        stats 传入 dict 时写入 cache_hit=True/False（成本日志用）。
        """
        if self.bm25 is None or self.vector is None:
            raise RuntimeError("索引未构建，先调用 build_index()")
        rc = self.cfg["retrieval"]
        k_final = k_final or rc["k_final"]

        # 中文医学术语扩展：原句 + 英文术语，缓解中问英库检索鸿沟
        query = expand_query(query)
        key = (query, self.index_version, use_rerank, k_final)
        if key in self._retrieve_cache:
            cached_evs, cached_feats = self._retrieve_cache[key]
            if stats is not None:
                stats["cache_hit"] = True
            return [dict(e) for e in cached_evs], [dict(f) for f in cached_feats]

        bm25_hits = self.bm25.search(query, k=rc["k_bm25"])
        vec_hits = self.vector.search(query, k=rc["k_vec"])
        merged = rrf_merge([bm25_hits, vec_hits], k=rc["rrf_k"])[: rc["k_rrf"]]

        if not use_rerank:
            top_ids = [doc_id for doc_id, _ in merged[:k_final]]
            features = [{"doc_id": d, "rank_in": i, "rrf": s, "final": s}
                        for i, (d, s) in enumerate(merged[:k_final])]
        else:
            weights = self.cfg["rerank"]["weights"]
            ranked = feature_rerank(merged, self.evidences, query, weights,
                                    q_freshness="stable", verbose=verbose)
            top_ids = mmr_select(ranked, self.evidences, k_final=k_final,
                                 lambda_=self.cfg["rerank"]["mmr_lambda"])
            features = [r for r in ranked if r["doc_id"] in top_ids]
            features.sort(key=lambda r: top_ids.index(r["doc_id"]))

        top_evs = [self.evidences[d].to_dict() for d in top_ids if d in self.evidences]
        self._retrieve_cache[key] = ([dict(e) for e in top_evs], [dict(f) for f in features])
        if stats is not None:
            stats["cache_hit"] = False
        return top_evs, features

    def get(self, doc_id: str) -> Evidence | None:
        return self.evidences.get(doc_id)


def build_store(cfg: Config, emb_backend: str | None = None) -> EvidenceStore:
    store = EvidenceStore(cfg)
    store.load().build_index(emb_backend=emb_backend)
    return store
