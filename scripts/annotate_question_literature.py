#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为开发集/测试集每题跑 RAG，标注涉及的全部文献。

对每题分别用 normal（题目+选项）和 oracle（题目+答案+选项）查询，
跑 BM25 + BGE-M3 + RRF 混合检索 top-50，合并：
  - normal / oracle 检索命中的全部证据
  - 覆盖审计中 judge 判定支撑的证据（supporting_ids）
  - 题面自带 PMID（gold）

输出字段：
  literature_used      文章级文献 ID（PMID/PMCID/EPMC/指南；fulltext chunk
                       归并到所属文章；不含 wiki/hesperian/trial），无则 NULL
  evidence_retrieved   RAG 原始命中的全部证据 ID（含 chunk/trial/wiki/hesperian）

用法（必须用项目 conda 环境）:
    .conda/Scripts/python.exe scripts/annotate_question_literature.py

输出:
    test_set/question_literature_annotation.jsonl
    test_set/question_literature_summary.json
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

os_import = __import__("os")
os_import.environ.setdefault("HF_HUB_OFFLINE", "1")
os_import.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import check_corpus_coverage as ccc


BASE_DIR = Path(__file__).resolve().parents[1]
SPLIT = BASE_DIR / "test_set" / "question_rag_split.jsonl"
QUESTIONS = BASE_DIR / "test_set" / "questions_test.json"
AUDIT = BASE_DIR / "test_set" / "corpus_coverage_audit.jsonl"
ORACLE_SUPPORT = BASE_DIR / "test_set" / "oracle_support_annotation.jsonl"
CURATED_ALL = BASE_DIR / "data" / "processed" / "curated_rerank_all.jsonl"
OUT_JSONL = BASE_DIR / "test_set" / "question_literature_annotation.jsonl"
OUT_SUMMARY = BASE_DIR / "test_set" / "question_literature_summary.json"

TOP_K = 50
BM25_K = 50
VECTOR_K = 50

# 人工裁定（已确认，不再需要复核清单）：
# 1) 这 4 道语料无直接支撑，从 hard 改判 refusal
REFUSE_OVERRIDE = {
    "clinical_knowledge-254",
    "4682d46d-f791-48cc-ac4d-b2a73fbb18c4",
    "medqa-usmle-train-train-00782",
    "medqa-usmle-train-train-01389",
}
# 2) 这 5 道语料有直接原文，保留 hard 并写入支撑文献
HARD_SUPPORT_OVERRIDE = {
    "0438": ["wikipedia:Thiazide#1", "wikipedia:Thiazide#2"],
    "0516": ["wikipedia:ACE inhibitor#3", "wikipedia:Angiotensin II receptor blocker#1"],
    "b5a8425a-1ddf-41e1-9ffa-c2088ce2897e": [
        "wikipedia:LDL receptor#1",
        "wikipedia:Apolipoprotein B#1",
    ],
    "297ab88f-0697-406b-8994-332269314289": ["wikipedia:Very low-density lipoprotein#1"],
    "medqa-usmle-train-train-05202": [
        "wikipedia:Obstructive sleep apnea#1",
        "wikipedia:Obstructive sleep apnea#15",
    ],
}


def load_jsonl(path):
    rows = []
    if not Path(path).exists():
        return rows
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_items(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("questions"), list):
        return data["questions"]
    return data


def norm_letter(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s[0] in "ABCDEabcde":
        return s[0].upper()
    m = re.match(r"[\(\[\{]*\s*([A-Ea-e])", s)
    return m.group(1).upper() if m else None


def article_level_id(doc):
    """把任意证据记录归并到文章级稳定 ID（文献字段用）。"""
    kind = doc.get("record_kind") or ""
    if kind in ("abstract", "guideline"):
        return doc["id"]
    if kind == "fulltext_chunk":
        if doc.get("pmcid"):
            return f"pmcid:{doc['pmcid']}"
        if doc.get("pmid"):
            return f"pmid:{doc['pmid']}"
        base = str(doc.get("id") or "").split(":chunk:")[0]
        return base or doc.get("id")
    return None


def normalize_id(rid):
    """去掉 judge 返回 ID 偶尔带的外层方括号/引号。"""
    s = str(rid or "").strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return s.strip().strip('"').strip("'")


def article_lit_id(rid, doc_by_id):
    """把原始 evidence ID 归并成文章级文献 ID；非文献（wiki/hesperian/trial）返回 None。"""
    rid = normalize_id(rid)
    doc = doc_by_id.get(rid) or {}
    aid = article_level_id(doc) if doc else None
    if aid:
        return aid
    if rid.startswith(("pmid:", "pmcid:", "epmc:", "guideline:")):
        return rid.split(":chunk:")[0]
    if rid.startswith("wikipedia:"):
        return rid
    return None


def main():
    rows = load_jsonl(SPLIT)
    questions = { (q.get("source"), str(q.get("id"))): q for q in load_items(QUESTIONS) }
    audit = { (r["source"], str(r["id"])): r for r in load_jsonl(AUDIT) }
    oracle = {
        (r["source"], str(r["id"])): r
        for r in load_jsonl(ORACLE_SUPPORT)
    } if Path(ORACLE_SUPPORT).exists() else {}
    curated_by_q = {}
    if Path(CURATED_ALL).exists():
        for line in CURATED_ALL.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            cr = json.loads(line)
            if cr.get("rank_normal") is not None or cr.get("rank_oracle") is not None:
                curated_by_q.setdefault(str(cr.get("question")), []).append(cr.get("id"))

    docs, bm25, embedder, embeddings = ccc.build_index(
        ccc.DEFAULT_EVIDENCE,
        ccc.DEFAULT_FULLTEXT,
        ccc.DEFAULT_WIKIPEDIA,
        ccc.DEFAULT_HESPERIAN,
        ccc.DEFAULT_EMBEDDING_MODEL,
        ccc.DEFAULT_EMBEDDING_CACHE,
        ccc.DEFAULT_EMBEDDING_IDS_CACHE,
        ccc.DEFAULT_EMBEDDING_HASHES_CACHE,
        use_embedding=True,
        max_seq_length=2048,
    )
    doc_by_id = {d["id"]: d for d in docs}
    print(f"语料: {len(docs)} 条 | 待标注题目: {len(rows)}")

    annotated = []
    for i, row in enumerate(rows, start=1):
        q = questions.get((row.get("source"), row.get("id"))) or {}
        options = q.get("options") or row.get("options") or {}
        gold_letter = norm_letter(q.get("answer")) or norm_letter(row.get("answer"))
        answer_text = q.get("answer_text") or row.get("answer_text") or options.get(gold_letter, "")
        question_text = q.get("question") or row.get("question") or ""
        option_text = " ".join(str(v) for v in options.values())
        q_query = f"{question_text} {option_text}".strip()
        oracle_query = f"{question_text} {answer_text} {option_text}".strip()

        retrieved_ids = []
        for query in (q_query, oracle_query):
            hits = ccc.hybrid_retrieve(
                docs, bm25, embedder, embeddings, query,
                top_k=TOP_K, bm25_k=BM25_K, vector_k=VECTOR_K,
            )
            retrieved_ids.extend(h["id"] for h in hits)

        supporting = [
            normalize_id(s)
            for s in (audit.get((row.get("source"), row.get("id")), {}).get("supporting_ids") or [])
        ]
        oracle_row = oracle.get((row.get("source"), row.get("id")), {})
        supporting += [normalize_id(s) for s in (oracle_row.get("oracle_supporting_ids") or [])]
        supporting = list(dict.fromkeys(supporting))
        gold_pmids = q.get("pmid") or []
        if isinstance(gold_pmids, str):
            gold_pmids = [gold_pmids]
        gold_ids = [f"pmid:{p}" for p in gold_pmids if p]

        all_ids = list(dict.fromkeys(
            [normalize_id(x) for x in retrieved_ids] + supporting + gold_ids
        ))
        lit_ids = []
        supported_lit = []
        supported_ev = []
        for rid in all_ids:
            aid = article_lit_id(rid, doc_by_id)
            if aid is None and rid in gold_ids:
                aid = rid
            if aid and aid not in lit_ids:
                lit_ids.append(aid)
            if rid in supporting:
                supported_ev.append(rid)
                if aid and aid not in supported_lit:
                    supported_lit.append(aid)
        supported_ev = sorted(set(supported_ev))
        # oracle/精选候选没有进 top-50 但 judge 已确认支撑的，也补进 supported_literature
        for s in supporting:
            aid = article_lit_id(s, doc_by_id)
            if aid and aid not in supported_lit:
                supported_lit.append(aid)

        candidate_lit = None
        if row["rag_category"] == "hard":
            cand = curated_by_q.get(str(row["id"])) or []
            candidate_lit = sorted(set(
                a for c in cand for a in [article_lit_id(c, doc_by_id)] if a
            )) if cand else None

        gold_lit = sorted(set(supported_lit + gold_ids)) if (supported_lit or gold_ids) else None

        rec = dict(row)
        rec["literature_used"] = sorted(lit_ids) if lit_ids else None
        rec["literature_count"] = len(lit_ids)
        rec["supported_evidence"] = supported_ev if supported_ev else None
        rec["supported_literature"] = sorted(set(supported_lit)) if supported_lit else None
        rec["supported_count"] = len(set(supported_lit))
        rec["candidate_literature"] = candidate_lit
        rec["candidate_count"] = len(candidate_lit) if candidate_lit else 0
        rec["gold_literature"] = gold_lit
        rec["gold_count"] = len(gold_lit) if gold_lit else 0
        rec["evidence_retrieved"] = all_ids
        rec["evidence_count"] = len(all_ids)
        rec["retrieval_config"] = {
            "method": "BM25 + BGE-M3 + RRF",
            "top_k": TOP_K,
            "bm25_k": BM25_K,
            "vector_k": VECTOR_K,
            "queries": ["normal", "oracle"],
        }

        # 人工裁定覆盖（不再需要人工复核）
        qid = str(row["id"])
        if qid in REFUSE_OVERRIDE:
            rec["rag_category"] = "refusal"
            rec["supported_evidence"] = None
            rec["supported_literature"] = None
            rec["supported_count"] = 0
            rec["candidate_literature"] = None
            rec["candidate_count"] = 0
            rec["gold_literature"] = None
            rec["gold_count"] = 0
        elif qid in HARD_SUPPORT_OVERRIDE:
            rec["rag_category"] = "hard"
            extra = HARD_SUPPORT_OVERRIDE[qid]
            supported_ev = list(dict.fromkeys((rec.get("supported_evidence") or []) + extra))
            supported_lit = list(dict.fromkeys((rec.get("supported_literature") or []) + extra))
            rec["supported_evidence"] = sorted(supported_ev)
            rec["supported_literature"] = sorted(supported_lit)
            rec["supported_count"] = len(supported_lit)
            gold = list(dict.fromkeys(supported_lit + gold_ids))
            rec["gold_literature"] = sorted(gold) if gold else None
            rec["gold_count"] = len(gold)
        # gold 是否已核验：只有人工裁定过的题才算 verified；
        # 自动管线产物（检索命中 + judge 判定 + oracle 查询）一律 pending_review，
        # 避免把“语料里有文献”误读为“gold 已人工核验”（实施规划要求人工 gold 核验）。
        rec["gold_derivation"] = "manual_override" if qid in (
            REFUSE_OVERRIDE | HARD_SUPPORT_OVERRIDE
        ) else "auto_retrieval_oracle_judge"
        rec["gold_verified"] = (
            rec["gold_derivation"] == "manual_override"
            and bool(rec.get("gold_literature"))
        )
        rec["gold_verification_status"] = (
            "verified" if rec["gold_verified"]
            else ("pending_review" if rec.get("gold_literature") else "no_gold")
        )
        rec["gold_source_ids"] = rec.get("gold_literature") or []
        annotated.append(rec)
        if i == 1 or i % 20 == 0 or i == len(rows):
            print(f"进度: {i}/{len(rows)}")

    OUT_JSONL.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in annotated) + "\n",
        encoding="utf-8",
    )

    by_cat = defaultdict(list)
    for r in annotated:
        by_cat[r["rag_category"]].append(r)
    summary = {
        "total": len(annotated),
        "by_category": {
            cat: {
                "count": len(items),
                "with_literature": sum(1 for r in items if r.get("literature_used")),
                "null_literature": sum(1 for r in items if not r.get("literature_used")),
                "avg_literature_count": round(sum(r["literature_count"] for r in items) / len(items), 2) if items else 0,
                "with_supported": sum(1 for r in items if r.get("supported_literature")),
                "null_supported": sum(1 for r in items if not r.get("supported_literature")),
                "avg_supported_count": round(sum(r["supported_count"] for r in items) / len(items), 2) if items else 0,
                "with_supported_evidence": sum(1 for r in items if r.get("supported_evidence")),
                "with_candidate": sum(1 for r in items if r.get("candidate_literature")),
                "with_gold": sum(1 for r in items if r.get("gold_literature")),
            }
            for cat, items in by_cat.items()
        },
        "avg_literature_count": round(sum(r["literature_count"] for r in annotated) / len(annotated), 2),
        "top_k": TOP_K,
        "retrieval": "BM25 + BGE-M3 + RRF",
    }
    OUT_SUMMARY.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("标注完成:", json.dumps(summary["by_category"], ensure_ascii=False))
    print(f"输出: {OUT_JSONL} / {OUT_SUMMARY}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
