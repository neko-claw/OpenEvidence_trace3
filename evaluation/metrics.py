"""确定性指标：Hit@k、MRR、Recall@50、nDCG@8、citation precision/coverage"""
from __future__ import annotations

import math
from typing import Iterable, Optional


# ---------- 检索指标 ----------

def hit_at_k(ranked_ids: list[str], gold: set[str], k: int) -> float:
    """gold 证据是否进入前 k"""
    return 1.0 if set(ranked_ids[:k]) & gold else 0.0


def mrr(ranked_ids: list[str], gold: set[str]) -> float:
    """首次命中排名的倒数"""
    for i, doc_id in enumerate(ranked_ids, start=1):
        if doc_id in gold:
            return 1.0 / i
    return 0.0


def recall_at_k(ranked_ids: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 0.0
    hit = set(ranked_ids[:k]) & gold
    return len(hit) / len(gold)


def ndcg_at_k(ranked_ids: list[str], gold: set[str], k: int) -> float:
    """nDCG@k：gold 文档越靠前越好"""
    dcg = 0.0
    for i, doc_id in enumerate(ranked_ids[:k], start=1):
        if doc_id in gold:
            dcg += 1.0 / math.log2(i + 1)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal > 0 else 0.0


# ---------- 引用指标 ----------

def citation_precision(valid_cites: list[int], invalid_cites: list[int]) -> float:
    """被引用证据中合法（存在于本次上下文）的比例"""
    total = len(valid_cites) + len(invalid_cites)
    return len(valid_cites) / total if total else 0.0


def citation_coverage(key_claims: int, claims_with_valid_cite: int) -> float:
    """关键主张中实际附有合法引用的比例"""
    return claims_with_valid_cite / key_claims if key_claims else 0.0


def claim_support_rate(claims: list[dict]) -> float:
    """所有主张中 decision=support 的比例"""
    if not claims:
        return 0.0
    supported = sum(1 for c in claims if c.get("decision") == "supported")
    return supported / len(claims)


def unsupported_claim_rate(claims: list[dict]) -> float:
    return 1.0 - claim_support_rate(claims) if claims else 1.0


def abstention_quality(question_type: str, decision: str) -> float:
    """证据不足题合理拒答得 1；证据充分题误拒答得 0；否则 0.5"""
    if question_type == "insufficient":
        return 1.0 if decision == "REFUSE" else 0.0
    else:
        return 1.0 if decision == "PASS" else 0.0
