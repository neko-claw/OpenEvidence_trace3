"""LLM judge with anonymization, random position audit, and control samples.

Usage:
  python -m evaluation.judge --runs data/experiments/runs/runs_xxx.jsonl
  python -m evaluation.judge --runs ... --include-controls
"""
from __future__ import annotations

import argparse
import json
import random
import time

from core.config import load_config
from core.dataclasses import Question, Score, load_jsonl, save_jsonl
from core.llm import LLMClient
from generation import prompts


def anonymize(runs: list[dict]) -> tuple[list[dict], dict[tuple[str, str], str]]:
    """Map condition labels to deterministic anonymous labels per question."""
    per_question: dict[str, dict[str, str]] = {}
    anon_runs = []
    mapping: dict[tuple[str, str], str] = {}
    for run in runs:
        qid = run["question_id"]
        if qid not in per_question:
            conditions = sorted({r["condition"] for r in runs if r["question_id"] == qid})
            labels = [f"OPT{i + 1}" for i in range(len(conditions))]
            rng = random.Random(f"b5-anon::{qid}")
            rng.shuffle(labels)
            per_question[qid] = dict(zip(conditions, labels))
        label = per_question[qid][run["condition"]]
        mapping[(qid, run["condition"])] = label
        anon = dict(run)
        anon["condition_label"] = label
        anon_runs.append(anon)
    return anon_runs, mapping


def make_position_swap_controls(runs: list[dict]) -> list[dict]:
    """Create deterministic position-control samples for judge bias audit."""
    controls = []
    for idx, run in enumerate(runs):
        control = dict(run)
        control["run_id"] = f"{run['run_id']}::position_swap"
        control["control_type"] = "position_swap"
        control["control_id"] = f"{run['question_id']}::{run['run_id']}::position_swap"
        control["forced_position"] = 1 + (idx % 6)
        controls.append(control)
    return controls


def make_wrong_citation_controls(runs: list[dict]) -> list[dict]:
    """Create wrong-citation samples by injecting fabricated identifiers."""
    controls = []
    suffix = "\n\nAudit control: fabricated identifiers PMID:99999999, DOI 10.9999/fake.b5, NCT99999999."
    for run in runs:
        control = dict(run)
        control["run_id"] = f"{run['run_id']}::wrong_citations"
        control["control_type"] = "wrong_citations"
        control["control_id"] = f"{run['question_id']}::{run['run_id']}::wrong_citations"
        control["answer"] = f"{run.get('answer') or ''}{suffix}"
        control["citations"] = list(run.get("citations") or []) + [
            "PMID:99999999",
            "10.9999/fake.b5",
            "NCT99999999",
        ]
        controls.append(control)
    return controls


def build_control_samples(runs: list[dict], include_original: bool = True) -> list[dict]:
    """Return original runs plus deterministic P1 control samples."""
    out = list(runs) if include_original else []
    out.extend(make_position_swap_controls(runs))
    out.extend(make_wrong_citation_controls(runs))
    return out


def judge_run(llm: LLMClient, q: Question, run: dict, judge_id: str,
              model: str | None = None) -> Score:
    msgs = prompts.build_judge_prompt(q, run["answer"], q.rubric)
    obj, meta = llm.chat_json(msgs, temperature=0.0, model=model)
    verdicts = obj.get("verdicts", [])
    n_sup = sum(1 for v in verdicts if v.get("decision") == "supported")
    n_total = len(verdicts)
    return Score(
        run_id=run["run_id"],
        question_id=q.id,
        condition=run["condition"],
        judge_id=judge_id,
        metric_version="v0.1",
        rubric_version=(q.rubric or {}).get("rubric_version") or q.extras.get("rubric_version", "v0.1"),
        relevance=float(obj.get("relevance", 0) or 0),
        correctness=float(obj.get("correctness", 0) or 0),
        completeness=float(obj.get("completeness", 0) or 0),
        faithfulness=float(obj.get("faithfulness", 0) or 0),
        claim_support_rate=n_sup / n_total if n_total else 0.0,
        unsupported_claim_rate=(n_total - n_sup) / n_total if n_total else 1.0,
        latency_ms=meta["latency_ms"],
        input_tokens=meta["input_tokens"],
        output_tokens=meta["output_tokens"],
        estimated_cost=meta["estimated_cost"],
        control_type=str(run.get("control_type") or ""),
        control_id=str(run.get("control_id") or ""),
        notes=obj.get("notes", ""),
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Run anonymized B5 judge scoring")
    ap.add_argument("--runs", required=True, help="Run JSONL path")
    ap.add_argument("--questions", default="test_set/questions.jsonl")
    ap.add_argument("--judges", nargs="+", default=["judge1", "judge2"])
    ap.add_argument("--model", default=None, help="Override judge model")
    ap.add_argument("--sample", type=float, default=1.0, help="Deterministic run sample ratio")
    ap.add_argument("--include-controls", action="store_true",
                    help="Add deterministic position_swap and wrong_citations control samples")
    args = ap.parse_args()

    cfg = load_config()
    llm = LLMClient(cfg["llm"])
    model = args.model or cfg["llm"].get("judge_model") or "unknown-judge-family"
    questions = {q["id"]: Question.from_dict(q) for q in load_jsonl(args.questions)}
    raw_runs = load_jsonl(args.runs)
    if args.sample < 1.0:
        rng = random.Random(42)
        raw_runs = [run for run in raw_runs if rng.random() <= args.sample]
    if args.include_controls:
        raw_runs = build_control_samples(raw_runs, include_original=True)

    anon_runs, mapping = anonymize(raw_runs)
    mapping_path = cfg.path("artifacts") / "b5" / "judge_anonymize_mapping.json"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(
        json.dumps({f"{k[0]}::{k[1]}": v for k, v in sorted(mapping.items())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = cfg.path("scores_dir") / f"scores_{ts}.jsonl"
    for idx, run in enumerate(anon_runs):
        question = questions.get(run["question_id"])
        if question is None:
            continue
        for judge_idx, judge_id in enumerate(args.judges, start=1):
            seed = 1000 + idx * 7 + judge_idx
            rng = random.Random(seed)
            position = int(run.get("forced_position") or rng.randint(1, 6))
            score = judge_run(llm, question, run, judge_id, model=model)
            score.anonymous_label = run.get("condition_label", "")
            score.position = position
            score.randomization_seed = seed
            score.judge_family = model
            score.citation_count = len(run.get("citations") or [])
            score.displayed_citation_count = score.citation_count
            save_jsonl(str(out_path), [score.to_dict()])
            print(
                f"{score.condition} {run['question_id']} by {judge_id}: "
                f"faith={score.faithfulness} comp={score.completeness} "
                f"corr={score.correctness} rel={score.relevance}"
            )
    print(f"\njudge scoring complete -> {out_path} (anonymization map: {mapping_path})")


if __name__ == "__main__":
    main()
