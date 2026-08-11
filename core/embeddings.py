"""Embedding 客户端：支持 api / local / fallback 三种后端

- api     : OpenAI 兼容 embedding 接口（如 SiliconFlow），需在 config 配 base_url 与 key
- local   : sentence-transformers 本地模型（首次运行自动下载）
- fallback: 词表哈希向量，不依赖模型（仅保证管线可跑通，不建议正式评测使用）
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Optional

import numpy as np


class EmbeddingClient:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.backend = cfg.get("backend", "fallback")
        self.dim = int(cfg.get("dim", 512))
        self._model = None
        self._session = None
        if self.backend == "api":
            self._init_api()
        elif self.backend == "local":
            self._init_local()

    def _init_api(self) -> None:
        import httpx
        base = self.cfg.get("api_base_url", "").rstrip("/")
        key = self.cfg.get("api_key", "") or os.environ.get("EMBEDDING_API_KEY", "")
        if not base or not key:
            raise RuntimeError("embedding.backend=api 需要配置 api_base_url 与 key")
        self._api_base = f"{base}/embeddings"
        self._api_model = self.cfg.get("api_model", "BAAI/bge-m3")
        self._session = httpx.Client(
            headers={"Authorization": f"Bearer {key}"}, timeout=60)

    def _init_local(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise RuntimeError(
                "embedding.backend=local 需要安装 sentence-transformers："
                "pip install sentence-transformers")
        name = self.cfg.get("local_model", "BAAI/bge-small-zh-v1.5")
        self._model = SentenceTransformer(name)
        try:
            self.dim = self._model.get_embedding_dimension()
        except AttributeError:  # sentence-transformers < 5.0 兼容
            self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        if self.backend == "api":
            resp = self._session.post("", json={"model": self._api_model, "input": texts})
            resp.raise_for_status()
            data = resp.json()["data"]
            arr = np.array([d["embedding"] for d in data], dtype=np.float32)
            self.dim = arr.shape[1]
            return arr
        if self.backend == "local":
            return self._model.encode(texts, normalize_embeddings=True).astype(np.float32)
        return self._hash_embed(texts)

    def _hash_embed(self, texts: list[str]) -> np.ndarray:
        """fallback：字符 n-gram 哈希向量，可复现、无外部依赖"""
        vecs = []
        for t in texts:
            v = np.zeros(self.dim, dtype=np.float32)
            tokens = re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", t.lower())
            grams = []
            for tok in tokens:
                if len(tok) == 1:
                    grams.append(tok)
                else:
                    grams.extend(tok[i:i + 2] for i in range(len(tok) - 1))
            for g in grams:
                h = int(hashlib.md5(g.encode()).hexdigest()[:8], 16)
                v[h % self.dim] += 1.0
            n = np.linalg.norm(v)
            vecs.append(v / n if n > 0 else v)
        return np.asarray(vecs, dtype=np.float32)

    def cosine_similarity(self, q_vec: np.ndarray, mat: np.ndarray) -> np.ndarray:
        if mat.shape[0] == 0:
            return np.zeros(0)
        q = q_vec / (np.linalg.norm(q_vec) + 1e-9)
        return mat @ q
