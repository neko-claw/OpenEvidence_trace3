"""Compatibility wrapper around the canonical B5 report statistics.

`evaluation.b5_report` is the single source for B5 statistical outputs. This
module keeps older imports and the `python -m evaluation.stats` command working
while delegating metric aliases, paired deltas, bootstrap CIs, and agreement
logic to the B5 implementation.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from core.config import load_config
from core.dataclasses import load_jsonl
from evaluation.b5_report import (
    DEFAULT_METRICS,
    _bootstrap_ci_stratified,
    _cohen_kappa,
    _linear_weighted_kappa,
    _metric_value,
    aggregate_run_scores,
    condition_distribution_rows,
    group_means,
    merge_auto_and_judge_scores,
    paired_delta_rows,
    parse_comparisons,
    run_b5_report,
)


def _score_rows(scores: list[dict[str, Any]], metrics: list[str] | None = None) -> list[dict[str, Any]]:
    return aggregate_run_scores(scores, metrics or DEFAULT_METRICS)


def paired_deltas(scores: list[dict[str, Any]], metric: str, c1: str, c2: str) -> list[float]:
    """Return paired deltas using b5_report's question-level aggregation."""
    rows = _score_rows(scores, [metric])
    by_q: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        value = _metric_value(row, metric)
        if value is not None and row.get("question_id") and row.get("condition"):
            by_q[str(row["question_id"])][str(row["condition"])].append(value)
    deltas = []
    for conds in by_q.values():
        if c1 in conds and c2 in conds:
            deltas.append(statistics.fmean(conds[c2]) - statistics.fmean(conds[c1]))
    return deltas


def bootstrap_ci(
    deltas: list[float],
    n_boot: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Compatibility CI using b5_report's stratified bootstrap helper."""
    if not deltas:
        return (0.0, 0.0)
    if alpha != 0.05:
        raise ValueError("evaluation.stats delegates to b5_report, which reports 95% CIs")
    q_deltas = {str(i): float(delta) for i, delta in enumerate(deltas)}
    qtypes = {qid: "all" for qid in q_deltas}
    lo, hi = _bootstrap_ci_stratified(q_deltas, qtypes, samples=n_boot, seed=seed)
    return (float(lo), float(hi))


def mean_by_condition(scores: list[dict[str, Any]], metric: str) -> dict[str, float]:
    rows = condition_distribution_rows(_score_rows(scores, [metric]), [metric])
    return {str(row["condition"]): float(row["mean"]) for row in rows}


def group_by_type(
    scores: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    metric: str,
) -> dict[str, dict[str, float]]:
    rows = group_means(_score_rows(scores, [metric]), questions, [metric])
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        if row["group"] == "question_type":
            out[str(row["value"])][str(row["condition"])] = float(row["mean"])
    return dict(out)


def judge_agreement(scores: list[dict[str, Any]], metric: str) -> float:
    """Return mean kappa where estimable, matching b5_report's agreement semantics."""
    by_run: dict[str, list[float]] = defaultdict(list)
    for row in scores:
        if row.get("judge_id") and row.get("judge_id") != "auto":
            value = _metric_value(row, metric)
            if value is not None and row.get("run_id"):
                by_run[str(row["run_id"])].append(value)
    pairs = [values[:2] for values in by_run.values() if len(values) >= 2]
    if not pairs:
        return math.nan
    a = [pair[0] for pair in pairs]
    b = [pair[1] for pair in pairs]
    binary = all(value in (0.0, 1.0) for value in a + b)
    kappa = _cohen_kappa(a, b) if binary else _linear_weighted_kappa(a, b)
    return float(kappa) if kappa is not None else math.nan


def report(scores: list[dict[str, Any]], questions: list[dict[str, Any]] | None = None) -> str:
    metrics = [
        "relevance",
        "correctness",
        "completeness",
        "faithfulness",
        "claim_support_rate",
        "unsupported_claim_rate",
    ]
    questions = questions or []
    rows = _score_rows(scores, metrics)
    condition_rows = condition_distribution_rows(rows, metrics)
    delta_rows = paired_delta_rows(rows, questions, metrics, [("A", "B"), ("B", "C"), ("C", "D")])

    lines = ["=== B5 canonical condition means ==="]
    for metric in metrics:
        mm = {row["condition"]: row["mean"] for row in condition_rows if row["metric"] == metric}
        lines.append(f"  {metric:24s} " + "  ".join(f"{c}:{v:.3f}" for c, v in sorted(mm.items())))
    lines.append("=== B5 canonical paired deltas ===")
    for row in delta_rows:
        lines.append(
            f"  {row['comparison']} {row['metric']:24s} "
            f"mean={row['mean_delta']:+.3f} 95%CI=[{row['ci95_low']:+.3f},{row['ci95_high']:+.3f}] "
            f"p={row['permutation_p']} holm={row['holm_p']} n={row['n_pairs']}"
        )
    lines.append("=== B5 judge agreement ===")
    for metric in ("faithfulness", "correctness", "completeness"):
        value = judge_agreement(scores, metric)
        lines.append(f"  {metric}: {'nan' if math.isnan(value) else f'{value:.3f}'}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compatibility entrypoint for canonical B5 statistics")
    parser.add_argument("--scores", required=True, help="Score JSONL path")
    parser.add_argument("--runs", default=None, help="Optional Run JSONL; enables auto metrics through b5_report")
    parser.add_argument("--questions", default="data/questions/formal12.jsonl")
    parser.add_argument("--questions-stress", default=None)
    parser.add_argument("--out-dir", default=None, help="Optional directory for full b5_report outputs")
    parser.add_argument("--metrics", nargs="+", default=DEFAULT_METRICS)
    parser.add_argument("--comparisons", default=None)
    args = parser.parse_args()

    cfg = load_config()
    questions = load_jsonl(args.questions)
    if args.questions_stress:
        stress_questions = load_jsonl(args.questions_stress)
        for q in stress_questions:
            q.setdefault("split", "stress")
        questions.extend(stress_questions)

    scores = load_jsonl(args.scores)
    if args.runs:
        runs = load_jsonl(args.runs)
        out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.mkdtemp(prefix="b5_stats_"))
        summary = run_b5_report(
            runs=runs,
            judge_scores=scores,
            questions=questions,
            out_dir=out_dir,
            runs_path=args.runs,
            scores_path=args.scores,
            metrics=args.metrics,
            comparisons=parse_comparisons(args.comparisons),
        )
        print(json.dumps(summary["condition_distribution"], ensure_ascii=False, indent=2))
        print(f"\nFull B5 outputs: {summary['out_dir']}")
    else:
        print(report(scores, questions))


if __name__ == "__main__":
    main()
