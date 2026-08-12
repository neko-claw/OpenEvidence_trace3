#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为恢复为可回答的题（原 refusal，gold 为空）生成候选 gold 证据。

策略：用"答案文本 + 题干关键词"在 evidence.db 的 title/abstract 中做词法匹配，
取命中分数最高的文献作为候选 gold（gold_verification_status=pending_review）。
候选 gold 仅用于检索评测（Hit@k/Recall@50）的初步对齐，正式冻结前须人工核验。

输出：更新 test_set/questions_110.json 的 gold_source_ids / gold_literature /
gold_candidates（含匹配关键词与分数）。
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
QUESTIONS_110 = BASE_DIR / "test_set" / "questions_110.json"
EVIDENCE_DB = BASE_DIR / "data" / "processed" / "evidence.db"

# 停用词/过于宽泛的词
STOPWORDS = {
    "patient", "patients", "the", "a", "an", "of", "in", "with", "and", "or",
    "is", "are", "was", "were", "which", "following", "most", "likely", "best",
    "blood", "pressure", "treatment", "treated", "therapy", "hypertension",
    "hypertensive", "cholesterol", "lipid", "ldl", "hdl", "effect", "effects",
    "levels", "level", "increase", "decreased", "due", "drug", "medication",
    "increase", "caused", "patient", "man", "woman", "male", "female", "history",
    "presents", "presented", "comes", "physical", "examination", "mg",
}
TOKEN_RE = re.compile(r"[a-z]{3,}")


def extract_keywords(q: dict) -> list[str]:
    """提取答案+题干关键词（小写，去停用词）。"""
    at = str(q.get("answer_text") or "") or ""
    opts = q.get("options") or {}
    answer = q.get("answer")
    if answer and isinstance(answer, str) and answer[:1] in "ABCDE" and not at:
        at = opts.get(answer[:1].upper(), "")
    question = str(q.get("question") or "")
    text = f"{at} {question}"
    tokens = [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]
    # 答案词优先，题干词次之；按 (答案词, -频率, 字母序) 稳定排序，保证跨进程可复现
    at_tokens = set(TOKEN_RE.findall(at.lower()))
    ranked = sorted(set(tokens), key=lambda t: (t not in at_tokens, -tokens.count(t), t))
    return ranked[:8]


def main() -> int:
    doc = json.loads(Path(QUESTIONS_110).read_text(encoding="utf-8"))
    questions = doc["questions"]

    con = sqlite3.connect(str(EVIDENCE_DB))
    cur = con.cursor()
    filled = 0
    for q in questions:
        if q.get("gold_source_ids") or q.get("answerability") != "true":
            continue
        kws = extract_keywords(q)
        if not kws:
            continue
        scores: dict[str, float] = {}
        for kw in kws:
            for r in cur.execute(
                    "SELECT id, title, abstract_or_chunk FROM evidence "
                    "WHERE title LIKE ? OR abstract_or_chunk LIKE ? LIMIT 20",
                    (f"%{kw}%", f"%{kw}%")):
                eid, title, abstract = r[0], r[1] or "", r[2] or ""
                scores[eid] = scores.get(eid, 0) + 2.0 if kw in title.lower() else scores.get(eid, 0) + 1.0
        if not scores:
            continue
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:3]
        cands = [eid for eid, _ in top]
        q["gold_source_ids"] = cands
        q["gold_literature"] = cands
        q["gold_verified"] = False
        q["gold_verification_status"] = "pending_review"
        q["gold_candidates"] = {
            "ids": cands,
            "keywords": kws,
            "scores": {eid: round(s, 1) for eid, s in top},
            "note": "词法检索候选，须人工核验后才能冻结",
        }
        filled += 1
    con.close()

    Path(QUESTIONS_110).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n",
        encoding="utf-8")
    with_gold = sum(1 for q in questions if q.get("gold_source_ids"))
    print(f"filled gold candidates: {filled} | 全库有 gold 的题: {with_gold}/{len(questions)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
