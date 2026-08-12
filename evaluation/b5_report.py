"""B5 automatic evaluation report.

This script implements only the automated scoring/reporting parts required by
the MVP plan.  It computes deterministic metrics from Run/Question records and
uses optional judge Score records only for metrics that cannot be derived
programmatically, plus judge-bias audit.

Usage:
  python -m evaluation.b5_report --demo
  python -m evaluation.b5_report --runs data/experiments/runs/runs_xxx.jsonl
  python -m evaluation.b5_report --runs ... --scores data/experiments/scores/scores_xxx.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import time
from collections import defaultdict
from itertools import combinations, product
from pathlib import Path
from typing import Any

from core.config import load_config
from core.dataclasses import load_jsonl, save_jsonl

DEFAULT_METRICS = [
    "rubric_keypoint_score",
    "hit_at_5",
    "mrr",
    "recall_at_50",
    "rerank_ndcg_8",
    "faithfulness",
    "citation_precision",
    "citation_coverage",
    "correctness",
    "completeness",
    "relevance",
    "claim_support_rate",
    "unsupported_claim_rate",
    "unsupported_critical_claim_rate",
    "abstention_quality",
]

METRIC_ALIASES = {
    "rubric_keypoint_score": ("rubric_keypoint_score", "correctness"),
    "hit_at_5": ("hit_at_5", "retrieval_hit_at_k", "retrieval_hit"),
    "rerank_ndcg_8": ("rerank_ndcg_8", "rerank_ndcg"),
    "unsupported_critical_claim_rate": ("unsupported_critical_claim_rate", "unsupported_claim_rate"),
}

LOWER_IS_BETTER_PREFIXES = ("unsupported",)
RETRIEVAL_CONDITIONS = {"B", "C", "D", "E"}
DEFAULT_EXPECTED_CONDITIONS = ["A", "A2", "B", "C", "D", "E"]
DEFAULT_COMPARISONS = [("A", "B"), ("B", "C"), ("C", "D"), ("C", "E"), ("A", "A2")]
PRIMARY_COMPARISONS = {"B-A", "C-B", "D-C"}
STRESS_COMPARISONS = {("C", "E"), ("E", "C")}
OBSOLETE_OUTPUTS = ["b5_human_review.json", "b5_condition_means.csv"]


def _metric_value(row: dict[str, Any], metric: str) -> float | None:
    for key in METRIC_ALIASES.get(metric, (metric,)):
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _fmt(value: Any, digits: int = 3) -> str:
    if value in (None, ""):
        return "NA"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number):
        return "NA"
    return f"{number:.{digits}f}"


def _question_id(row: dict[str, Any]) -> str:
    return str(row.get("question_id") or row.get("id") or "")


def _question_split(question: dict[str, Any] | None) -> str:
    if not question:
        return ""
    return str(
        question.get("split")
        or question.get("dataset_split")
        or question.get("dataset")
        or question.get("set")
        or ""
    ).lower()


def _is_stress_question(question: dict[str, Any] | None) -> bool:
    return _question_split(question) == "stress"


def _load_questions_with_stress(formal_path: str, stress_path: str | None, cfg: Any) -> list[dict[str, Any]]:
    """加载正式题 + STRESS 压力题（E-C 仅压力集对比依赖 split 标记）。

    - B2 正式题若自带 split 字段（TEST/STRESS...），保留原值；
    - 压力题文件里的题目若无显式 split，标记为 "stress"；
    - 这样 `--questions` 指向正式题文件时，E-C 比较也能覆盖 STRESS 题。
    """
    questions = load_jsonl(formal_path)
    stress_candidates = [stress_path]
    if stress_path is None:
        try:
            stress_candidates.append(str(cfg.path("questions_stress")))
        except Exception:
            pass
    for candidate in stress_candidates:
        if not candidate or not Path(candidate).exists():
            continue
        for d in load_jsonl(candidate):
            d.setdefault("split", "stress")
            questions.append(d)
    return questions


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _remove_obsolete_outputs(out_dir: Path) -> None:
    for filename in OBSOLETE_OUTPUTS:
        path = out_dir / filename
        if path.exists() and path.is_file():
            path.unlink()


def _as_evidence_id(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("id", ""))
    return str(item or "")


def _doc_id(evidence_id: str) -> str:
    """Document-level de-duplication key for citation metrics.

    Chunk suffix 优先剥离（对 pmid/nct/guideline/epmc 统一生效），
    避免 "nct:NCT001:chunk:0" / "guideline:x:chunk:1" 这类 ID 在
    Hit@K/Recall/引文指标里被当成与文档级 gold 不同的实体。
    """
    if ":chunk:" in evidence_id:
        return evidence_id.split(":chunk:", 1)[0]
    return evidence_id


def _ranked_ids(run: dict[str, Any], prefer_candidates: bool = True) -> list[str]:
    candidate_ids = [str(x) for x in run.get("candidate_ids") or [] if x]
    retrieved_ids = [_as_evidence_id(x) for x in run.get("retrieved_evidence") or []]
    retrieved_ids = [x for x in retrieved_ids if x]
    if prefer_candidates and candidate_ids:
        return candidate_ids
    return retrieved_ids or candidate_ids


def _hit_at_k(ranked: list[str], gold: set[str], k: int) -> float | None:
    if not gold:
        return None
    return 1.0 if {_doc_id(x) for x in ranked[:k]} & gold else 0.0


def _mrr(ranked: list[str], gold: set[str]) -> float | None:
    if not gold:
        return None
    for idx, evidence_id in enumerate(ranked, start=1):
        if _doc_id(evidence_id) in gold:
            return 1.0 / idx
    return 0.0


def _recall_at_k(ranked: list[str], gold: set[str], k: int) -> float | None:
    if not gold:
        return None
    hits = {_doc_id(x) for x in ranked[:k]} & gold
    return len(hits) / len(gold)


def _ndcg_at_k(ranked: list[str], gold: set[str], k: int) -> float | None:
    if not gold:
        return None
    dcg = 0.0
    seen: set[str] = set()
    for idx, evidence_id in enumerate(ranked[:k], start=1):
        doc = _doc_id(evidence_id)
        if doc in gold and doc not in seen:
            dcg += 1.0 / math.log2(idx + 1)
            seen.add(doc)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else 0.0


def _claim_decision(claim: dict[str, Any]) -> str:
    return str(claim.get("decision") or "").strip().lower()


def _claim_citation_ids(claim: dict[str, Any]) -> list[str]:
    ids = claim.get("evidence_ids") or []
    return [str(x) for x in ids if str(x)]


def _compute_claim_metrics(run: dict[str, Any], question: dict[str, Any] | None) -> dict[str, Any]:
    claims = [c for c in (run.get("claims") or []) if isinstance(c, dict)]
    decision = str(run.get("verification_decision") or "").upper()
    qtype = str((question or {}).get("question_type") or "")

    if qtype == "insufficient":
        abstention_quality = 1.0 if decision == "REFUSE" else 0.0
    elif qtype:
        abstention_quality = 0.0 if decision == "REFUSE" else 1.0
    else:
        abstention_quality = None

    if not claims:
        return {
            "claim_support_rate": None,
            "unsupported_claim_rate": None,
            "unsupported_critical_claim_rate": None,
            "citation_precision": None,
            "citation_coverage": None,
            "valid_citation_count": None,
            "total_citation_count": None,
            "claims_with_valid_cite": None,
            "key_claim_count": None,
            "abstention_quality": abstention_quality,
        }

    supported_claims = [c for c in claims if _claim_decision(c) == "supported"]
    unsupported_claims = [
        c for c in claims
        if _claim_decision(c) in {"unsupported", "contradicted", "insufficient", "pending"}
    ]
    critical_claims = [c for c in claims if str(c.get("criticality") or "").lower() == "critical"]
    unsupported_critical = [
        c for c in critical_claims
        if _claim_decision(c) != "supported"
    ]

    cited_doc_ids = []
    valid_cited_doc_ids = []
    key_claim_count = 0
    claims_with_valid_cite = 0
    for claim in claims:
        cite_docs = {_doc_id(eid) for eid in _claim_citation_ids(claim)}
        cited_doc_ids.extend(cite_docs)
        if str(claim.get("criticality") or "").lower() in {"critical", "important"}:
            key_claim_count += 1
        if _claim_decision(claim) == "supported" and cite_docs:
            valid_cited_doc_ids.extend(cite_docs)
            if str(claim.get("criticality") or "").lower() in {"critical", "important"}:
                claims_with_valid_cite += 1

    cited_doc_set = set(cited_doc_ids)
    valid_cited_doc_set = set(valid_cited_doc_ids)
    citation_precision = (
        len(valid_cited_doc_set) / len(cited_doc_set)
        if cited_doc_set else None
    )
    citation_coverage = (
        claims_with_valid_cite / key_claim_count
        if key_claim_count else None
    )

    return {
        "claim_support_rate": len(supported_claims) / len(claims),
        "unsupported_claim_rate": len(unsupported_claims) / len(claims),
        "unsupported_critical_claim_rate": (
            len(unsupported_critical) / len(critical_claims)
            if critical_claims else None
        ),
        "citation_precision": citation_precision,
        "citation_coverage": citation_coverage,
        "valid_citation_count": len(valid_cited_doc_set),
        "total_citation_count": len(cited_doc_set),
        "claims_with_valid_cite": claims_with_valid_cite,
        "key_claim_count": key_claim_count,
        "abstention_quality": abstention_quality,
    }


def compute_automatic_scores(runs: list[dict[str, Any]], questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute deterministic MD-required metrics from Run and Question records."""
    q_by_id = {q.get("id"): q for q in questions}
    rows = []
    for run in runs:
        qid = run.get("question_id")
        condition = str(run.get("condition") or "")
        question = q_by_id.get(qid, {})
        gold = {_doc_id(str(x)) for x in (question.get("gold_source_ids") or []) if str(x)}

        score = {
            "run_id": run.get("run_id"),
            "question_id": qid,
            "condition": condition,
            "judge_id": "auto",
            "metric_version": "b5-auto-v1",
            "rubric_version": (question.get("rubric_version")
                                or (question.get("rubric") or {}).get("rubric_version")
                                or ""),
            "latency_ms": run.get("latency_ms", 0),
            "input_tokens": run.get("input_tokens", 0),
            "output_tokens": run.get("output_tokens", 0),
            "estimated_cost": run.get("estimated_cost", 0.0),
            "answer_length": len(run.get("answer") or ""),
        }

        if condition in RETRIEVAL_CONDITIONS:
            initial_ranked = _ranked_ids(run, prefer_candidates=True)
            final_ranked = _ranked_ids(run, prefer_candidates=False)
            score.update(
                {
                    "hit_at_5": _hit_at_k(initial_ranked, gold, 5),
                    "mrr": _mrr(initial_ranked, gold),
                    "recall_at_50": _recall_at_k(initial_ranked, gold, 50),
                    "rerank_ndcg_8": _ndcg_at_k(final_ranked, gold, 8),
                }
            )

        score.update(_compute_claim_metrics(run, question))
        rows.append(score)
    return rows


def merge_auto_and_judge_scores(
    auto_scores: list[dict[str, Any]],
    judge_scores: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep computed deterministic metrics and append optional judge metrics."""
    by_run = {s.get("run_id"): dict(s) for s in auto_scores}
    for row in judge_scores:
        merged = dict(row)
        auto = by_run.get(row.get("run_id"), {})
        for key in (
            "question_id",
            "condition",
            "latency_ms",
            "input_tokens",
            "output_tokens",
            "estimated_cost",
            "answer_length",
        ):
            if merged.get(key) in (None, "") and auto.get(key) not in (None, ""):
                merged[key] = auto[key]
        for metric in (
            "hit_at_5",
            "mrr",
            "recall_at_50",
            "rerank_ndcg_8",
            "citation_precision",
            "citation_coverage",
            "claim_support_rate",
            "unsupported_claim_rate",
            "unsupported_critical_claim_rate",
            "abstention_quality",
            "valid_citation_count",
            "total_citation_count",
            "claims_with_valid_cite",
            "key_claim_count",
        ):
            if auto.get(metric) not in (None, ""):
                merged[metric] = auto[metric]
        by_run.setdefault(row.get("run_id"), auto)
        by_run[f"{row.get('run_id')}::{row.get('judge_id', '')}"] = merged
    return list(by_run.values()) if judge_scores else auto_scores


def aggregate_run_scores(score_rows: list[dict[str, Any]], metrics: list[str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in score_rows:
        if row.get("run_id"):
            grouped[str(row["run_id"])].append(row)

    out = []
    for run_id, rows in grouped.items():
        base = dict(rows[0])
        judges = {str(r.get("judge_id")) for r in rows if r.get("judge_id") and r.get("judge_id") != "auto"}
        base["judge_count"] = len(judges)
        for metric in metrics:
            values = [_metric_value(r, metric) for r in rows]
            values = [v for v in values if v is not None]
            base[metric] = statistics.fmean(values) if values else None
        out.append(base)
    return out


def condition_distribution_rows(run_scores: list[dict[str, Any]], metrics: list[str]) -> list[dict[str, Any]]:
    rows = []
    for metric in metrics:
        grouped: dict[str, list[float]] = defaultdict(list)
        for score in run_scores:
            value = _metric_value(score, metric)
            if value is not None:
                grouped[str(score.get("condition", ""))].append(value)
        for condition, values in sorted(grouped.items()):
            values_sorted = sorted(values)
            median = statistics.median(values_sorted)
            rows.append(
                {
                    "metric": metric,
                    "condition": condition,
                    "n": len(values),
                    "mean": round(statistics.fmean(values), 6),
                    "median": round(median, 6),
                    "sd": round(statistics.stdev(values), 6) if len(values) > 1 else 0.0,
                    "min": round(values_sorted[0], 6),
                    "max": round(values_sorted[-1], 6),
                }
            )
    return rows


def group_means(run_scores: list[dict[str, Any]], questions: list[dict[str, Any]], metrics: list[str]) -> list[dict[str, Any]]:
    q_meta = {q.get("id"): q for q in questions}
    rows = []
    for group_key in ("topic", "difficulty", "question_type", "split"):
        for metric in metrics:
            grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
            for score in run_scores:
                value = _metric_value(score, metric)
                q = q_meta.get(score.get("question_id"), {})
                group_value = _question_split(q) if group_key == "split" else q.get(group_key)
                condition = score.get("condition")
                if value is not None and group_value and condition:
                    grouped[(str(group_value), str(condition))].append(value)
            for (group_value, condition), values in sorted(grouped.items()):
                rows.append(
                    {
                        "group": group_key,
                        "value": group_value,
                        "metric": metric,
                        "condition": condition,
                        "n": len(values),
                        "mean": round(statistics.fmean(values), 6),
                    }
                )
    return rows


def citation_macro_micro_rows(run_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = [
        ("citation_precision", "valid_citation_count", "total_citation_count"),
        ("citation_coverage", "claims_with_valid_cite", "key_claim_count"),
    ]
    rows = []
    for metric, numerator_key, denominator_key in specs:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for score in run_scores:
            if _metric_value(score, metric) is not None:
                grouped[str(score.get("condition", ""))].append(score)
        for condition, subset in sorted(grouped.items()):
            ratios = [_metric_value(row, metric) for row in subset]
            ratios = [x for x in ratios if x is not None]
            numerator = sum(float(row.get(numerator_key) or 0) for row in subset)
            denominator = sum(float(row.get(denominator_key) or 0) for row in subset)
            rows.append(
                {
                    "metric": metric,
                    "condition": condition,
                    "macro_mean": round(statistics.fmean(ratios), 6) if ratios else "",
                    "micro_mean": round(numerator / denominator, 6) if denominator else "",
                    "micro_numerator": round(numerator, 6) if denominator else "",
                    "micro_denominator": round(denominator, 6) if denominator else "",
                    "micro_status": "available" if denominator else "not_available_no_citation_counts",
                }
            )
    return rows


def _question_condition_scores(run_scores: list[dict[str, Any]], metric: str) -> dict[str, dict[str, float]]:
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in run_scores:
        value = _metric_value(row, metric)
        if value is not None and row.get("question_id") and row.get("condition"):
            grouped[(str(row["question_id"]), str(row["condition"]))].append(value)
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for (qid, condition), values in grouped.items():
        out[qid][condition] = statistics.fmean(values)
    return out


def _bootstrap_ci_stratified(
    deltas_by_qid: dict[str, float],
    qtype_by_qid: dict[str, str],
    samples: int = 2000,
    seed: int = 42,
) -> tuple[float | None, float | None]:
    if not deltas_by_qid:
        return None, None
    strata: dict[str, list[float]] = defaultdict(list)
    for qid, delta in deltas_by_qid.items():
        strata[qtype_by_qid.get(qid, "unknown")].append(delta)
    rng = random.Random(seed)
    boot_means = []
    for _ in range(samples):
        sample = []
        for values in strata.values():
            sample.extend(rng.choice(values) for _ in values)
        boot_means.append(statistics.fmean(sample))
    boot_means.sort()
    return (
        boot_means[int(0.025 * (len(boot_means) - 1))],
        boot_means[int(0.975 * (len(boot_means) - 1))],
    )


def paired_permutation_p(deltas: list[float], max_exact_n: int = 14, samples: int = 20000, seed: int = 42) -> float | None:
    """Two-sided paired sign-flip permutation test on mean paired deltas.

    平局（delta == 0）保留在置换分布中（它们稀释显著性，不剔除），
    避免小样本下高估效应。
    """
    if not deltas:
        return None
    observed = abs(statistics.fmean(deltas))
    n = len(deltas)
    if n <= max_exact_n:
        total = 0
        extreme = 0
        for signs in product((-1, 1), repeat=n):
            total += 1
            mean = abs(statistics.fmean(d * s for d, s in zip(deltas, signs)))
            if mean >= observed - 1e-12:
                extreme += 1
        return extreme / total
    rng = random.Random(seed)
    extreme = 0
    for _ in range(samples):
        mean = abs(statistics.fmean(d * rng.choice((-1, 1)) for d in deltas))
        if mean >= observed - 1e-12:
            extreme += 1
    return extreme / samples


def _holm_adjust(rows: list[dict[str, Any]]) -> None:
    indexed = [
        (idx, row["permutation_p"])
        for idx, row in enumerate(rows)
        if isinstance(row.get("permutation_p"), (float, int))
        and row.get("comparison") in PRIMARY_COMPARISONS
    ]
    indexed.sort(key=lambda item: item[1])
    previous = 0.0
    m = len(indexed)
    for rank, (idx, p_value) in enumerate(indexed, start=1):
        adjusted = min(1.0, max(previous, p_value * (m - rank + 1)))
        rows[idx]["holm_p"] = round(adjusted, 6)
        previous = adjusted


def paired_delta_rows(
    run_scores: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    metrics: list[str],
    comparisons: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    q_by_id = {_question_id(q): q for q in questions}
    qtype_by_qid = {qid: str(q.get("question_type") or "unknown") for qid, q in q_by_id.items()}
    rows = []
    for metric in metrics:
        by_q = _question_condition_scores(run_scores, metric)
        for left, right in comparisons:
            stress_only = (left, right) in STRESS_COMPARISONS
            deltas_by_qid = {
                qid: conds[right] - conds[left]
                for qid, conds in by_q.items()
                if left in conds and right in conds
                and (not stress_only or _is_stress_question(q_by_id.get(qid)))
            }
            if not deltas_by_qid:
                continue
            deltas = list(deltas_by_qid.values())
            mean_delta = statistics.fmean(deltas)
            better_when = "lower" if metric.startswith(LOWER_IS_BETTER_PREFIXES) else "higher"
            if mean_delta == 0:
                favored = "tie"
            elif (mean_delta > 0 and better_when == "higher") or (mean_delta < 0 and better_when == "lower"):
                favored = right
            else:
                favored = left
            lo, hi = _bootstrap_ci_stratified(deltas_by_qid, qtype_by_qid)
            p_value = paired_permutation_p(deltas)
            rows.append(
                {
                    "metric": metric,
                    "comparison": f"{right}-{left}",
                    "scope": "stress" if stress_only else "all_available_questions",
                    "n_pairs": len(deltas),
                    "mean_delta": round(mean_delta, 6),
                    "ci95_low": round(lo, 6) if lo is not None else "",
                    "ci95_high": round(hi, 6) if hi is not None else "",
                    "permutation_p": round(p_value, 6) if p_value is not None else "",
                    "holm_p": "",
                    "better_when": better_when,
                    "favored_condition": favored,
                    "wins": sum(1 for d in deltas if d > 0),
                    "losses": sum(1 for d in deltas if d < 0),
                    "ties": sum(1 for d in deltas if d == 0),
                }
            )
    _holm_adjust(rows)
    return rows


def per_question_delta_rows(
    run_scores: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    metrics: list[str],
    comparisons: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    q_by_id = {_question_id(q): q for q in questions}
    rows = []
    for metric in metrics:
        by_q = _question_condition_scores(run_scores, metric)
        better_when = "lower" if metric.startswith(LOWER_IS_BETTER_PREFIXES) else "higher"
        for left, right in comparisons:
            stress_only = (left, right) in STRESS_COMPARISONS
            for qid, conds in sorted(by_q.items()):
                if left not in conds or right not in conds:
                    continue
                question = q_by_id.get(qid, {})
                if stress_only and not _is_stress_question(question):
                    continue
                delta = conds[right] - conds[left]
                right_better = delta < 0 if better_when == "lower" else delta > 0
                rows.append(
                    {
                        "question_id": qid,
                        "question_type": question.get("question_type") or "",
                        "topic": question.get("topic") or "",
                        "difficulty": question.get("difficulty") or "",
                        "split": _question_split(question),
                        "metric": metric,
                        "comparison": f"{right}-{left}",
                        "scope": "stress" if stress_only else "all_available_questions",
                        "left_condition": left,
                        "right_condition": right,
                        "left_score": round(conds[left], 6),
                        "right_score": round(conds[right], 6),
                        "delta": round(delta, 6),
                        "better_when": better_when,
                        "right_condition_better": right_better,
                    }
                )
    return rows


def counterexample_rows(question_delta_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary_metrics = {"rubric_keypoint_score", "unsupported_critical_claim_rate", "faithfulness", "citation_precision", "citation_coverage"}
    rows = []
    for row in question_delta_rows:
        if row["metric"] not in primary_metrics:
            continue
        if row["comparison"] in {"B-A", "C-B", "D-C"} and not row["right_condition_better"]:
            rows.append({**row, "counterexample_type": "expected_gain_not_seen"})
        elif row["comparison"] == "E-C" and (row["right_condition_better"] or row["delta"] == 0):
            # 劣化未生效（E >= C，含平局）都算“检索拖累”反例：
            # 预注册假设是检索污染应拖累回答，平局同样需要披露。
            rows.append({**row, "counterexample_type": "degraded_condition_not_worse"})
    return rows


def comparison_availability_rows(
    run_scores: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    metrics: list[str],
    comparisons: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    q_by_id = {_question_id(q): q for q in questions}
    all_qids = sorted(qid for qid in q_by_id if qid)
    condition_by_q: dict[str, set[str]] = defaultdict(set)
    metric_by_q_condition: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in run_scores:
        qid = str(row.get("question_id") or "")
        condition = str(row.get("condition") or "")
        if not qid or not condition:
            continue
        condition_by_q[qid].add(condition)
        for metric in metrics:
            if _metric_value(row, metric) is not None:
                metric_by_q_condition[(qid, condition)].add(metric)

    rows = []
    for left, right in comparisons:
        stress_only = (left, right) in STRESS_COMPARISONS
        eligible_qids = [
            qid for qid in all_qids
            if not stress_only or _is_stress_question(q_by_id.get(qid))
        ]
        missing_left = [qid for qid in eligible_qids if left not in condition_by_q[qid]]
        missing_right = [qid for qid in eligible_qids if right not in condition_by_q[qid]]
        for metric in metrics:
            paired_qids = [
                qid for qid in eligible_qids
                if metric in metric_by_q_condition[(qid, left)]
                and metric in metric_by_q_condition[(qid, right)]
            ]
            rows.append(
                {
                    "comparison": f"{right}-{left}",
                    "metric": metric,
                    "scope": "stress" if stress_only else "all_available_questions",
                    "eligible_questions": len(eligible_qids),
                    "paired_questions": len(paired_qids),
                    "missing_left_condition": len(missing_left),
                    "missing_right_condition": len(missing_right),
                    "status": "available" if paired_qids else "missing_or_unscorable",
                }
            )
    return rows


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    denom_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if denom_x == 0 or denom_y == 0:
        return None
    return numerator / (denom_x * denom_y)


# ---------- 评审一致性（§6.3：二元标签 Cohen's kappa，有序评分加权 kappa） ----------

ORDINAL_JUDGE_METRICS = {"relevance", "correctness", "completeness", "faithfulness", "rubric_keypoint_score"}


def _cohen_kappa(a: list[float], b: list[float]) -> float | None:
    """Cohen's kappa（二元标签，类别集合取并集，两端各有至少一个非空类别）。"""
    if len(a) != len(b) or not a:
        return None
    labels = sorted({round(x) for x in a + b})
    if len(labels) < 2:
        return None  # 无类别变化无法估计 kappa
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if round(x) == round(y)) / n
    expected = 0.0
    for label in labels:
        pa = sum(1 for x in a if round(x) == label) / n
        pb = sum(1 for y in b if round(y) == label) / n
        expected += pa * pb
    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def _linear_weighted_kappa(a: list[float], b: list[float]) -> float | None:
    """线性加权 kappa（有序 1..5 评分；先取整到整数类别）。"""
    if len(a) != len(b) or not a:
        return None
    labels = sorted({round(x) for x in a + b})
    if len(labels) < 2:
        return None
    n = len(a)
    pa = {label: sum(1 for x in a if round(x) == label) / n for label in labels}
    pb = {label: sum(1 for y in b if round(y) == label) / n for label in labels}
    max_w = max(abs(i - j) for i in labels for j in labels) or 1.0
    weights = {(i, j): 1.0 - abs(i - j) / max_w for i in labels for j in labels}
    observed = sum(weights[(round(x), round(y))] for x, y in zip(a, b)) / n
    expected = sum(pa[i] * pb[j] * weights[(i, j)] for i in labels for j in labels)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def _judge_kappa(judge_rows: list[dict], metric: str) -> dict[str, Any]:
    """评审一致性 kappa（§6.3.6）：同一 judge 对在多个 run 上的评分向量计算。

    - 有序 1-5 指标（relevance/correctness/completeness/faithfulness/rubric_keypoint_score）
      用线性加权 kappa（先取整到整数类别）；
    - 二元指标（值全为 0/1，如 abstention_quality、hit_at_5）用 Cohen's kappa；
    - 其他连续比例指标不适用 kappa（保留 mean_abs_diff），返回 None 并注明。
    """
    by_judge_run: dict[str, dict[str, float]] = defaultdict(dict)
    for row in judge_rows:
        judge_id = str(row.get("judge_id") or "")
        run_id = str(row.get("run_id") or "")
        value = _metric_value(row, metric)
        if judge_id and run_id and value is not None:
            by_judge_run[judge_id][run_id] = value
    judge_ids = sorted(by_judge_run)
    is_ordinal = metric in ORDINAL_JUDGE_METRICS
    kappas: list[float] = []
    pair_count = 0
    for j1, j2 in combinations(judge_ids, 2):
        common = [r for r in by_judge_run[j1] if r in by_judge_run[j2]]
        if len(common) < 2:
            continue
        pair_count += 1
        a = [by_judge_run[j1][r] for r in common]
        b = [by_judge_run[j2][r] for r in common]
        binary_ok = all(v in (0.0, 1.0) for v in a + b)
        if is_ordinal:
            kappa = _linear_weighted_kappa(a, b)
        elif binary_ok:
            kappa = _cohen_kappa(a, b)
        else:
            kappa = None
        if kappa is not None:
            kappas.append(kappa)
    return {
        "kappa_judge_pairs": pair_count,
        "kappa_estimable_pairs": len(kappas),
        "mean_kappa": round(statistics.fmean(kappas), 6) if kappas else None,
        "kappa_type": "linear_weighted" if is_ordinal else "cohen_binary",
        "note": "kappa 需同一 judge 对在 >=2 个 run 上评分；连续比例指标（如 claim_support_rate）不适用 kappa，用 mean_abs_diff。" if not kappas else "",
    }


def judge_audit(judge_scores: list[dict[str, Any]], run_scores: list[dict[str, Any]], metrics: list[str]) -> dict[str, Any]:
    judge_rows = [row for row in judge_scores if row.get("judge_id") and row.get("judge_id") != "auto"]
    run_by_id = {str(row.get("run_id")): row for row in run_scores if row.get("run_id")}
    by_run: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in judge_rows:
        by_run[str(row.get("run_id"))].append(row)

    agreement = {}
    for metric in metrics:
        diffs = []
        for rows in by_run.values():
            values = [_metric_value(row, metric) for row in rows]
            values = [v for v in values if v is not None]
            for left, right in combinations(values, 2):
                diffs.append(abs(left - right))
        agreement[metric] = {
            "paired_judge_rows": len(diffs),
            "mean_abs_diff": round(statistics.fmean(diffs), 6) if diffs else None,
            "max_abs_diff": round(max(diffs), 6) if diffs else None,
            "kappa": _judge_kappa(judge_rows, metric),
        }

    position_bias = {}
    for metric in metrics:
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in judge_rows:
            position = row.get("position") or row.get("answer_position") or row.get("display_position")
            value = _metric_value(row, metric)
            if position is not None and value is not None:
                grouped[str(position)].append(value)
        position_bias[metric] = (
            {key: round(statistics.fmean(vals), 6) for key, vals in sorted(grouped.items())}
            if grouped else "not_available"
        )

    family_bias = {}
    for metric in metrics:
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in judge_rows:
            family = row.get("judge_family") or row.get("judge_model") or row.get("judge_provider")
            value = _metric_value(row, metric)
            if family and value is not None:
                grouped[str(family)].append(value)
        if grouped:
            means = {key: statistics.fmean(vals) for key, vals in grouped.items()}
            family_bias[metric] = {
                "means": {key: round(val, 6) for key, val in sorted(means.items())},
                "spread": round(max(means.values()) - min(means.values()), 6) if len(means) > 1 else 0.0,
            }
        else:
            family_bias[metric] = "not_available"

    length_bias = {}
    for metric in metrics:
        xs, ys = [], []
        for row in run_scores:
            value = _metric_value(row, metric)
            length = row.get("answer_length")
            if value is not None and isinstance(length, (int, float)):
                xs.append(float(length))
                ys.append(value)
        corr = _pearson(xs, ys)
        length_bias[metric] = {
            "n": len(xs),
            "pearson_answer_length": round(corr, 6) if corr is not None else None,
        }

    citation_appearance_bias = {}
    for metric in metrics:
        xs, ys = [], []
        for row in judge_rows:
            value = _metric_value(row, metric)
            run = run_by_id.get(str(row.get("run_id")), {})
            citation_count = (
                row.get("displayed_citation_count")
                or row.get("citation_count")
                or run.get("total_citation_count")
            )
            if value is not None and isinstance(citation_count, (int, float)):
                xs.append(float(citation_count))
                ys.append(value)
        corr = _pearson(xs, ys)
        citation_appearance_bias[metric] = {
            "n": len(xs),
            "pearson_citation_count": round(corr, 6) if corr is not None else None,
        }

    control_sample_audit = {}
    for control_type in ("style", "position_swap", "wrong_citations"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in judge_rows:
            row_type = str(row.get("control_type") or row.get("audit_control_type") or "").lower()
            pair_id = row.get("control_id") or row.get("audit_pair_id")
            if row_type == control_type and pair_id:
                grouped[str(pair_id)].append(row)
        metric_summary = {}
        for metric in metrics:
            spreads = []
            for rows in grouped.values():
                values = [_metric_value(row, metric) for row in rows]
                values = [v for v in values if v is not None]
                if len(values) >= 2:
                    spreads.append(max(values) - min(values))
            metric_summary[metric] = {
                "control_groups": len(grouped),
                "scorable_groups": len(spreads),
                "mean_score_spread": round(statistics.fmean(spreads), 6) if spreads else None,
                "max_score_spread": round(max(spreads), 6) if spreads else None,
            }
        control_sample_audit[control_type] = metric_summary

    randomization_audit = {
        "rows": len(judge_rows),
        "with_anonymous_label": sum(1 for row in judge_rows if row.get("anonymous_label") or row.get("answer_label")),
        "with_position": sum(1 for row in judge_rows if row.get("position") or row.get("answer_position") or row.get("display_position")),
        "with_randomization_seed": sum(1 for row in judge_rows if row.get("randomization_seed") or row.get("shuffle_seed")),
        "status": "available" if judge_rows else "not_available_no_judge_scores",
    }

    return {
        "judge_ids": sorted({str(row.get("judge_id")) for row in judge_rows if row.get("judge_id")}),
        "scored_runs": len(by_run),
        "runs_with_multiple_judges": sum(1 for rows in by_run.values() if len({r.get("judge_id") for r in rows}) >= 2),
        "agreement": agreement,
        "position_bias": position_bias,
        "judge_family_bias": family_bias,
        "length_bias": length_bias,
        "citation_appearance_bias": citation_appearance_bias,
        "control_sample_audit": control_sample_audit,
        "randomization_audit": randomization_audit,
        "notes": [
            "Only non-auto judge rows are used for judge agreement and judge-family audits.",
            "Position-bias audit requires position/answer_position/display_position fields.",
            "Length-bias audit uses answer length from runs.",
            "Judge-family audit requires judge_family/judge_model/judge_provider fields.",
            "Citation-appearance audit requires displayed_citation_count/citation_count or computed citation counts.",
            "Control-sample audit requires control_type plus control_id/audit_pair_id fields.",
            "Anonymous-order audit requires anonymous_label/answer_label and randomization_seed/shuffle_seed fields.",
        ],
    }


def cost_latency_rows(run_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for condition in sorted({str(r.get("condition")) for r in run_scores if r.get("condition")}):
        subset = [r for r in run_scores if str(r.get("condition")) == condition]
        latency = [float(r.get("latency_ms") or 0) for r in subset]
        cost = [float(r.get("estimated_cost") or 0) for r in subset]
        in_tokens = [float(r.get("input_tokens") or 0) for r in subset]
        out_tokens = [float(r.get("output_tokens") or 0) for r in subset]
        rows.append(
            {
                "condition": condition,
                "n": len(subset),
                "mean_latency_ms": round(statistics.fmean(latency), 3) if latency else 0,
                "total_input_tokens": int(sum(in_tokens)),
                "total_output_tokens": int(sum(out_tokens)),
                "total_cost": round(sum(cost), 6),
                "mean_cost": round(statistics.fmean(cost), 6) if cost else 0,
            }
        )
    return rows


def expected_condition_summary(expected_conditions: list[str], run_scores: list[dict[str, Any]]) -> dict[str, Any]:
    present = sorted({str(row.get("condition")) for row in run_scores if row.get("condition")})
    missing = [condition for condition in expected_conditions if condition not in present]
    return {
        "expected": expected_conditions,
        "present": present,
        "missing": missing,
        "extra": sorted(condition for condition in present if condition not in expected_conditions),
    }


def parse_comparisons(text: str | None) -> list[tuple[str, str]]:
    if not text:
        return DEFAULT_COMPARISONS
    pairs = []
    for item in text.split(","):
        left, sep, right = item.strip().partition(":")
        if not sep:
            raise ValueError(f"Bad comparison {item!r}; expected A:B,B:C")
        pairs.append((left.strip(), right.strip()))
    return pairs


def _svg_bar_chart(path: Path, title: str, rows: list[tuple[str, float]], width: int = 900) -> None:
    height = max(260, 70 + len(rows) * 34)
    max_abs = max([abs(value) for _, value in rows] + [1.0])
    has_negative = any(value < 0 for _, value in rows)
    zero_x = width // 2 if has_negative else 140
    plot_w = width // 2 - 60 if has_negative else width - zero_x - 40
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<style>text{font-family:Arial,Microsoft YaHei,sans-serif;font-size:13px}.title{font-size:18px;font-weight:bold}.axis{stroke:#555;stroke-width:1}.pos{fill:#2563eb}.neg{fill:#dc2626}</style>',
        f'<text class="title" x="20" y="30">{_xml(title)}</text>',
        f'<line class="axis" x1="{zero_x}" y1="52" x2="{zero_x}" y2="{height - 25}"/>',
    ]
    for idx, (label, value) in enumerate(rows):
        y = 62 + idx * 34
        bar = int((abs(value) / max_abs) * plot_w)
        x = zero_x if value >= 0 else zero_x - bar
        css = "pos" if value >= 0 else "neg"
        lines.append(f'<text x="12" y="{y + 16}">{_xml(label[:24])}</text>')
        lines.append(f'<rect class="{css}" x="{x}" y="{y}" width="{bar}" height="20" rx="2"/>')
        label_x = x + bar + 6 if value >= 0 else x - 58
        lines.append(f'<text x="{label_x}" y="{y + 15}">{value:.3f}</text>')
    lines.append("</svg>")
    _write_text(path, "\n".join(lines))


def _xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_charts(
    out_dir: Path,
    condition_rows: list[dict[str, Any]],
    delta_rows: list[dict[str, Any]],
    question_delta_rows: list[dict[str, Any]],
    cost_rows: list[dict[str, Any]],
) -> None:
    mean_metric = next(
        (metric for metric in ("faithfulness", "rubric_keypoint_score", "citation_precision", "claim_support_rate") if any(row["metric"] == metric for row in condition_rows)),
        None,
    )
    mean_data = [
        (row["condition"], float(row["mean"]))
        for row in condition_rows
        if row["metric"] == mean_metric
    ]
    _svg_bar_chart(out_dir / "b5_condition_means.svg", f"Condition means: {mean_metric or 'no data'}", mean_data)

    delta_data = [
        (f"{row['comparison']} {row['metric']}", float(row["mean_delta"]))
        for row in delta_rows
        if row["metric"] in {"rubric_keypoint_score", "faithfulness", "citation_precision"}
    ][:14]
    _svg_bar_chart(out_dir / "b5_paired_deltas.svg", "Paired deltas", delta_data)

    question_metric = next(
        (
            metric for metric in ("rubric_keypoint_score", "unsupported_critical_claim_rate", "faithfulness", "citation_precision")
            if any(row["metric"] == metric and row["comparison"] in {"B-A", "C-B", "D-C", "E-C"} for row in question_delta_rows)
        ),
        None,
    )
    question_data = [
        (f"{row['comparison']} {row['question_id']}", float(row["delta"]))
        for row in question_delta_rows
        if row["metric"] == question_metric and row["comparison"] in {"B-A", "C-B", "D-C", "E-C"}
    ][:24]
    _svg_bar_chart(out_dir / "b5_question_deltas.svg", f"Per-question deltas: {question_metric or 'no data'}", question_data)

    latency_data = [(row["condition"], float(row["mean_latency_ms"])) for row in cost_rows]
    _svg_bar_chart(out_dir / "b5_cost_latency.svg", "Mean latency by condition", latency_data)


def make_markdown_report(
    out_dir: Path,
    runs_path: str,
    scores_path: str | None,
    condition_summary: dict[str, Any],
    condition_rows: list[dict[str, Any]],
    delta_rows: list[dict[str, Any]],
    citation_rows: list[dict[str, Any]],
    judge_report: dict[str, Any],
    cost_rows: list[dict[str, Any]],
    limitations: list[str],
) -> str:
    lines = [
        "# B5 Automatic Evaluation Report",
        "",
        "仅供教学研究，不用于临床诊疗。",
        "",
        "## Inputs",
        f"- Runs: `{runs_path}`",
        f"- Judge scores: `{scores_path or 'not provided'}`",
        f"- Expected conditions: `{', '.join(condition_summary['expected'])}`",
        f"- Present conditions: `{', '.join(condition_summary['present']) or 'none'}`",
        f"- Missing conditions: `{', '.join(condition_summary['missing']) or 'none'}`",
        "",
        "## Condition Distribution",
        "| metric | condition | n | mean | median | sd | min | max |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in condition_rows:
        lines.append(
            f"| {row['metric']} | {row['condition']} | {row['n']} | {_fmt(row['mean'])} | "
            f"{_fmt(row['median'])} | {_fmt(row['sd'])} | {_fmt(row['min'])} | {_fmt(row['max'])} |"
        )

    lines += [
        "",
        "## Paired Comparisons",
        "Bootstrap is stratified by question_type. Significance uses a paired sign-flip permutation test; Holm correction is applied to preregistered primary comparisons A-B, B-C, and C-D.",
        "",
        "| metric | comparison | better_when | favored | n | mean_delta | 95% CI | permutation_p | holm_p | wins/losses/ties |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in delta_rows:
        lines.append(
            f"| {row['metric']} | {row['comparison']} | {row['better_when']} | {row['favored_condition']} | "
            f"{row['n_pairs']} | {_fmt(row['mean_delta'])} | [{_fmt(row['ci95_low'])}, {_fmt(row['ci95_high'])}] | "
            f"{_fmt(row['permutation_p'])} | {_fmt(row.get('holm_p'))} | {row['wins']}/{row['losses']}/{row['ties']} |"
        )

    lines += [
        "",
        "## Citation Macro/Micro",
        "| metric | condition | macro_mean | micro_mean | numerator | denominator | status |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in citation_rows:
        lines.append(
            f"| {row['metric']} | {row['condition']} | {_fmt(row['macro_mean'])} | {_fmt(row['micro_mean'])} | "
            f"{_fmt(row['micro_numerator'])} | {_fmt(row['micro_denominator'])} | {row['micro_status']} |"
        )

    lines += [
        "",
        "## Judge Audit",
        f"- Judge IDs: `{', '.join(judge_report['judge_ids']) or 'none'}`",
        f"- Scored runs: `{judge_report['scored_runs']}`",
        f"- Runs with multiple judges: `{judge_report['runs_with_multiple_judges']}`",
        "",
        "| metric | judge pairs | mean abs diff | max abs diff | length corr |",
        "|---|---:|---:|---:|---:|",
    ]
    for metric, item in judge_report["agreement"].items():
        length = judge_report["length_bias"].get(metric, {})
        lines.append(
            f"| {metric} | {item['paired_judge_rows']} | {_fmt(item['mean_abs_diff'])} | "
            f"{_fmt(item['max_abs_diff'])} | {_fmt(length.get('pearson_answer_length'))} |"
        )

    lines += [
        "",
        "## Cost, Tokens, Latency",
        "| condition | n | mean latency ms | input tokens | output tokens | total cost | mean cost |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in cost_rows:
        lines.append(
            f"| {row['condition']} | {row['n']} | {row['mean_latency_ms']:.1f} | "
            f"{row['total_input_tokens']} | {row['total_output_tokens']} | {row['total_cost']:.6f} | {row['mean_cost']:.6f} |"
        )

    if limitations:
        lines += ["", "## Limitations"]
        for item in limitations:
            lines.append(f"- {item}")

    lines += [
        "",
        "## Output Files",
        f"- `{out_dir / 'b5_auto_scores.jsonl'}`",
        f"- `{out_dir / 'b5_condition_distribution.csv'}`",
        f"- `{out_dir / 'b5_group_means.csv'}`",
        f"- `{out_dir / 'b5_paired_deltas.csv'}`",
        f"- `{out_dir / 'b5_citation_rollup.csv'}`",
        f"- `{out_dir / 'b5_judge_audit.json'}`",
        f"- `{out_dir / 'b5_cost_latency.csv'}`",
        f"- `{out_dir / 'b5_summary.json'}`",
        f"- `{out_dir / 'b5_condition_means.svg'}`",
        f"- `{out_dir / 'b5_paired_deltas.svg'}`",
        f"- `{out_dir / 'b5_cost_latency.svg'}`",
    ]
    return "\n".join(lines) + "\n"


def make_markdown_report_v2(
    out_dir: Path,
    runs_path: str,
    scores_path: str | None,
    condition_summary: dict[str, Any],
    condition_rows: list[dict[str, Any]],
    delta_rows: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    citation_rows: list[dict[str, Any]],
    judge_report: dict[str, Any],
    cost_rows: list[dict[str, Any]],
    counterexamples: list[dict[str, Any]],
    limitations: list[str],
) -> str:
    lines = [
        "# B5 Automatic Evaluation Report",
        "",
        "For education/research only; not for clinical use.",
        "",
        "## Inputs",
        f"- Runs: `{runs_path}`",
        f"- Judge scores: `{scores_path or 'not provided'}`",
        f"- Expected conditions: `{', '.join(condition_summary['expected'])}`",
        f"- Present conditions: `{', '.join(condition_summary['present']) or 'none'}`",
        f"- Missing conditions: `{', '.join(condition_summary['missing']) or 'none'}`",
        "",
        "## Condition Distribution",
        "| metric | condition | n | mean | median | sd | min | max |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in condition_rows:
        lines.append(
            f"| {row['metric']} | {row['condition']} | {row['n']} | {_fmt(row['mean'])} | "
            f"{_fmt(row['median'])} | {_fmt(row['sd'])} | {_fmt(row['min'])} | {_fmt(row['max'])} |"
        )

    lines += [
        "",
        "## Paired Comparisons",
        "Bootstrap is stratified by question_type. Significance uses a paired sign-flip permutation test; Holm correction is applied to preregistered primary comparisons A-B, B-C, and C-D. E-C is restricted to STRESS questions.",
        "",
        "| metric | comparison | scope | better_when | favored | n | mean_delta | 95% CI | permutation_p | holm_p | wins/losses/ties |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in delta_rows:
        lines.append(
            f"| {row['metric']} | {row['comparison']} | {row['scope']} | {row['better_when']} | {row['favored_condition']} | "
            f"{row['n_pairs']} | {_fmt(row['mean_delta'])} | [{_fmt(row['ci95_low'])}, {_fmt(row['ci95_high'])}] | "
            f"{_fmt(row['permutation_p'])} | {_fmt(row.get('holm_p'))} | {row['wins']}/{row['losses']}/{row['ties']} |"
        )

    lines += [
        "",
        "## Comparison Availability",
        "| comparison | metric | scope | eligible | paired | missing left | missing right | status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in comparison_rows:
        lines.append(
            f"| {row['comparison']} | {row['metric']} | {row['scope']} | {row['eligible_questions']} | "
            f"{row['paired_questions']} | {row['missing_left_condition']} | {row['missing_right_condition']} | {row['status']} |"
        )

    lines += [
        "",
        "## Citation Macro/Micro",
        "| metric | condition | macro_mean | micro_mean | numerator | denominator | status |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in citation_rows:
        lines.append(
            f"| {row['metric']} | {row['condition']} | {_fmt(row['macro_mean'])} | {_fmt(row['micro_mean'])} | "
            f"{_fmt(row['micro_numerator'])} | {_fmt(row['micro_denominator'])} | {row['micro_status']} |"
        )

    lines += [
        "",
        "## Judge Audit",
        f"- Judge IDs: `{', '.join(judge_report['judge_ids']) or 'none'}`",
        f"- Scored runs: `{judge_report['scored_runs']}`",
        f"- Runs with multiple judges: `{judge_report['runs_with_multiple_judges']}`",
        f"- Anonymous/randomization audit: `{judge_report['randomization_audit']['status']}`",
        "",
        "| metric | judge pairs | mean abs diff | max abs diff | kappa | kappa type | length corr | citation-count corr |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric, item in judge_report["agreement"].items():
        length = judge_report["length_bias"].get(metric, {})
        citation = judge_report["citation_appearance_bias"].get(metric, {})
        kappa = item.get("kappa") or {}
        lines.append(
            f"| {metric} | {item['paired_judge_rows']} | {_fmt(item['mean_abs_diff'])} | "
            f"{_fmt(item['max_abs_diff'])} | {_fmt(kappa.get('mean_kappa'))} | "
            f"{kappa.get('kappa_type') or 'n/a'} | {_fmt(length.get('pearson_answer_length'))} | "
            f"{_fmt(citation.get('pearson_citation_count'))} |"
        )

    lines += [
        "",
        "## Cost, Tokens, Latency",
        "| condition | n | mean latency ms | input tokens | output tokens | total cost | mean cost |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in cost_rows:
        lines.append(
            f"| {row['condition']} | {row['n']} | {row['mean_latency_ms']:.1f} | "
            f"{row['total_input_tokens']} | {row['total_output_tokens']} | {row['total_cost']:.6f} | {row['mean_cost']:.6f} |"
        )

    if limitations:
        lines += ["", "## Limitations"]
        for item in limitations:
            lines.append(f"- {item}")

    lines += [
        "",
        "## Counterexamples",
        f"- Counterexample rows kept: `{len(counterexamples)}`",
    ]
    for row in counterexamples[:8]:
        lines.append(
            f"- `{row['comparison']}` `{row['metric']}` question `{row['question_id']}` delta `{_fmt(row['delta'])}`: {row['counterexample_type']}"
        )

    lines += [
        "",
        "## Output Files",
        f"- `{out_dir / 'b5_auto_scores.jsonl'}`",
        f"- `{out_dir / 'b5_condition_distribution.csv'}`",
        f"- `{out_dir / 'b5_group_means.csv'}`",
        f"- `{out_dir / 'b5_comparison_availability.csv'}`",
        f"- `{out_dir / 'b5_paired_deltas.csv'}`",
        f"- `{out_dir / 'b5_question_deltas.csv'}`",
        f"- `{out_dir / 'b5_counterexamples.csv'}`",
        f"- `{out_dir / 'b5_citation_rollup.csv'}`",
        f"- `{out_dir / 'b5_judge_audit.json'}`",
        f"- `{out_dir / 'b5_cost_latency.csv'}`",
        f"- `{out_dir / 'b5_summary.json'}`",
        f"- `{out_dir / 'b5_condition_means.svg'}`",
        f"- `{out_dir / 'b5_paired_deltas.svg'}`",
        f"- `{out_dir / 'b5_question_deltas.svg'}`",
        f"- `{out_dir / 'b5_cost_latency.svg'}`",
    ]
    return "\n".join(lines) + "\n"


def demo_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    questions = [
        {"id": "demo_q1", "split": "test", "topic": "hypertension", "difficulty": "easy", "question_type": "guideline", "gold_source_ids": ["pmid:gold1"]},
        {"id": "demo_q2", "split": "test", "topic": "lipids", "difficulty": "medium", "question_type": "mechanism", "gold_source_ids": ["pmid:gold2"]},
        {"id": "demo_q3", "split": "stress", "topic": "hypertension", "difficulty": "hard", "question_type": "insufficient", "gold_source_ids": ["pmid:gold3"]},
    ]
    runs = []
    judge_scores = []
    base_score = {"A": 2.4, "B": 3.1, "C": 3.7, "D": 3.8, "E": 2.8}
    for qi, q in enumerate(questions, start=1):
        for condition in ("A", "B", "C", "D", "E"):
            gold = q["gold_source_ids"][0]
            retrieved = [gold, "pmid:other"] if condition in {"B", "C", "D"} else []
            if condition == "E":
                retrieved = ["pmid:other"]
            candidate_ids = [gold, "pmid:other", "pmid:x"] if condition in {"B", "C", "D"} else ["pmid:other", "pmid:x"]
            run_id = f"demo_{q['id']}_{condition}"
            decision = "REFUSE" if q["question_type"] == "insufficient" and condition in {"C", "D"} else "PASS"
            claims = []
            if condition != "A":
                claims = [
                    {
                        "claim_id": f"{run_id}_c1",
                        "criticality": "critical",
                        "evidence_ids": [retrieved[0]] if retrieved else [],
                        "decision": "supported" if retrieved and _doc_id(retrieved[0]) == _doc_id(gold) else "unsupported",
                    },
                    {
                        "claim_id": f"{run_id}_c2",
                        "criticality": "important",
                        "evidence_ids": [retrieved[0]] if retrieved else [],
                        "decision": "supported" if retrieved and _doc_id(retrieved[0]) == _doc_id(gold) else "pending",
                    },
                ]
            runs.append(
                {
                    "run_id": run_id,
                    "question_id": q["id"],
                    "condition": condition,
                    "candidate_ids": candidate_ids,
                    "retrieved_evidence": [{"id": x} for x in retrieved],
                    "claims": claims,
                    "verification_decision": decision,
                    "answer": f"demo answer {condition} {q['id']} " * (8 + qi + len(condition)),
                    "latency_ms": 800 + qi * 100 + ord(condition) % 7 * 30,
                    "input_tokens": 500 + qi * 10,
                    "output_tokens": 220 + qi * 8,
                    "estimated_cost": round(0.002 * qi + 0.001 * len(condition), 6),
                }
            )
            for judge_id, jitter in (("judge1", -0.05), ("judge2", 0.05)):
                judge_scores.append(
                    {
                        "run_id": run_id,
                        "question_id": q["id"],
                        "condition": condition,
                        "judge_id": judge_id,
                        "judge_model": "judge-family-a" if judge_id == "judge1" else "judge-family-b",
                        "anonymous_label": f"answer_{condition}",
                        "randomization_seed": 1000 + qi,
                        "position": (qi + len(condition) + (1 if judge_id == "judge1" else 2)) % 5 + 1,
                        "citation_count": len(retrieved),
                        "rubric_keypoint_score": base_score[condition] + jitter,
                        "correctness": base_score[condition] + jitter,
                        "faithfulness": base_score[condition] + jitter,
                        "completeness": min(5.0, base_score[condition] + 0.1 + jitter),
                        "relevance": min(5.0, base_score[condition] + 0.2 + jitter),
                    }
                )
    return runs, judge_scores, questions


def run_b5_report(
    runs: list[dict[str, Any]],
    judge_scores: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    out_dir: Path,
    runs_path: str,
    scores_path: str | None,
    metrics: list[str],
    comparisons: list[tuple[str, str]],
    expected_conditions: list[str] | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    _remove_obsolete_outputs(out_dir)
    auto_scores = compute_automatic_scores(runs, questions)
    combined_scores = merge_auto_and_judge_scores(auto_scores, judge_scores)
    run_scores = aggregate_run_scores(combined_scores, metrics)
    condition_rows = condition_distribution_rows(run_scores, metrics)
    group_rows = group_means(run_scores, questions, metrics)
    delta_rows = paired_delta_rows(run_scores, questions, metrics, comparisons)
    question_delta_rows = per_question_delta_rows(run_scores, questions, metrics, comparisons)
    comparison_rows = comparison_availability_rows(run_scores, questions, metrics, comparisons)
    counterexamples = counterexample_rows(question_delta_rows)
    citation_rows = citation_macro_micro_rows(run_scores)
    judge_report = judge_audit(judge_scores, run_scores, metrics)
    cost_rows = cost_latency_rows(run_scores)
    condition_summary = expected_condition_summary(expected_conditions or DEFAULT_EXPECTED_CONDITIONS, run_scores)

    limitations = []
    if not judge_scores:
        limitations.append("No judge score file was provided, so faithfulness/correctness/completeness/relevance are unavailable unless present in runs.")
    if any(not q.get("gold_source_ids") for q in questions):
        limitations.append("Some questions have no gold_source_ids; retrieval metrics for those questions are omitted instead of scored as zero.")
    if "A2" in condition_summary["missing"]:
        limitations.append("A2 was not run; A2-A is marked missing and not used for conclusions.")
    if any((left, right) in STRESS_COMPARISONS for left, right in comparisons) and not any(_is_stress_question(q) for q in questions):
        limitations.append("E-C was requested but no STRESS split questions were found, so the MD-required stress-only comparison is unavailable.")

    save_jsonl(str(out_dir / "b5_auto_scores.jsonl"), auto_scores, mode="w")
    _write_csv(
        out_dir / "b5_condition_distribution.csv",
        condition_rows,
        ["metric", "condition", "n", "mean", "median", "sd", "min", "max"],
    )
    _write_csv(out_dir / "b5_group_means.csv", group_rows, ["group", "value", "metric", "condition", "n", "mean"])
    _write_csv(
        out_dir / "b5_comparison_availability.csv",
        comparison_rows,
        ["comparison", "metric", "scope", "eligible_questions", "paired_questions", "missing_left_condition", "missing_right_condition", "status"],
    )
    _write_csv(
        out_dir / "b5_paired_deltas.csv",
        delta_rows,
        ["metric", "comparison", "scope", "better_when", "favored_condition", "n_pairs", "mean_delta", "ci95_low", "ci95_high", "permutation_p", "holm_p", "wins", "losses", "ties"],
    )
    _write_csv(
        out_dir / "b5_question_deltas.csv",
        question_delta_rows,
        ["question_id", "question_type", "topic", "difficulty", "split", "metric", "comparison", "scope", "left_condition", "right_condition", "left_score", "right_score", "delta", "better_when", "right_condition_better"],
    )
    _write_csv(
        out_dir / "b5_counterexamples.csv",
        counterexamples,
        ["question_id", "question_type", "topic", "difficulty", "split", "metric", "comparison", "scope", "left_condition", "right_condition", "left_score", "right_score", "delta", "better_when", "right_condition_better", "counterexample_type"],
    )
    _write_csv(
        out_dir / "b5_citation_rollup.csv",
        citation_rows,
        ["metric", "condition", "macro_mean", "micro_mean", "micro_numerator", "micro_denominator", "micro_status"],
    )
    _write_json(out_dir / "b5_judge_audit.json", judge_report)
    _write_csv(
        out_dir / "b5_cost_latency.csv",
        cost_rows,
        ["condition", "n", "mean_latency_ms", "total_input_tokens", "total_output_tokens", "total_cost", "mean_cost"],
    )
    write_charts(out_dir, condition_rows, delta_rows, question_delta_rows, cost_rows)

    markdown = make_markdown_report_v2(
        out_dir,
        runs_path,
        scores_path,
        condition_summary,
        condition_rows,
        delta_rows,
        comparison_rows,
        citation_rows,
        judge_report,
        cost_rows,
        counterexamples,
        limitations,
    )
    _write_text(out_dir / "b5_report.md", markdown)
    summary = {
        "expected_conditions": condition_summary,
        "condition_distribution": condition_rows,
        "group_means": group_rows,
        "comparison_availability": comparison_rows,
        "paired_deltas": delta_rows,
        "question_deltas": question_delta_rows,
        "counterexamples": counterexamples,
        "citation_rollup": citation_rows,
        "judge_audit": judge_report,
        "cost_latency": cost_rows,
        "limitations": limitations,
        "out_dir": str(out_dir),
    }
    _write_json(out_dir / "b5_summary.json", summary)
    return summary


def main() -> None:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="B5 automated metrics, paired statistics, and judge audit")
    parser.add_argument("--runs", default=None, help="Run JSONL from evaluation.experiment")
    parser.add_argument("--scores", default=None, help="Optional judge Score JSONL")
    parser.add_argument("--questions", default=str(cfg.path("questions_formal")), help="Question JSONL")
    parser.add_argument("--questions-stress", default=None,
                        help="STRESS 压力题 JSONL（默认取 config questions_stress；用于 E-C 仅压力集对比）")
    parser.add_argument("--out-dir", default=str(cfg.path("artifacts") / "b5"), help="Output directory")
    parser.add_argument("--metrics", nargs="+", default=DEFAULT_METRICS)
    parser.add_argument("--comparisons", default=None, help="Comma list like A:B,B:C,C:D,C:E,A:A2")
    parser.add_argument("--expected-conditions", default="A,A2,B,C,D,E")
    parser.add_argument("--demo", action="store_true", help="Use deterministic demo inputs")
    args = parser.parse_args()

    if args.demo:
        runs, judge_scores, questions = demo_records()
        out_dir = Path(args.out_dir).resolve()
        runs_path = str(out_dir / "demo_runs.jsonl")
        scores_path = str(out_dir / "demo_scores.jsonl")
        questions_path = str(out_dir / "demo_questions.jsonl")
        save_jsonl(runs_path, runs, mode="w")
        save_jsonl(scores_path, judge_scores, mode="w")
        save_jsonl(questions_path, questions, mode="w")
    else:
        if not args.runs:
            raise SystemExit("Missing --runs. Automated metrics are computed from Run records.")
        runs = load_jsonl(args.runs)
        judge_scores = load_jsonl(args.scores) if args.scores else []
        questions = _load_questions_with_stress(args.questions, args.questions_stress, cfg)
        runs_path = args.runs
        scores_path = args.scores
        out_dir = Path(args.out_dir).resolve()

    summary = run_b5_report(
        runs=runs,
        judge_scores=judge_scores,
        questions=questions,
        out_dir=out_dir,
        runs_path=runs_path,
        scores_path=scores_path,
        metrics=args.metrics,
        comparisons=parse_comparisons(args.comparisons),
        expected_conditions=[x.strip() for x in args.expected_conditions.split(",") if x.strip()],
    )
    print(f"B5 report complete -> {summary['out_dir']}")
    print(f"  auto scores:      {out_dir / 'b5_auto_scores.jsonl'}")
    print(f"  condition table:  {out_dir / 'b5_condition_distribution.csv'}")
    print(f"  availability:     {out_dir / 'b5_comparison_availability.csv'}")
    print(f"  paired deltas:    {out_dir / 'b5_paired_deltas.csv'}")
    print(f"  question deltas:  {out_dir / 'b5_question_deltas.csv'}")
    print(f"  counterexamples:  {out_dir / 'b5_counterexamples.csv'}")
    print(f"  citation rollup:  {out_dir / 'b5_citation_rollup.csv'}")
    print(f"  judge audit:      {out_dir / 'b5_judge_audit.json'}")
    print(f"  markdown report:  {out_dir / 'b5_report.md'}")


if __name__ == "__main__":
    main()
