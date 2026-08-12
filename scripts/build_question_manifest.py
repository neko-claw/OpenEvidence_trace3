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
    "questions_110.json": "合并题集（110 题，含可回答性裁定/同源去重标记）",
    "questions_test.json": "100 道公开基准题（由 scripts/split_dataset.py 冻结）",
    "refusal_split.json": "10 道原始拒答题（REF-001 ~ REF-010）",
    "question_rag_split.jsonl": "110 题 dev/test 划分（3:7）",
    "question_literature_annotation.jsonl": "110 题 RAG 文献标注",
    "field_annotation_review.jsonl": "topic/question_type 自动标注复核清单",
    "refusal_auto_annotation_review.jsonl": "拒答自动标注复核清单",
    "answerability_review.jsonl": "可回答性待裁定清单（已由 adjudication_manifest 替代，保留审计）",
    "qrels.jsonl": "题-证据相关标注（Qrel 契约，题级）",
    "adjudication_manifest.json": "人工裁定记录（44 题恢复 hard + 范围外 + 同源去重）",
    "latest_research.json": "latest_research_trial 分层补充 20 题（15 TEST + 5 DEV，语料库真实文献抽象）",
    "supplement_insufficient.json": "insufficient 分层补充 5 题（范围外/证据不足）",
    "stress_20.json": "STRESS 压力集 20 题（预注册四类扰动，C/E 对照）",
    "external_10.json": "EXTERNAL 外部基准 10 题（ClinicalTrials/Europe PMC）",
    "reserve_10.json": "RESERVE 备用 10 题（6 同源重复 + 4 构造）",
    "scoring_guide.json": "评分指南（0.2-adjudicated，拒答矛盾已清除）",
    "scoring_guide.md": "评分指南可读版",
    "supplemental_evidence.jsonl": "冻结补料/人工精选证据（85 条）",
    "validation_report.json": "规划合规校验报告（v2 PASS）",
    "validation_report.md": "规划合规校验报告可读版",
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
        name: sha256(TEST_SET / name)
        for name in TRACKED_FILES if (TEST_SET / name).exists()
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
                "scripts/split_dataset.py",
                "scripts/annotate_question_literature.py",
                "scripts/annotate_question_fields.py",
                "scripts/adjudicate_dataset.py",
                "scripts/gold_candidates.py",
                "scripts/build_questions_110.py",
                "scripts/build_qrels.py",
                "scripts/build_latest_questions.py",
                "scripts/build_insufficient_supplement.py",
                "scripts/build_stress_set.py",
                "scripts/build_external_reserve.py",
                "scripts/fix_scoring_guide.py",
                "scripts/build_scoring_guide.py",
                "scripts/validate_dataset.py",
                "scripts/build_question_manifest.py",
            ],
        },
        "split_counts": {
            "dev": split_counts.get("dev", 0),
            "test": split_counts.get("test", 0),
            "total": len(questions),
            "packs": {
                "DEV_effective": 38,
                "TEST_effective": 91,
                "STRESS": 20,
                "EXTERNAL": 10,
                "RESERVE": 10,
                "note": "TEST 有效=110 test 去重 71 + latest 15 + insufficient 补充 5；DEV 有效=33 + latest 5",
            },
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
            "by_answerability": dict(
                Counter(str(q.get("answerability") or "missing") for q in questions)
            ),
            "by_adjudication_status": dict(
                Counter(str(q.get("adjudication_status") or "missing") for q in questions)
            ),
            "gold_human_verified": sum(1 for q in questions if q.get("gold_verified")),
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
