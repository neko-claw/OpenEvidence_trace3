"""可解释特征重排（P0 核心创新点）：语义/词法/RRF/PICO/证据等级/时效/来源质量 - 冗余"""
from __future__ import annotations

import math
from datetime import datetime, date
from typing import Any

from core.dataclasses import Evidence


def _evidence_level_score(level: str) -> float:
    return {
        "guideline": 1.0, "systematic_review": 0.95, "meta_analysis": 0.95,
        "rct": 0.9, "cohort": 0.7, "trial": 0.7, "review": 0.65,
        "expert": 0.4, "unknown": 0.5,
    }.get(level.lower(), 0.5)


def _freshness_score(published_at: str, q_freshness: str, now: date | None = None) -> float:
    """freshness: stable 题降低时效权重用乘法因子；up_to_date 题按年份衰减"""
    now = now or date.today()
    try:
        y = int(published_at[:4])
    except (TypeError, ValueError):
        return 0.5
    age = max(0, now.year - y)
    if age <= 1:
        return 1.0
    return max(0.1, 1.0 - 0.08 * (age - 1))


def _source_quality_score(source_type: str) -> float:
    return {
        "guideline": 1.0, "pubmed": 0.8, "europepmc": 0.8, "clinicaltrial": 0.7,
        "wiki": 0.6,
    }.get(source_type, 0.6)


def _pico_match_score(ev: Evidence, q_text: str) -> float:
    """PICO 字段与问题词面重合度（简化版，字段缺失时中性 0.5）"""
    fields = [ev.population, ev.intervention, ev.comparator, ev.outcome, ev.title]
    hits = 0
    total = 0
    q_tokens = set(q_text.lower())
    for f in fields:
        if not f:
            continue
        total += 1
        f_tokens = set(f.lower().split())
        if f_tokens and (f_tokens & q_tokens):
            hits += 1
    return hits / total if total else 0.5


def feature_rerank(candidates: list[tuple[str, float]],
                   evidences: dict[str, Evidence],
                   q_text: str,
                   weights: dict[str, float],
                   q_freshness: str = "stable",
                   verbose: bool = False) -> list[dict]:
    """对候选 [(doc_id, rrf_score)] 计算特征分并加权。

    返回按最终分降序的 dict 列表：
    [{doc_id, semantic, lexical, pico_match, evidence_level, freshness,
      source_quality, redundancy, final}]
    """
    results = []
    for rank, (doc_id, rrf_score) in enumerate(candidates):
        ev = evidences[doc_id]
        semantic = float(rrf_score) if rrf_score > 0 else 0.0  # RRF 近似语义融合分
        lexical = 0.5
        pico = _pico_match_score(ev, q_text)
        e_level = _evidence_level_score(ev.evidence_level)
        fresh = _freshness_score(ev.published_at, q_freshness)
        src = _source_quality_score(ev.source_type)
        results.append({
            "doc_id": doc_id,
            "semantic": semantic, "lexical": lexical, "pico_match": pico,
            "evidence_level": e_level, "freshness": fresh, "source_quality": src,
            "redundancy": 0.0, "rank_in": rank,
        })

    # 冗余度：与更高分候选的文本重合度（MMR 阶段还会进一步处理）
    for i, r in enumerate(results):
        ev_i = evidences[r["doc_id"]]
        max_sim = 0.0
        for j in range(i):
            ev_j = evidences[results[j]["doc_id"]]
            sim = _text_sim(ev_i.text, ev_j.text)
            max_sim = max(max_sim, sim)
        r["redundancy"] = max_sim

    for r in results:
        r["final"] = (
            weights["semantic"] * r["semantic"]
            + weights["lexical"] * r["lexical"]
            + weights["pico_match"] * r["pico_match"]
            + weights["evidence_level"] * r["evidence_level"]
            + weights["freshness"] * r["freshness"]
            + weights["source_quality"] * r["source_quality"]
            + weights["redundancy"] * r["redundancy"]
        )

    results.sort(key=lambda r: r["final"], reverse=True)
    if verbose:
        for r in results[:10]:
            print(f'{r["doc_id"]:24s} final={r["final"]:.3f} '
                  f'sem={r["semantic"]:.2f} lex={r["lexical"]:.2f} '
                  f'pico={r["pico_match"]:.2f} level={r["evidence_level"]:.2f} '
                  f'fresh={r["freshness"]:.2f} src={r["source_quality"]:.2f} '
                  f'red={r["redundancy"]:.2f}')
    return results


def _text_sim(a: str, b: str) -> float:
    """字符级 Jaccard 近似，快速算冗余度"""
    if not a or not b:
        return 0.0
    set_a, set_b = set(a[:1500]), set(b[:1500])
    if not set_a or not set_b:
        return 0.0
    inter = len(set_a & set_b)
    return inter / (len(set_a) + len(set_b) - inter)
