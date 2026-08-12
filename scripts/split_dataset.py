#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结题集输入文件，恢复 B2 题集的可复现性（替代缺失的 build_dev_test_split.py 输入产物）。

背景：b2 分支的 test_set/README.md 引用 build_dev_test_split.py /
extract_oracle_support.py 及 questions_test.json / refusal_split.json /
question_rag_split.jsonl / corpus_coverage_audit.jsonl / oracle_support_annotation.jsonl，
但这些文件未纳入版本库，题集无法从已提交代码重建。

本脚本以唯一已提交的规范入口 test_set/questions_110.json 为准，
确定性拆出三类输入，保证后续 build_questions_110.py 可完整重跑：

- test_set/questions_test.json     100 道公开基准题（含难度、topic_tags、pmid 等原始字段）
- test_set/refusal_split.json      10 道原始拒答题（REF-001 ~ REF-010）
- test_set/question_rag_split.jsonl 110 题 dev/test 划分（3:7，冻结 seed 42 分层抽样结果）

不改变任何 id / split / rag_category / 题目文本，只做字段投影。

用法（必须用项目 conda 环境）:
    .conda/Scripts/python.exe scripts/split_dataset.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
QUESTIONS_110 = BASE_DIR / "test_set" / "questions_110.json"
OUT_QUESTIONS = BASE_DIR / "test_set" / "questions_test.json"
OUT_REFUSALS = BASE_DIR / "test_set" / "refusal_split.json"
OUT_SPLIT = BASE_DIR / "test_set" / "question_rag_split.jsonl"

# 从 questions_110.json 回填到 questions_test.json 的原始基准字段
BENCHMARK_FIELDS = [
    "id", "source", "question", "options", "answer", "answer_text",
    "difficulty", "difficulty_level", "difficulty_raw", "difficulty_norm1",
    "topic_tags", "matched_keywords", "hypertension_lipid_only", "pmid",
]


def main() -> int:
    doc = json.loads(Path(QUESTIONS_110).read_text(encoding="utf-8"))
    questions = doc["questions"]

    benchmark = []
    refusals = []
    split_rows = []
    for q in questions:
        rec = {k: q.get(k) for k in BENCHMARK_FIELDS}
        # refusal 题的拒答字段属于原始 REF 题，一并保留
        for k in ("answerable", "expected_action", "refusal_reason", "note"):
            if q.get(k) is not None:
                rec[k] = q.get(k)
        split_rows.append({
            "id": q["id"],
            "source": q["source"],
            "split": q["split"],
            "rag_category": q["rag_category"],
            "audit_status": q.get("audit_status"),
        })
        if q.get("source") == "ORIGINAL_REFUSAL":
            refusals.append(rec)
        else:
            benchmark.append(rec)

    # 保持与 questions_110.json 相同的题序（按 id）
    benchmark.sort(key=lambda r: str(r["id"]))
    refusals.sort(key=lambda r: str(r["id"]))
    split_rows.sort(key=lambda r: (str(r["split"]), str(r["id"])))

    OUT_QUESTIONS.write_text(
        json.dumps({"version": "1.0", "count": len(benchmark), "questions": benchmark},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_REFUSALS.write_text(
        json.dumps({"version": "1.0", "count": len(refusals), "questions": refusals},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_SPLIT.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in split_rows) + "\n",
        encoding="utf-8")

    print(f"questions_test.json: {len(benchmark)} 题")
    print(f"refusal_split.json: {len(refusals)} 题")
    print("question_rag_split.jsonl:", dict(Counter(r["split"] for r in split_rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
