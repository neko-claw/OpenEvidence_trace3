#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 questions_110.json 生成 qrels.jsonl（对齐实施规划 3.1 的 Qrel 契约）。

Qrel 契约字段：
  question_id, atomic_point_id, evidence_id, evidence_span_id,
  relevance_grade, stance, valid_from, valid_to, reviewer, adjudication

说明：
- atomic_point_id：暂以题级 gold 证据行表示（key_points 级别的原子主张
  由评分指南提供，题级 qrels 先行落地）；格式 {question_id}:{evidence_index}。
- evidence_id：取 gold_source_ids / supported_evidence 的并集。
- relevance_grade：gold 证据为 2（强相关）；supported_evidence 中的其余证据为 1。
- stance：不预设支持/反对，统一 unknown，由后续核验回合填充。
- reviewer：auto_pipeline（当前全部为自动管线产物，人工核验后才可冻结）。
- adjudication：pending_review / manual。

输出：test_set/qrels.jsonl
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
QUESTIONS_110 = BASE_DIR / "test_set" / "questions_110.json"
OUT_QUELS = BASE_DIR / "test_set" / "qrels.jsonl"


def main() -> int:
    doc = json.loads(Path(QUESTIONS_110).read_text(encoding="utf-8"))
    questions = doc["questions"]

    rows = []
    for q in questions:
        qid = str(q["id"])
        gold = list(dict.fromkeys(q.get("gold_source_ids") or q.get("gold_literature") or []))
        supported = list(dict.fromkeys(q.get("supported_evidence") or []))
        if not gold and not supported:
            continue
        evidence = list(dict.fromkeys(gold + supported))
        for idx, eid in enumerate(evidence, start=1):
            rows.append({
                "question_id": qid,
                "atomic_point_id": f"{qid}:ap:{idx}",
                "evidence_id": eid,
                "evidence_span_id": None,  # 题级 qrels 不定位到 chunk，待证据片段核验
                "relevance_grade": 2 if eid in gold else 1,
                "stance": "unknown",
                "valid_from": q.get("as_of_date"),
                "valid_to": None,
                "reviewer": "auto_pipeline",
                "adjudication": "manual" if q.get("adjudication_status") == "manual"
                                 else "pending_review",
            })

    with OUT_QUELS.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"qrels: {len(rows)} 行 / {len(set(r['question_id'] for r in rows))} 题")
    print("adjudication:", dict(Counter(r["adjudication"] for r in rows)))
    print("relevance_grade:", dict(Counter(r["relevance_grade"] for r in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
