"""B5 交付物回归测试（全部离线，不依赖 LLM/API）：

- 离线 fixture 满足 run.schema.json（冻结契约不回归）
- b5_report 主终点可算、配对比较/反例/一致性（kappa）行为正确
- STRESS 压力题加载（E-C 仅压力集）
- _doc_id 文档级去重对 chunk ID 统一生效
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import jsonschema

from core.dataclasses import Score, load_jsonl
from evaluation.b5_report import (
    _doc_id,
    _extract_identifiers_from_answer,
    _load_questions_with_stress,
    _cohen_kappa,
    _linear_weighted_kappa,
    paired_permutation_p,
    demo_records,
    run_b5_report,
    counterexample_rows,
)
from evaluation.judge import build_control_samples


ROOT = Path(__file__).resolve().parent.parent


# ---------- 契约：离线 fixture 满足冻结 schema（§3.1 Run 契约） ----------

def test_fixture_validates_against_run_schema():
    schema = json.loads((ROOT / "evaluation/schemas/run.schema.json").read_text(encoding="utf-8"))
    rows = load_jsonl(str(ROOT / "tests/fixtures/runs_offline_smoke.jsonl"))
    assert rows, "fixture 为空"
    for r in rows:
        jsonschema.validate(r, schema)
        # P0b 口径：B/C/D/E 有证据上下文时 claims 必须有 decision
        if r["condition"] in ("B", "C", "D", "E"):
            assert all(c.get("decision") for c in (r.get("claims") or [])), \
                f"{r['run_id']} claims 缺少 decision（主终点不可算）"
        # 冻结版本留痕
        assert r.get("code_commit"), f"{r['run_id']} 缺少 code_commit"


def test_run_roundtrip_keeps_code_commit():
    from core.dataclasses import Run
    r = Run(question_id="q01", condition="B", model="m", code_commit="abc123")
    r2 = Run.from_dict(r.to_dict())
    assert r2.code_commit == "abc123"


# ---------- 主终点与统计行为 ----------

def test_demo_report_main_endpoints_and_stress(tmp_path):
    runs, judge_scores, questions = demo_records()
    out_dir = tmp_path / "b5_demo"
    summary = run_b5_report(
        runs, judge_scores, questions, out_dir,
        runs_path="demo", scores_path="demo",
        metrics=["rubric_keypoint_score", "faithfulness", "unsupported_claim_rate",
                 "abstention_quality", "hit_at_5"],
        comparisons=[("A", "B"), ("B", "C"), ("C", "D"), ("C", "E")],
        expected_conditions=["A", "A2", "B", "C", "D", "E"],
    )
    # rubric_keypoint_score 均值单调 A < B < C < D
    means = {row["condition"]: row["mean"]
             for row in summary["condition_distribution"]
             if row["metric"] == "rubric_keypoint_score"}
    assert means["A"] < means["B"] < means["C"] < means["D"]
    # E-C 仅在 STRESS 题上比较
    ec = [row for row in summary["paired_deltas"] if row["comparison"] == "E-C"]
    assert ec and all(row["scope"] == "stress" for row in ec)
    # kappa 已计算（demo 双 judge 完全一致 -> 1.0）
    fa = summary["judge_audit"]["agreement"]["faithfulness"]["kappa"]
    assert fa["mean_kappa"] == 1.0
    # 反例机制已接入（demo 中 E 在压力题上劣于 C，故不产生反例行；合成用例见 test_e_c_tie_is_counterexample）
    assert (out_dir / "b5_counterexamples.csv").exists()


def test_doc_id_strips_chunk_for_all_prefixes():
    assert _doc_id("pmid:123:chunk:0") == "pmid:123"
    assert _doc_id("epmc:PMC1:chunk:002") == "epmc:PMC1"
    assert _doc_id("nct:NCT001:chunk:1") == "nct:NCT001"
    assert _doc_id("guideline:x:chunk:2") == "guideline:x"
    assert _doc_id("nct:NCT001") == "nct:NCT001"


def test_b4_evidence_id_records_are_supported(tmp_path):
    questions = [{"id": "q1", "question_type": "guideline", "gold_source_ids": ["pmid:12345"]}]
    runs = [
        {
            "run_id": "r1",
            "question_id": "q1",
            "condition": "C",
            "answer": "Answer cites PMID:12345.",
            "candidate_ids": [],
            "retrieved_evidence": [
                {"evidence_id": "pmid:12345:chunk:1", "source_type": "pubmed", "pmid": "12345", "text": "gold"},
                {"evidence_id": "guideline:g1", "source_type": "guideline", "text": "guide"},
            ],
            "claims": [{"criticality": "critical", "decision": "supported", "evidence_ids": ["pmid:12345"]}],
            "verification_decision": "PASS",
        }
    ]
    rows = run_b5_report(
        runs, [], questions, tmp_path / "b5",
        runs_path="runs", scores_path=None,
        metrics=["hit_at_5", "mrr", "recall_at_50", "rerank_ndcg_8", "source_diversity"],
        comparisons=[],
    )["condition_distribution"]
    means = {row["metric"]: row["mean"] for row in rows}
    assert means["hit_at_5"] == 1.0
    assert means["mrr"] == 1.0
    assert means["recall_at_50"] == 1.0
    assert means["rerank_ndcg_8"] == 1.0
    assert means["source_diversity"] == 2.0


def test_fake_identifier_and_retrieval_diagnostics(tmp_path):
    questions = [{"id": "q1", "split": "stress", "question_type": "guideline", "gold_source_ids": ["pmid:12345"]}]
    runs = [
        {
            "run_id": "r1",
            "question_id": "q1",
            "condition": "C",
            "answer": "Supported by PMID:12345 but not PMID:99999999 or DOI 10.9999/fake.b5. Trial NCT99999999.",
            "candidate_ids": ["pmid:12345"],
            "retrieved_evidence": [
                {"id": "pmid:12345:chunk:1", "source_type": "pubmed", "pmid": "12345", "text": "alpha beta"},
                {"id": "pmid:12345:chunk:2", "source_type": "pubmed", "pmid": "12345", "text": "duplicate"},
                {"id": "guideline:g1", "source_type": "guideline", "text": "guideline text"},
            ],
            "claims": [{"criticality": "critical", "decision": "unsupported", "conflict_ids": ["pmid:12345"]}],
            "verification_decision": "PASS",
        }
    ]
    summary = run_b5_report(
        runs, [], questions, tmp_path / "b5",
        runs_path="runs", scores_path=None,
        metrics=["fake_identifier_count", "source_diversity", "context_tokens", "duplicate_rate", "conflict_rate", "unsupported_critical_claim_rate"],
        comparisons=[],
    )
    scores = load_jsonl(str(tmp_path / "b5" / "b5_auto_scores.jsonl"))
    score = scores[0]
    assert _extract_identifiers_from_answer(runs[0]["answer"]) >= {"pmid:12345", "pmid:99999999", "doi:10.9999/fake.b5", "nct:NCT99999999"}
    assert score["fake_identifier_count"] == 3
    assert score["source_diversity"] == 2
    assert score["duplicate_rate"] == 1 / 3
    assert score["conflict_rate"] == 1 / 2
    assert (tmp_path / "b5" / "b5_retrieval_diagnostics.csv").exists()
    assert summary["retrieval_diagnostics"]


def test_judge_control_sample_generators():
    runs = [{"run_id": "r1", "question_id": "q1", "condition": "C", "answer": "answer", "citations": []}]
    controls = build_control_samples(runs)
    by_type = {run.get("control_type"): run for run in controls if run.get("control_type")}
    assert set(by_type) == {"style", "position_swap", "wrong_citations"}
    assert by_type["style"]["answer"] != runs[0]["answer"]
    assert by_type["position_swap"]["forced_position"] == 1
    assert "PMID:99999999" in by_type["wrong_citations"]["answer"]


def test_stats_module_delegates_to_b5_report_semantics():
    from evaluation import stats

    scores = [
        {"run_id": "r1", "question_id": "q1", "condition": "A", "judge_id": "j1", "faithfulness": 2.0},
        {"run_id": "r2", "question_id": "q1", "condition": "B", "judge_id": "j1", "faithfulness": 4.0},
        {"run_id": "r1", "question_id": "q1", "condition": "A", "judge_id": "j2", "faithfulness": 2.0},
        {"run_id": "r2", "question_id": "q1", "condition": "B", "judge_id": "j2", "faithfulness": 4.0},
    ]
    assert stats.mean_by_condition(scores, "faithfulness") == {"A": 2.0, "B": 4.0}
    assert stats.paired_deltas(scores, "faithfulness", "A", "B") == [2.0]
    lo, hi = stats.bootstrap_ci([2.0, 2.0])
    assert lo == 2.0 and hi == 2.0


def test_permutation_keeps_ties():
    # 全平局 -> p=1.0（此前剔除 0 会误判）
    assert paired_permutation_p([0.0, 0.0, 0.0]) == 1.0
    # 有平局稀释显著性：[0.7, 0.0] 的 p 应 >= 无平局的 [0.7, 0.7]
    with_ties = paired_permutation_p([0.7, 0.0])
    without_ties = paired_permutation_p([0.7, 0.7])
    assert with_ties is not None and without_ties is not None
    assert with_ties >= without_ties


def test_e_c_tie_is_counterexample():
    rows = [
        {"question_id": "s1", "metric": "rubric_keypoint_score", "comparison": "E-C",
         "delta": 0.0, "right_condition_better": False},
        {"question_id": "s2", "metric": "rubric_keypoint_score", "comparison": "E-C",
         "delta": -0.5, "right_condition_better": False},
        {"question_id": "q1", "metric": "rubric_keypoint_score", "comparison": "B-A",
         "delta": 0.1, "right_condition_better": True},
    ]
    out = counterexample_rows(rows)
    types = {r["question_id"]: r["counterexample_type"] for r in out}
    assert types.get("s1") == "degraded_condition_not_worse"  # 平局也披露
    assert "s2" not in types  # E 劣于 C 不是反例
    assert "q1" not in types  # B 优于 A 不是反例


def test_kappa_helpers():
    a = [1, 2, 3, 4, 5]
    b = [1, 2, 3, 4, 5]
    assert _linear_weighted_kappa(a, b) == 1.0
    assert _linear_weighted_kappa(a, [5, 4, 3, 2, 1]) is not None
    assert _cohen_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0
    assert _cohen_kappa([1, 1, 1, 1], [0, 0, 0, 0]) == 0.0   # 完全不一致
    assert _cohen_kappa([1, 1, 1, 1], [1, 1, 1, 1]) is None   # 无类别变化无法估计


# ---------- STRESS 加载（E-C 仅压力集可运行） ----------

def test_stress_questions_loaded_with_split(tmp_path):
    formal = tmp_path / "formal.jsonl"
    stress = tmp_path / "stress.jsonl"
    formal.write_text(json.dumps({"id": "t1", "question_type": "guideline"}) + "\n",
                      encoding="utf-8")
    stress.write_text(json.dumps({"id": "s1", "question_type": "insufficient"}) + "\n",
                      encoding="utf-8")
    class FakeCfg:
        def path(self, key):
            return stress
    qs = _load_questions_with_stress(str(formal), str(stress), FakeCfg())
    splits = {q["id"]: q.get("split") for q in qs}
    assert splits == {"t1": None, "s1": "stress"}


# ---------- Score 契约：judge 审计字段 + 版本字段（§6.3） ----------

def test_score_schema_validates_judge_row():
    schema = json.loads((ROOT / "evaluation/schemas/score.schema.json").read_text(encoding="utf-8"))
    s = Score(run_id="r1", question_id="q1", condition="B", judge_id="judge1",
              metric_version="v0.1", rubric_version="v0.1",
              relevance=4.0, correctness=4.0, completeness=3.5, faithfulness=4.0,
              citation_precision=1.0, citation_coverage=1.0,
              claim_support_rate=0.8, unsupported_claim_rate=0.2,
              abstention_quality=1.0,
              anonymous_label="OPT①", position=2, randomization_seed=1007,
              judge_family="judge-family-b", citation_count=3,
              displayed_citation_count=3)
    jsonschema.validate(s.to_dict(), schema)


def test_score_schema_has_main_endpoint_and_audit_fields():
    schema = json.loads((ROOT / "evaluation/schemas/score.schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    for field in ("unsupported_critical_claim_rate", "hit_at_5", "recall_at_50",
                  "rerank_ndcg_8", "position", "anonymous_label",
                  "randomization_seed", "judge_family", "citation_count",
                  "control_type", "control_id"):
        assert field in props, f"score.schema 缺少 {field}"
