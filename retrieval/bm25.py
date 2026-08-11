"""BM25 词法检索（rank-bm25）"""
from __future__ import annotations

import re
from typing import Any

from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> list[str]:
    # 中文按字切分 + 英文/数字按 token 切分，保持 PMID/药名等标识符可匹配
    text = text.lower()
    tokens = re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", text)
    return tokens


class BM25Index:
    def __init__(self, docs: list[dict]):
        """docs: [{'id':..., 'title':..., 'text':...}]"""
        self.ids = [d["id"] for d in docs]
        corpus = [_tokenize(d.get("title", "") + " " + d.get("text", "")) for d in docs]
        self.bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, query: str, k: int = 50) -> list[tuple[str, float]]:
        if self.bm25 is None or not query.strip():
            return []
        q = _tokenize(query)
        if not q:
            return []
        scores = self.bm25.get_scores(q)
        idx = scores.argsort()[::-1][:k]
        # 语料小时 IDF 可为 0 或负，不能过滤非正分，否则小语料永远搜不到结果
        return [(self.ids[i], float(scores[i])) for i in idx]
