import json
from pathlib import Path

from scripts.validate_stress_fixture import validate_questions


ROOT = Path(__file__).resolve().parents[1]


def test_current_fixture_is_rejected_as_non_formal_stress_set():
    questions = [
        json.loads(line)
        for line in (ROOT / "data/fixtures/questions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = validate_questions(questions)
    assert not report["valid"]
    assert report["stress_count"] == 5
    assert report["missing_rule_ids"] == [
        "stress-001",
        "stress-002",
        "stress-003",
        "stress-004",
        "stress-005",
    ]


def test_formal_stress_contract_accepts_four_groups_of_five():
    rules = (
        "drop_all_gold_v1",
        "topk_reduced",
        "inject_unsupporting_v1",
        "unanswerable_malicious",
    )
    questions = [
        {
            "id": f"s-{index}",
            "split": "STRESS",
            "rubric": {"stress_rule": rule},
        }
        for index, rule in enumerate(rule for rule in rules for _ in range(5))
    ]
    report = validate_questions(questions)
    assert report["valid"]
    assert report["stress_count"] == 20
    assert all(value == 5 for value in report["rule_counts"].values())


def test_fixture_smoke_mode_allows_the_small_pipeline_sample():
    questions = [
        json.loads(line)
        for line in (ROOT / "data/fixtures/questions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = validate_questions(questions, formal=False)
    assert report["valid"]
