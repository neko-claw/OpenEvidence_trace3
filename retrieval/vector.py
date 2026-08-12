"""向量语义检索（numpy 内积，小语料足够）"""
from __future__ import annotations

import numpy as np

from core.embeddings import EmbeddingClient


class VectorIndex:
    def __init__(self, docs: list[dict], emb_client: EmbeddingClient, matrix: np.ndarray | None = None):
        """docs: [{'id':..., 'title':..., 'text':...}]"""
        self.ids = [d["id"] for d in docs]
        texts = [d.get("title", "") + "\n" + d.get("text", "") for d in docs]
        self.matrix = matrix if matrix is not None else emb_client.embed(texts)
        self.emb = emb_client

    def search(self, query: str, k: int = 50) -> list[tuple[str, float]]:
        q_vec = self.emb.embed([query])[0]
        sims = self.emb.cosine_similarity(q_vec, self.matrix)
        idx = sims.argsort()[::-1][:k]
        return [(self.ids[i], float(sims[i])) for i in idx]
