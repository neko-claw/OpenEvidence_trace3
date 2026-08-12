"""为 test_set/questions_110.json 补全蓝图必填字段，并把 data/questions 样例标记为演示数据。

确定性字段：
- language：按题面 CJK 内容判定 zh/en；
- dataset_pack：split=dev -> DEV，split=test -> TEST；
- as_of_date：统一取语料 cutoff（corpus_cutoff）；
- rubric_version：与 scoring_guide 一致取 0.1-draft；
- source_provenance：公开基准 -> public_benchmark，ORIGINAL_REFUSAL -> human_teacher；
- source_group_id：暂以原始题 ID 作为同源组（翻译/改写待合并）。

推断字段（生成复核清单）：
- topic：优先取 topic_tags，否则关键词分类；无法判断为 unknown；
- question_type：refusal -> insufficient_conflict_out_of_scope；其余按关键词分类；
  无法判断为 unknown。

data/questions 三个样例文件：只加 demo 标记，不补正式字段。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
QUESTIONS_110 = BASE_DIR / "test_set" / "questions_110.json"
REVIEW_OUT = BASE_DIR / "test_set" / "field_annotation_review.jsonl"
DEMO_FILES = {
    "dev8.jsonl": "dev",
    "formal12.jsonl": "test",
    "stress_sample.jsonl": "stress",
}

AS_OF_DATE = "2026-08-11"
RUBRIC_VERSION = "0.1-draft"

TOPIC_KEYWORDS = {
    "hypertension": [
        "blood pressure", "hypertension", "hypertensive", "systolic", "diastolic",
        "antihypertensive", "bp ", "血压", "高血压", "降压", "限钠", "盐",
        "pre-eclampsia", "preeclampsia", "aldosterone", "thiazide", "diuretic",
    ],
    "dyslipidemia": [
        "cholesterol", "lipid", "ldl", "hdl", "triglyceride", "statin",
        "lipoprotein", "hyperlipidemia", "dyslipidemia", "apolipoprotein",
        "vldl", "血脂", "胆固醇", "他汀", "脂蛋白", "降脂",
    ],
}

QUESTION_TYPE_KEYWORDS = {
    "latest_research_trial": [
        "trial", "randomized", "randomised", "rct", "meta-analysis", "meta analysis",
        "systematic review", "study", "studies", "recent", "newest", "latest",
        "evidence", "outcome", "phase", "试验", "随机", "研究", "最新", "meta",
        "系统综述", "结局",
    ],
    "guideline_treatment": [
        "guideline", "recommend", "recommended", "indication", "indicated",
        "treat", "treatment", "therapy", "dose", "dosing", "manage", "management",
        "first-line", "指南", "推荐", "治疗", "用药", "剂量", "一线",
    ],
    "stable_knowledge_mechanism": [
        "mechanism", "physiolog", "pathophysiolog", "definition", "diagnos",
        "which of the following", "what is", "what are", "function", "causes",
        "cause", "role", "difference between", "define", "机制", "定义", "诊断",
        "是什么", "作用", "原因", "区别",
    ],
}


def cjk_count(text: str) -> int:
    return sum("\u4e00" <= ch <= "\u9fff" for ch in text)


def classify_topic(question: str, tags: list[str]) -> tuple[str, str]:
    lowered = [t.lower() for t in tags]
    if "hypertension" in lowered:
        return "hypertension", "from_tags"
    if "lipid" in lowered or "dyslipidemia" in lowered:
        return "dyslipidemia", "from_tags"
    text = question.lower()
    hits = {
        topic: sum(1 for kw in kws if kw in text)
        for topic, kws in TOPIC_KEYWORDS.items()
    }
    if hits["hypertension"] == hits["dyslipidemia"]:
        return "unknown", "unknown"
    topic = max(hits, key=hits.get)
    return topic, "auto" if hits[topic] else "unknown"


def classify_question_type(question: str, rag_category: str) -> str:
    """按题面文本分型；不再把 refusal 直接映射为 insufficient_conflict_out_of_scope。

    修复背景（见 docs/b2_dataset_review.md）：旧逻辑把检索审计失败（rag_category
    == refusal）强制映射为'证据不足/冲突/范围外'，导致 TEST 集 41 题被计入拒答分层，
    且与'检索失败'形成循环论证。现在只有经医学裁定 answerable=false 的题才属于
    insufficient_conflict_out_of_scope；待裁定的题返回 unknown 并进入人工复核清单。
    """
    if rag_category == "refusal" and question:
        # refusal 题若已被独立裁定为不可回答，才归入该题型；否则留待人工判定
        return "unknown"
    text = question.lower()
    hits = {
        qtype: sum(1 for kw in kws if kw in text)
        for qtype, kws in QUESTION_TYPE_KEYWORDS.items()
    }
    best = max(hits, key=hits.get)
    if hits[best] == 0:
        return "unknown"
    sorted_hits = sorted(hits.values(), reverse=True)
    if len(sorted_hits) >= 2 and sorted_hits[0] == sorted_hits[1]:
        return "unknown"
    return best


def main() -> None:
    doc = json.loads(QUESTIONS_110.read_text(encoding="utf-8"))
    questions = doc["questions"]
    review: list[dict] = []

    for q in questions:
        split = q.get("split")
        q["language"] = "zh" if cjk_count(q.get("question", "")) >= 1 else "en"
        q["dataset_pack"] = "DEV" if split == "dev" else "TEST"
        q["as_of_date"] = AS_OF_DATE
        q["rubric_version"] = RUBRIC_VERSION
        q["source_provenance"] = (
            "human_teacher"
            if q.get("source") == "ORIGINAL_REFUSAL"
            else "public_benchmark"
        )
        q["source_group_id"] = q.get("id")

        topic, topic_status = classify_topic(
            q.get("question", ""), q.get("topic_tags") or []
        )
        qtype = classify_question_type(q.get("question", ""), q.get("rag_category"))
        # 已人工裁定不可回答（answerable=false）的题才归入 evidence-insufficient 类
        answerable = q.get("answerable")
        if q.get("rag_category") == "refusal" and answerable is False:
            qtype = "insufficient_conflict_out_of_scope"
        q["topic"] = topic
        q["question_type"] = qtype

        annotation = {
            "topic_status": topic_status,
            "question_type_status": (
                "derived_refusal" if (q.get("rag_category") == "refusal" and answerable is False) else (
                    "auto" if qtype != "unknown" else "unknown"
                )
            ),
        }
        q["field_annotation"] = annotation

        if topic_status != "from_tags" or annotation["question_type_status"] in ("auto", "unknown"):
            review.append({
                "id": q.get("id"),
                "source": q.get("source"),
                "split": q.get("split"),
                "rag_category": q.get("rag_category"),
                "topic": topic,
                "topic_status": topic_status,
                "question_type": qtype,
                "question_type_status": annotation["question_type_status"],
                "question": q.get("question"),
            })

    QUESTIONS_110.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with REVIEW_OUT.open("w", encoding="utf-8") as f:
        for rec in review:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # data/questions 样例标记为演示数据
    for filename, split in DEMO_FILES.items():
        path = BASE_DIR / "data" / "questions" / filename
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for row in rows:
            row["demo"] = True
            row["dataset_pack"] = "DEMO"
            row["split"] = split
            row["demo_note"] = "链路/离线样例，不进正式评测指标"
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )

    from collections import Counter
    print("topic:", dict(Counter(q.get("topic") for q in questions)))
    print("question_type:", dict(Counter(q.get("question_type") for q in questions)))
    print("review lines:", len(review))


if __name__ == "__main__":
    main()
