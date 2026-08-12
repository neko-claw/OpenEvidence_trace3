from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent.parent


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _mean(values: Iterable[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    return round(sum(usable) / len(usable), 6) if usable else None


def _fraction(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def load_qrels(path: Path, relevance_threshold: int) -> dict[str, dict[str, dict[str, Any]]]:
    qrels: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in load_jsonl(path):
        question_id = row["question_id"]
        evidence_id = row["evidence_id"]
        existing = qrels[question_id].get(evidence_id)
        if existing is None or row.get("relevance_grade", 0) > existing.get("relevance_grade", 0):
            qrels[question_id][evidence_id] = {
                "relevance_grade": row.get("relevance_grade", 0),
                "relevant": row.get("relevance_grade", 0) >= relevance_threshold,
                "atomic_point_ids": [],
                "stances": [],
            }
        item = qrels[question_id][evidence_id]
        atomic_point_id = row.get("atomic_point_id")
        if atomic_point_id and atomic_point_id not in item["atomic_point_ids"]:
            item["atomic_point_ids"].append(atomic_point_id)
        stance = row.get("stance")
        if stance and stance not in item["stances"]:
            item["stances"].append(stance)
    return dict(qrels)


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("evidence_id")) for item in items if item.get("evidence_id")]


def evaluate_pair(
    question_id: str,
    condition: str,
    retrieval: dict[str, Any],
    run: dict[str, Any] | None,
    qrels: dict[str, dict[str, dict[str, Any]]],
    top_k: int,
) -> dict[str, Any]:
    qrel_items = qrels.get(question_id, {})
    relevant_ids = {evidence_id for evidence_id, item in qrel_items.items() if item["relevant"]}
    # 各阶段候选：Recall@50/hit@5/mrr 统一以“检索阶段融合候选”（RRF，K0≤100）为口径，
    # 对应实施规划 §4.3.1 的初检候选集；各单路（bm25/vector/rrf）指标单独保留用于消融。
    candidates = (
        retrieval.get("rrf_candidates")
        or retrieval.get("bm25_candidates")
        or retrieval.get("rerank_candidates")
        or []
    )
    candidate_ids = _ids(candidates)
    bm25_ids = _ids(retrieval.get("bm25_candidates") or [])
    vector_ids = _ids(retrieval.get("vector_candidates") or [])
    rrf_ids = _ids(retrieval.get("rrf_candidates") or candidates)
    rerank_candidates = retrieval.get("rerank_candidates") or candidates
    rerank_ids = _ids(rerank_candidates)
    final_items = (run or {}).get("retrieved_evidence") or retrieval.get("final_evidence") or []
    final_ids = _ids(final_items)
    top5 = set(candidate_ids[:5])
    top10 = set(candidate_ids[:10])
    top50 = set(candidate_ids[:50])
    bm25_top50 = set(bm25_ids[:50])
    vector_top50 = set(vector_ids[:50])
    rrf_top50 = set(rrf_ids[:50])
    hit5 = bool(top5 & relevant_ids) if relevant_ids else None
    hit10 = bool(top10 & relevant_ids) if relevant_ids else None
    recall50 = _fraction(len(top50 & relevant_ids), len(relevant_ids)) if relevant_ids else None
    bm25_recall50 = _fraction(len(bm25_top50 & relevant_ids), len(relevant_ids)) if relevant_ids else None
    vector_recall50 = _fraction(len(vector_top50 & relevant_ids), len(relevant_ids)) if relevant_ids else None
    rrf_recall50 = _fraction(len(rrf_top50 & relevant_ids), len(relevant_ids)) if relevant_ids else None
    first_rank = next(
        (rank for rank, evidence_id in enumerate(candidate_ids, start=1) if evidence_id in relevant_ids),
        None,
    )
    mrr = 1 / first_rank if first_rank else (None if relevant_ids else None)
    bm25_first_rank = next(
        (rank for rank, evidence_id in enumerate(bm25_ids, start=1) if evidence_id in relevant_ids),
        None,
    )
    vector_first_rank = next(
        (rank for rank, evidence_id in enumerate(vector_ids, start=1) if evidence_id in relevant_ids),
        None,
    )
    rrf_first_rank = next(
        (rank for rank, evidence_id in enumerate(rrf_ids, start=1) if evidence_id in relevant_ids),
        None,
    )
    bm25_mrr = 1 / bm25_first_rank if bm25_first_rank else (None if relevant_ids else None)
    vector_mrr = 1 / vector_first_rank if vector_first_rank else (None if relevant_ids else None)
    rrf_mrr = 1 / rrf_first_rank if rrf_first_rank else (None if relevant_ids else None)
    rerank_hit5 = bool(set(rerank_ids[:5]) & relevant_ids) if relevant_ids else None
    rerank_hit10 = bool(set(rerank_ids[:10]) & relevant_ids) if relevant_ids else None
    rerank_first_rank = next(
        (rank for rank, evidence_id in enumerate(rerank_ids, start=1) if evidence_id in relevant_ids),
        None,
    )
    rerank_mrr = 1 / rerank_first_rank if rerank_first_rank else (None if relevant_ids else None)
    final_gold_ids = [evidence_id for evidence_id in final_ids if evidence_id in relevant_ids]
    final_recall = _fraction(len(set(final_gold_ids)), len(relevant_ids)) if relevant_ids else None
    source_types = sorted({
        str(item.get("source_type") or "unknown")
        for item in final_items
        if item.get("evidence_id")
    })
    final_source_count = len(source_types)
    failure_class = "no_qrels"
    if relevant_ids:
        if not top50.intersection(relevant_ids):
            failure_class = "not_recalled_in_top50"
        elif not final_gold_ids:
            failure_class = "recalled_but_not_in_final_context"
        else:
            failure_class = "gold_in_final_context"

    stress_manifest = (run or {}).get("stress_manifest")
    return {
        "question_id": question_id,
        "condition": condition,
        "run_id": (run or {}).get("run_id"),
        "run_status": (run or {}).get("status"),
        "split": (run or {}).get("split"),
        "gold_count": len(relevant_ids),
        "gold_ids": sorted(relevant_ids),
        "candidate_count": len(candidate_ids),
        "candidate_ids_top50": candidate_ids[:50],
        "gold_ranks": {
            evidence_id: (candidate_ids.index(evidence_id) + 1 if evidence_id in candidate_ids else None)
            for evidence_id in sorted(relevant_ids)
        },
        "rerank_gold_ranks": {
            evidence_id: (rerank_ids.index(evidence_id) + 1 if evidence_id in rerank_ids else None)
            for evidence_id in sorted(relevant_ids)
        },
        "hit_at_5": hit5,
        "hit_at_10": hit10,
        "recall_at_50": recall50,
        "mrr": round(mrr, 6) if mrr is not None else None,
        "bm25_recall_at_50": bm25_recall50,
        "vector_recall_at_50": vector_recall50,
        "rrf_recall_at_50": rrf_recall50,
        "bm25_mrr": round(bm25_mrr, 6) if bm25_mrr is not None else None,
        "vector_mrr": round(vector_mrr, 6) if vector_mrr is not None else None,
        "rrf_mrr": round(rrf_mrr, 6) if rrf_mrr is not None else None,
        "rerank_hit_at_5": rerank_hit5,
        "rerank_hit_at_10": rerank_hit10,
        "rerank_mrr": round(rerank_mrr, 6) if rerank_mrr is not None else None,
        "final_context_ids": final_ids,
        "final_gold_ids": final_gold_ids,
        "final_context_gold_hit": bool(final_gold_ids) if relevant_ids else None,
        "final_context_recall": final_recall,
        "final_source_types": source_types,
        "final_source_count": final_source_count,
        "failure_class": failure_class,
        "stress_manifest": stress_manifest,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_condition[row["condition"]].append(row)
    summary: dict[str, Any] = {}
    for condition, condition_rows in sorted(by_condition.items()):
        evaluated = [row for row in condition_rows if row["gold_count"] > 0]
        summary[condition] = {
            "run_count": len(condition_rows),
            "evaluated_questions": len(evaluated),
            "no_qrels_questions": sum(row["gold_count"] == 0 for row in condition_rows),
            "hit_at_5": _mean(row["hit_at_5"] for row in evaluated),
            "hit_at_10": _mean(row["hit_at_10"] for row in evaluated),
            "recall_at_50": _mean(row["recall_at_50"] for row in evaluated),
            "mrr": _mean(row["mrr"] for row in evaluated),
            "bm25_recall_at_50": _mean(row["bm25_recall_at_50"] for row in evaluated),
            "vector_recall_at_50": _mean(row["vector_recall_at_50"] for row in evaluated),
            "rrf_recall_at_50": _mean(row["rrf_recall_at_50"] for row in evaluated),
            "bm25_mrr": _mean(row["bm25_mrr"] for row in evaluated),
            "vector_mrr": _mean(row["vector_mrr"] for row in evaluated),
            "rrf_mrr": _mean(row["rrf_mrr"] for row in evaluated),
            "rerank_hit_at_5": _mean(row["rerank_hit_at_5"] for row in evaluated),
            "rerank_hit_at_10": _mean(row["rerank_hit_at_10"] for row in evaluated),
            "rerank_mrr": _mean(row["rerank_mrr"] for row in evaluated),
            "final_context_gold_hit_rate": _mean(row["final_context_gold_hit"] for row in evaluated),
            "final_context_recall": _mean(row["final_context_recall"] for row in evaluated),
            "average_final_source_count": _mean(row["final_source_count"] for row in condition_rows),
            "failure_counts": {
                failure: sum(row["failure_class"] == failure for row in condition_rows)
                for failure in sorted({row["failure_class"] for row in condition_rows})
            },
            "status_counts": {
                status: sum(row["run_status"] == status for row in condition_rows)
                for status in sorted({row["run_status"] for row in condition_rows})
            },
        }
    return summary


def markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# B4 检索基线评测报告",
        "",
        f"- 检索轨迹：`{payload['retrieval_file']}`",
        f"- 运行记录：`{payload['run_file']}`",
        f"- qrels：`{payload['qrels_file']}`",
        f"- 相关性阈值：`{payload['relevance_threshold']}`（relevance_grade >= threshold）",
        "",
        "## 汇总",
        "",
        "| 条件 | 题数 | BM25 Recall@50 | Vector Recall@50 | RRF Recall@50 | Rerank Hit@5 | 最终 Gold 命中率 | 最终 Recall |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for condition, metrics in payload["summary"].items():
        def display(key: str) -> str:
            value = metrics.get(key)
            return "-" if value is None else f"{value:.3f}"

        lines.append(
            f"| {condition} | {metrics['evaluated_questions']} | {display('bm25_recall_at_50')} | "
            f"{display('vector_recall_at_50')} | {display('rrf_recall_at_50')} | "
            f"{display('rerank_hit_at_5')} | {display('final_context_gold_hit_rate')} | "
            f"{display('final_context_recall')} |"
        )
    lines.extend([
        "",
        "## 逐题诊断",
        "",
        "| 条件 | 题目 | Gold 数 | 首个 Gold 排名 | Hit@5 | Recall@50 | 最终 Gold | 诊断分类 |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ])
    for row in payload["per_question"]:
        first_rank = next((rank for rank in row["gold_ranks"].values() if rank is not None), None)
        recall_display = "-" if row["recall_at_50"] is None else f"{row['recall_at_50']:.3f}"
        lines.append(
            f"| {row['condition']} | {row['question_id']} | {row['gold_count']} | "
            f"{first_rank if first_rank is not None else '-'} | "
            f"{'-' if row['hit_at_5'] is None else ('是' if row['hit_at_5'] else '否')} | "
            f"{recall_display} | "
            f"{', '.join(row['final_gold_ids']) if row['final_gold_ids'] else '-'} | "
            f"{row['failure_class']} |"
        )
    lines.extend([
        "",
        "## 解释",
        "",
        "- `Recall@50` / `Hit@5` / `MRR` 以检索阶段融合候选集（BM25+Vector+RRF，K0≤100）为口径，观察初检是否召回 qrels 相关证据；分阶段指标（bm25/vector/rrf）用于消融对比。",
        "- `最终上下文 Gold 命中率` 观察证据是否真正进入生成上下文；E 条件使用劣化后的运行记录。",
        "- `not_recalled_in_top50` 是检索问题；`recalled_but_not_in_final_context` 是候选到上下文选择问题。",
        "- 自动指标只用于回归诊断，不替代医学证据的人工核验。",
        "",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="评估 B4 检索轨迹与最终上下文")
    parser.add_argument("--retrieval", required=True, help="retrieval-*.jsonl")
    parser.add_argument("--runs", required=True, help="runs-*.jsonl")
    parser.add_argument("--qrels", default="data/fixtures/qrels.jsonl")
    parser.add_argument("--output-dir", default="artifacts/b4")
    parser.add_argument("--relevance-threshold", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    retrieval_path = ROOT / args.retrieval
    run_path = ROOT / args.runs
    qrels_path = ROOT / args.qrels
    output_dir = ROOT / args.output_dir
    qrels = load_qrels(qrels_path, args.relevance_threshold)
    runs = {row["run_id"]: row for row in load_jsonl(run_path)}
    per_question: list[dict[str, Any]] = []
    for trace in load_jsonl(retrieval_path):
        retrieval = trace.get("retrieval", {})
        run = runs.get(trace.get("run_id"))
        if run is None:
            continue
        per_question.append(
            evaluate_pair(
                question_id=retrieval["question_id"],
                condition=trace.get("condition", "unknown"),
                retrieval=retrieval,
                run=run,
                qrels=qrels,
                top_k=50,
            )
        )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = {
        "report_version": "retrieval-eval-v0.2",
        "created_at": timestamp,
        "retrieval_file": str(retrieval_path.relative_to(ROOT)),
        "run_file": str(run_path.relative_to(ROOT)),
        "qrels_file": str(qrels_path.relative_to(ROOT)),
        "relevance_threshold": args.relevance_threshold,
        "per_question": per_question,
        "summary": summarize(per_question),
    }
    json_path = output_dir / f"retrieval-eval-{timestamp}.json"
    markdown_path = output_dir / f"retrieval-eval-{timestamp}.md"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(markdown_report(payload), encoding="utf-8")
    print(json.dumps({
        "json_report": str(json_path.relative_to(ROOT)),
        "markdown_report": str(markdown_path.relative_to(ROOT)),
        "trace_count": len(per_question),
        "summary": payload["summary"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
