"""生成 test_set 题集级 DatasetManifest（逐 split 哈希 + 统计 + 字段审计）。

用法:
    python scripts/build_question_manifest.py

输出:
    test_set/dataset_manifest.json
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
TEST_SET = BASE_DIR / "test_set"
QUESTIONS = TEST_SET / "questions_110.json"
BLUEPRINT = BASE_DIR / "evaluation" / "blueprints" / "question_blueprint.json"
CORPUS_MANIFEST = BASE_DIR / "data" / "processed" / "manifest.json"
OUT = TEST_SET / "dataset_manifest.json"

TRACKED_FILES = {
    "questions_110.json": "合并题集（推荐入口）：110 道题 + 划分 + 文献标注",
    "questions_test.json": "100 道公开基准题（构建中间产物）",
    "questions_test.jsonl": "questions_test.json 的 JSONL 形式",
    "refusal_split.json": "10 道原始拒答题（REF-001 ~ REF-010）",
    "question_rag_split.jsonl": "110 题 dev/test 划分（3:7）",
    "question_rag_split_summary.json": "划分汇总",
    "question_literature_annotation.jsonl": "110 题 RAG 文献标注",
    "question_literature_summary.json": "文献标注汇总",
    "oracle_support_annotation.jsonl": "hard 题 oracle 检索支撑判定",
    "field_annotation_review.jsonl": "topic/question_type 自动标注复核清单",
    "scoring_guide.json": "评分指南（draft，待人工冻结）",
    "scoring_guide.md": "评分指南可读版（draft）",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cjk_count(text: str) -> int:
    return sum("\u4e00" <= ch <= "\u9fff" for ch in text)


def load_questions() -> list[dict]:
    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    questions = data.get("questions", data)
    if isinstance(questions, dict):
        questions = list(questions.values())
    return questions


def main() -> None:
    questions = load_questions()
    blueprint = json.loads(BLUEPRINT.read_text(encoding="utf-8"))
    required_fields = blueprint["question_required_fields"]

    split_counts = Counter(q.get("split") for q in questions)
    source_counts = Counter(q.get("source") for q in questions)
    rag_counts = Counter(q.get("rag_category") for q in questions)
    diff_counts = Counter(q.get("difficulty_level") for q in questions)

    topic_non_empty = sum(bool(q.get("topic_tags")) for q in questions)
    topic_counts: Counter[str] = Counter()
    for q in questions:
        for tag in q.get("topic_tags") or []:
            topic_counts[tag] += 1

    language_counts: Counter[str] = Counter()
    for q in questions:
        language_counts["zh" if cjk_count(q.get("question", "")) >= 1 else "en"] += 1

    ref_items = [q for q in questions if str(q.get("id", "")).startswith("REF-")]
    refusal_items = [q for q in questions if q.get("rag_category") == "refusal"]
    refusal_answerable = Counter(
        "missing" if q.get("answerable") is None else str(q.get("answerable"))
        for q in refusal_items
    )
    refusal_reason_counts = Counter(
        str(q.get("refusal_reason") or "missing") for q in refusal_items
    )
    refusal_evidence_status_counts = Counter(
        str(q.get("refusal_evidence_status") or "missing") for q in refusal_items
    )
    missing_refusal_fields = sum(1 for q in refusal_items if q.get("answerable") is None)

    present_all: list[str] = []
    missing_all: list[str] = []
    partial: dict[str, dict] = {}
    for field in required_fields:
        n = sum(field in q and q[field] is not None for q in questions)
        if n == len(questions):
            present_all.append(field)
        elif n == 0:
            missing_all.append(field)
        else:
            partial[field] = {"present": n, "total": len(questions)}

    corpus_cutoff = None
    if CORPUS_MANIFEST.exists():
        try:
            corpus_meta = json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))
            corpus_cutoff = corpus_meta.get("corpus_cutoff")
        except json.JSONDecodeError:
            corpus_cutoff = None

    split_hashes = {
        name: sha256(TEST_SET / name) for name in TRACKED_FILES
    }

    manifest = {
        "dataset_version": "v0.1.0",
        "questionset_id": "OpenEvidence-track3-test-set-110-v0.1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_cutoff": corpus_cutoff,
        "schema_version": f"question_blueprint.json {blueprint['blueprint_version']}（14 个必填字段）",
        "blueprint_ref": "evaluation/blueprints/question_blueprint.json",
        "source": {
            "canonical_file": "test_set/questions_110.json",
            "generation_scripts": [
                "scripts/build_dev_test_split.py",
                "scripts/annotate_question_literature.py",
                "scripts/annotate_question_fields.py",
                "scripts/build_questions_110.py",
                "scripts/build_scoring_guide.py",
            ],
        },
        "split_counts": {
            "dev": split_counts.get("dev", 0),
            "test": split_counts.get("test", 0),
            "total": len(questions),
        },
        "record_counts": {
            "questions": len(questions),
            "by_rag_category": dict(rag_counts),
            "by_difficulty_level": dict(diff_counts),
            "by_source": dict(source_counts),
            "by_topic": dict(Counter(str(q.get("topic") or "missing") for q in questions)),
            "by_question_type": dict(
                Counter(str(q.get("question_type") or "missing") for q in questions)
            ),
            "by_language_field": dict(
                Counter(str(q.get("language") or "missing") for q in questions)
            ),
            "by_language_content_audit": dict(language_counts),
            "by_dataset_pack": dict(
                Counter(str(q.get("dataset_pack") or "missing") for q in questions)
            ),
            "by_source_provenance": dict(
                Counter(str(q.get("source_provenance") or "missing") for q in questions)
            ),
            "topic_tags_non_empty": topic_non_empty,
            "by_topic_tag": dict(topic_counts),
            "as_of_date_non_empty": sum(1 for q in questions if q.get("as_of_date")),
            "rubric_version_non_empty": sum(1 for q in questions if q.get("rubric_version")),
            "source_group_id_non_empty": sum(1 for q in questions if q.get("source_group_id")),
            "gold_source_ids_non_empty": sum(
                1 for q in questions if q.get("gold_source_ids")
            ),
            "gold_literature_non_empty": sum(
                1 for q in questions if q.get("gold_literature")
            ),
        },
        "source_group_policy": "同源改写共享 source_group_id（当前暂以原始题 ID 为同源组，翻译/改写待合并）",
        "dedup_method": "id 唯一 + 文本/embedding 聚类检查近义重复（source_group_id 暂为原始题 ID，改写合并待补）",
        "dedup_threshold": None,
        "licenses": "公开基准题（MIRAGE/MedQA-USMLE/MedExpQA）许可证需在正式冻结前逐源核验并回填",
        "storage_layout": {
            name: desc for name, desc in TRACKED_FILES.items()
        },
        "split_hashes": split_hashes,
        "field_audit": {
            "required_field_count": len(required_fields),
            "present_in_all": present_all,
            "missing_in_all": missing_all,
            "partial": partial,
        },
        "refusal_audit": {
            "refusal_total": len(refusal_items),
            "ref_items": len(ref_items),
            "answerable_status": dict(refusal_answerable),
            "refusal_reason": dict(refusal_reason_counts),
            "refusal_evidence_status": dict(refusal_evidence_status_counts),
            "note": (
                f"{missing_refusal_fields} 道 refusal 缺少 "
                "answerable/expected_action/refusal_reason，待补齐后重新生成本 manifest"
                if missing_refusal_fields
                else "59/59 refusal 已标注；自动标注部分（hits_unsupported）待人工复核"
            ),
        },
        "pipeline": "python scripts/build_question_manifest.py",
        "generator": "scripts.build_question_manifest",
    }

    OUT.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"written: {OUT}")
    print(f"questions={len(questions)} dev={split_counts.get('dev')} test={split_counts.get('test')}")


if __name__ == "__main__":
    main()
