#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把"检索审计结果"与"医学可回答性裁定"解耦，写入 questions_110.json。

问题背景（详见 docs/b2_dataset_review.md）：
b2 当前把 rag_category（easy/hard/refusal）直接当作"题目可回答性"，
其中 49 道来自公开基准（MIRAGE/MedQA/MedExpQA）的题仅因 RAG 检索审计 fail
就被标为 refusal / answerable=False / expected_action=REFUSE。
这造成三重问题：
  1) 循环论证：类别标签来自被测检索管线的失败，而非独立的医学裁定；
  2) 类别污染：TEST 集 41/77 题被标为拒答题，A/B/C/D 主结论被拒答行为主导；
  3) 评分矛盾：scoring_guide 中 41 道拒答题仍列有"正确答案/错误答案"，
     与"正确拒答=满分"规则冲突，人工/LLM judge 无所适从。

本脚本不重判任何题目，只把现有信息显式拆成三个正交字段：
- retrieval_audit      检索审计结果（pass / corpus_only / fail，诊断信息）
- answerability        医学可回答性裁定（true / false / unknown）
- adjudication         裁定来源与状态（auto / pending_review / manual）

其中 answerability=unknown 的题（benchmark 有已知标准答案但检索未获支持）
必须由医学人员复核后才可进入 TEST 四类分层，在此之前不得按拒答题计入。

输出：
- 更新 test_set/questions_110.json（只增字段，不改 id/split/category/题目/答案）
- test_set/answerability_review.jsonl（待人工裁定清单）
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
QUESTIONS_110 = BASE_DIR / "test_set" / "questions_110.json"
REVIEW_OUT = BASE_DIR / "test_set" / "answerability_review.jsonl"

# 人工裁定过的题（来自 annotate_question_literature.py 的 REFUSE_OVERRIDE /
# HARD_SUPPORT_OVERRIDE / REF-* 手工拒答标注；见该脚本与 test_set/README.md）
# 4 道从 hard 改判 refusal 的题 id（REFUSE_OVERRIDE）
MANUAL_REFUSE_IDS = {
    "clinical_knowledge-254",
    "4682d46d-f791-48cc-ac4d-b2a73fbb18c4",
    "medqa-usmle-train-train-00782",
    "medqa-usmle-train-train-01389",
}
# 5 道人工补写支撑文献的 hard 题（HARD_SUPPORT_OVERRIDE）
MANUAL_HARD_IDS = {
    "0438",
    "0516",
    "b5a8425a-1ddf-41e1-9ffa-c2088ce2897e",
    "297ab88f-0697-406b-8994-332269314289",
    "medqa-usmle-train-train-05202",
}
# REF-007：有意设计的冲突证据题，期望 WARN 而非 REFUSE（answerable 视为 true）
REF_CONFLICT_IDS = {"REF-007"}


def adjudicate(q: dict) -> dict:
    """返回 (answerability, adjudication_status, note)"""
    qid = str(q.get("id"))
    category = q.get("rag_category")
    source = q.get("source")

    # 1) 人工改判 / 原始拒答题：裁定已完成
    if qid in REF_CONFLICT_IDS:
        return "true", "manual", "冲突证据题，期望 WARN（有意设计）"
    if source == "ORIGINAL_REFUSAL":
        return "false", "manual", "人工原创拒答题（REF-001~REF-010）"
    if qid in MANUAL_REFUSE_IDS:
        return "false", "manual", "人工裁定：语料无直接支撑，从 hard 改判 refusal"
    if qid in MANUAL_HARD_IDS:
        return "true", "manual", "人工补写支撑文献后保留 hard"

    # 2) easy/hard：有 gold_source_ids，视为可回答（gold 是否人工核验另见 gold_verified）
    if category in ("easy", "hard"):
        return "true", "auto", "检索审计通过/候选命中，gold 为自动管线产物待人工核验"

    # 3) refusal：区分"真不可回答"与"检索失败待裁定"
    if category == "refusal":
        return "unknown", "pending_review", (
            "基准题有已知标准答案，但 RAG 检索未获支持；不可据此判为不可回答，"
            "需医学人员复核后再定 answerability"
        )

    return "unknown", "pending_review", "未知类别"


def main() -> int:
    doc = json.loads(Path(QUESTIONS_110).read_text(encoding="utf-8"))
    questions = doc["questions"]
    review: list[dict] = []

    for q in questions:
        ans, status, note = adjudicate(q)
        q["answerability"] = ans
        q["adjudication_status"] = status
        q["adjudication_note"] = note
        # 诊断字段：保留检索审计原始结果（不再与 answerability 混用）
        q["retrieval_audit"] = q.get("audit_status")
        # 记录 gold 是否经人工核验：只有存在 gold 且裁定为 manual 才算已核验，
        # 避免“语料里有文献”被误读为“gold 已人工核验”（实施规划 §6.3 要求人工 gold 核验）
        q["gold_verified"] = status == "manual" and bool(q.get("gold_source_ids"))
        if status == "pending_review":
            review.append({
                "id": q["id"],
                "source": q["source"],
                "split": q["split"],
                "rag_category": q["rag_category"],
                "audit_status": q.get("audit_status"),
                "benchmark_answer": q.get("answer_text"),
                "literature_used_count": len(q.get("literature_used") or []),
                "gold_source_ids": q.get("gold_source_ids") or [],
                "proposed_answerability": "unknown（待医学人员裁定 true/false）",
                "question": q.get("question"),
            })

    Path(QUESTIONS_110).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n",
        encoding="utf-8")
    # 保持原始文件 CRLF 行尾（Windows 环境），避免整文件 diff 噪声
    with REVIEW_OUT.open("w", encoding="utf-8") as f:
        for rec in review:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("answerability:", dict(Counter(q.get("answerability") for q in questions)))
    print("adjudication_status:", dict(Counter(q.get("adjudication_status") for q in questions)))
    print(f"review lines: {len(review)} -> {REVIEW_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
