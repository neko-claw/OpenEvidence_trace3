import json
from pathlib import Path

import jsonschema

from evaluation.adapters.fixture_retriever import FixtureRetriever
from evaluation.runner import run_condition


ROOT = Path(__file__).resolve().parents[1]


def _validate(run):
    schema = json.loads((ROOT / "evaluation/schemas/run.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(run.to_dict(), schema)


def test_run_record_json_matches_schema_for_a_c_and_not_applicable_e():
    retriever = FixtureRetriever(ROOT / "data/fixtures/evidence.jsonl", ROOT / "data/fixtures/qrels.jsonl")
    questions = [
        json.loads(line)
        for line in (ROOT / "data/fixtures/questions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    dev = next(q for q in questions if q["id"] == "dev-001")
    stress = next(q for q in questions if q["id"] == "stress-001")
    for question, condition in ((dev, "A"), (dev, "C"), (dev, "E"), (stress, "E")):
        run, _ = run_condition(question, condition, retriever, config={"seed": 7, "replicate": 2})
        _validate(run)


def test_seed_and_replicate_make_run_ids_distinct():
    retriever = FixtureRetriever(ROOT / "data/fixtures/evidence.jsonl", ROOT / "data/fixtures/qrels.jsonl")
    question = json.loads((ROOT / "data/fixtures/questions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    first, _ = run_condition(question, "C", retriever, config={"seed": 1, "replicate": 1})
    second, _ = run_condition(question, "C", retriever, config={"seed": 2, "replicate": 1})
    third, _ = run_condition(question, "C", retriever, config={"seed": 1, "replicate": 2})
    assert len({first.run_id, second.run_id, third.run_id}) == 3


def test_run_schema_accepts_a5_style_evidence_and_object_citations():
    retriever = FixtureRetriever(ROOT / "data/fixtures/evidence.jsonl", ROOT / "data/fixtures/qrels.jsonl")
    question = json.loads((ROOT / "data/fixtures/questions.jsonl").read_text(encoding="utf-8").splitlines()[0])

    class A5ShapeAdapter:
        def run(self, question, config):
            from evaluation.adapters.full_system import FullSystemResult

            return FullSystemResult(
                question_id=question["id"],
                system_version="a5-workflow-v0.1",
                retrieved_evidence=[{"id": "pmid:123", "content": "evidence"}],
                answer="refused safely",
                claims=[],
                citations=[{"evidence_id": "pmid:123", "valid": True}],
                verification_decision="REFUSE",
            )

    run, _ = run_condition(question, "D", retriever, config={"full_system_adapter": A5ShapeAdapter()})
    _validate(run)
