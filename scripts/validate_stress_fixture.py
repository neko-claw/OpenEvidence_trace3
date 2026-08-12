"""Validate the frozen B2 STRESS question-set contract used by B4."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


FORMAL_RULES = (
    "drop_all_gold_v1",
    "topk_reduced",
    "inject_unsupporting_v1",
    "unanswerable_malicious",
)
EXPECTED_COUNT_PER_RULE = 5


def load_questions(path: Path) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    errors: list[str] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: invalid JSON ({exc.msg})")
                continue
            if not isinstance(value, dict):
                errors.append(f"line {line_number}: question must be an object")
                continue
            questions.append(value)
    if errors:
        raise ValueError("; ".join(errors))
    return questions


def declared_stress_rule(question: dict[str, Any]) -> str | None:
    rubric = question.get("rubric")
    if isinstance(rubric, dict) and rubric.get("stress_rule"):
        return str(rubric["stress_rule"]).strip().lower()
    if question.get("stress_rule"):
        return str(question["stress_rule"]).strip().lower()
    return None


def validate_questions(questions: list[dict[str, Any]], *, formal: bool = True) -> dict[str, Any]:
    stress_questions = [q for q in questions if q.get("split") == "STRESS"]
    ids = [str(q.get("id", "")) for q in stress_questions]
    rules = [declared_stress_rule(q) for q in stress_questions]
    missing_rule = [qid for qid, rule in zip(ids, rules) if not rule]
    unsupported_rule = sorted({rule for rule in rules if rule and rule not in FORMAL_RULES})
    counts = Counter(rule for rule in rules if rule)
    duplicate_ids = sorted(qid for qid, count in Counter(ids).items() if qid and count > 1)

    errors: list[str] = []
    if not stress_questions:
        errors.append("no questions with split=STRESS")
    if duplicate_ids:
        errors.append(f"duplicate STRESS question ids: {duplicate_ids}")
    if formal and missing_rule:
        errors.append(f"missing rubric.stress_rule/stress_rule: {missing_rule}")
    if unsupported_rule:
        errors.append(f"unsupported formal stress rules: {unsupported_rule}")
    if formal:
        if len(stress_questions) != 20:
            errors.append(f"formal STRESS count must be 20, got {len(stress_questions)}")
        for rule in FORMAL_RULES:
            if counts[rule] != EXPECTED_COUNT_PER_RULE:
                errors.append(
                    f"formal rule {rule} must have {EXPECTED_COUNT_PER_RULE} questions, "
                    f"got {counts[rule]}"
                )

    return {
        "valid": not errors,
        "formal": formal,
        "question_count": len(questions),
        "stress_count": len(stress_questions),
        "rule_counts": {rule: counts[rule] for rule in FORMAL_RULES},
        "missing_rule_ids": missing_rule,
        "unsupported_rules": unsupported_rule,
        "duplicate_ids": duplicate_ids,
        "errors": errors,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the B2 STRESS fixture contract")
    parser.add_argument("--questions", default="data/fixtures/questions.jsonl")
    parser.add_argument(
        "--fixture-smoke",
        action="store_true",
        help="allow a non-formal sample while still checking JSON and unique STRESS ids",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        questions = load_questions(Path(args.questions))
        report = validate_questions(questions, formal=not args.fixture_smoke)
    except (OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
