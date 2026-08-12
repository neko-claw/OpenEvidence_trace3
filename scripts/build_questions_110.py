#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 100 道测试题 + 10 道原始拒答合并为单文件 110 题 JSON。

以 question_literature_annotation.jsonl 的标注为主体，回填题目原始字段
（难度、topic_tags、拒答原因等），输出 test_set/questions_110.json。

用法（必须用项目 conda 环境）:
    .conda/Scripts/python.exe scripts/build_questions_110.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
ANNOTATION = BASE_DIR / "test_set" / "question_literature_annotation.jsonl"
QUESTIONS = BASE_DIR / "test_set" / "questions_test.json"
REFUSALS = BASE_DIR / "test_set" / "refusal_split.json"
OUT = BASE_DIR / "test_set" / "questions_110.json"


def load_jsonl(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def load_items(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("questions"), list):
        return data["questions"]
    return data


def main():
    ann = load_jsonl(ANNOTATION)
    qs = load_items(QUESTIONS)
    refs = load_items(REFUSALS)
    q_by = {(q.get("source"), str(q.get("id"))): q for q in qs}
    ref_by = {str(r.get("id")): r for r in refs}

    questions = []
    for r in ann:
        q = q_by.get((r.get("source"), str(r.get("id")))) or {}
        ref = ref_by.get(str(r.get("id"))) or {}
        rec = {
            "id": r["id"],
            "source": r["source"],
            "split": r["split"],
            "rag_category": r["rag_category"],
            "audit_status": r.get("audit_status"),
            "question": r.get("question"),
            "options": r.get("options"),
            "answer": r.get("answer"),
            "answer_text": r.get("answer_text"),
            "difficulty": q.get("difficulty"),
            "difficulty_level": q.get("difficulty_level"),
            "difficulty_raw": q.get("difficulty_raw"),
            "difficulty_norm1": q.get("difficulty_norm1"),
            "topic_tags": q.get("topic_tags"),
            "matched_keywords": q.get("matched_keywords"),
            "hypertension_lipid_only": q.get("hypertension_lipid_only"),
            "pmid": q.get("pmid"),
            "answerable": ref.get("answerable"),
            "expected_action": ref.get("expected_action"),
            "refusal_reason": ref.get("refusal_reason"),
            "note": ref.get("note"),
            "literature_used": r.get("literature_used"),
            "literature_count": r.get("literature_count"),
            "supported_evidence": r.get("supported_evidence"),
            "supported_literature": r.get("supported_literature"),
            "supported_count": r.get("supported_count"),
            "candidate_literature": r.get("candidate_literature"),
            "candidate_count": r.get("candidate_count"),
            "gold_source_ids": r.get("gold_source_ids") or r.get("gold_literature") or [],
            "gold_literature": r.get("gold_literature"),
            "gold_count": r.get("gold_count"),
            "gold_verified": r.get("gold_verified"),
            "evidence_retrieved": r.get("evidence_retrieved"),
            "evidence_count": r.get("evidence_count"),
            "retrieval_config": r.get("retrieval_config"),
        }
        questions.append(rec)

    by_split = defaultdict(Counter)
    by_cat = Counter()
    for r in questions:
        by_split[r["split"]][r["rag_category"]] += 1
        by_cat[r["rag_category"]] += 1

    doc = {
        "version": "1.0",
        "created_at": date.today().isoformat(),
        "description": "OpenEvidence 赛道 3 测试题集：100 道公开基准题 + 10 道原始拒答",
        "total": len(questions),
        "dev_count": sum(by_split["dev"].values()),
        "test_count": sum(by_split["test"].values()),
        "by_category": dict(by_cat),
        "by_split": {k: dict(v) for k, v in by_split.items()},
        "source_files": [
            "test_set/questions_test.json",
            "test_set/refusal_split.json",
            "test_set/question_rag_split.jsonl",
            "test_set/question_literature_annotation.jsonl",
        ],
        "questions": questions,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成 {OUT} ({len(questions)} 题)")
    print(json.dumps(doc["by_split"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
