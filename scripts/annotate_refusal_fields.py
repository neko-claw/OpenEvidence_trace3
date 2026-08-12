"""为 test_set/questions_110.json 的 refusal 题补齐拒答字段。

规则：
- 已有 answerable / expected_action / refusal_reason 的 REF-* 题保留原值；
- 缺失的 refusal 题（当前为检索审计 fail 自动判定）统一标为：
    answerable=False, expected_action=REFUSE, refusal_reason=no_evidence,
    refusal_evidence_status=hits_unsupported
- 所有 refusal 题补 refusal_evidence_status，区分 empty_result / hits_unsupported /
  out_of_scope / conflict / injection；
- REF-007 是冲突证据题，保留 WARN，并写入“有意设计”说明。

输出：
- 更新 test_set/questions_110.json
- test_set/refusal_auto_annotation_review.jsonl（自动标注清单，供人工复核）
"""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
QUESTIONS = BASE_DIR / "test_set" / "questions_110.json"
REVIEW_OUT = BASE_DIR / "test_set" / "refusal_auto_annotation_review.jsonl"

REASON_TO_EVIDENCE_STATUS = {
    "out_of_scope": "out_of_scope",
    "conflict": "conflict",
    "injection": "injection",
    "empty_result": "empty_result",
    "no_evidence": "hits_unsupported",
}


def derive_evidence_status(q: dict) -> str:
    reason = q.get("refusal_reason")
    if reason in REASON_TO_EVIDENCE_STATUS:
        return REASON_TO_EVIDENCE_STATUS[reason]
    has_hits = bool(q.get("literature_used") or q.get("evidence_retrieved"))
    return "hits_unsupported" if has_hits else "empty_result"


def main() -> None:
    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    questions = data["questions"]
    auto_annotated: list[dict] = []

    for q in questions:
        if q.get("rag_category") != "refusal":
            continue

        if q.get("answerable") is None:
            q["answerable"] = False
            q["expected_action"] = "REFUSE"
            q["refusal_reason"] = "no_evidence"
            q["refusal_evidence_status"] = "hits_unsupported"
            q["refusal_annotation"] = {
                "status": "auto",
                "note": "检索命中但均不支持（supported_literature 为空），待人工复核",
            }
            auto_annotated.append(q)
        else:
            q["refusal_evidence_status"] = derive_evidence_status(q)
            q.setdefault("refusal_annotation", {"status": "manual"})

    for q in questions:
        if q.get("id") == "REF-007":
            q["refusal_annotation"] = {
                "status": "manual",
                "note": "有意设计：冲突证据题期望 WARN 而非 REFUSE",
            }

    QUESTIONS.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with REVIEW_OUT.open("w", encoding="utf-8") as f:
        for q in auto_annotated:
            rec = {
                "id": q.get("id"),
                "source": q.get("source"),
                "split": q.get("split"),
                "audit_status": q.get("audit_status"),
                "literature_used_count": len(q.get("literature_used") or []),
                "supported_literature": q.get("supported_literature"),
                "question": q.get("question"),
                "assigned": {
                    "answerable": False,
                    "expected_action": "REFUSE",
                    "refusal_reason": "no_evidence",
                    "refusal_evidence_status": "hits_unsupported",
                },
                "review_status": "pending",
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    refusal_total = sum(1 for q in questions if q.get("rag_category") == "refusal")
    print(f"updated {QUESTIONS}: refusal total={refusal_total}, auto_annotated={len(auto_annotated)}")
    print(f"review list: {REVIEW_OUT}")


if __name__ == "__main__":
    main()
