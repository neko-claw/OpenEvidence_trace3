from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from evaluation.adapters.hybrid_retriever import HybridReferenceRetriever
from evaluation.evaluate_retrieval import evaluate_pair, load_jsonl, load_qrels, summarize


ROOT = Path(__file__).resolve().parents[1]


VARIANTS = {
    "baseline": {},
    "semantic_high": {
        "weights": {"semantic": 0.45, "lexical": 0.15, "pico_match": 0.10},
    },
    "authority_high": {
        "weights": {"semantic": 0.25, "lexical": 0.15, "evidence_level": 0.25, "source_quality": 0.15},
    },
    "mmr_low": {"mmr_lambda": 0.55},
    "mmr_high": {"mmr_lambda": 0.85},
    "rerank_top30": {"k1_rerank": 30},
    "rerank_top70": {"k1_rerank": 70},
    "rrf_k30": {"rrf_k": 30, "k1_rerank": 50},
    "rrf_k90": {"rrf_k": 90, "k1_rerank": 50},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="仅使用 DEV 调整 Vector+RRF rerank/MMR")
    parser.add_argument("--evidence", default="data/processed/evidence.jsonl")
    parser.add_argument("--questions", default="data/fixtures/questions.jsonl")
    parser.add_argument("--qrels", default="data/fixtures/qrels.jsonl")
    parser.add_argument("--embedding-backend", default="local", choices=["local", "fallback"])
    parser.add_argument("--final-k", type=int, default=4)
    parser.add_argument("--output-dir", default="artifacts/b4")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    questions = [
        row for row in load_jsonl(ROOT / args.questions)
        if row.get("split") == "DEV"
    ]
    qrels = load_qrels(ROOT / args.qrels, relevance_threshold=1)
    retriever = HybridReferenceRetriever(
        ROOT / args.evidence,
        config_path=ROOT / "config.yaml",
        embedding_backend=args.embedding_backend,
        use_vector=True,
        use_rerank=True,
        final_k=args.final_k,
    )
    base_rerank = copy.deepcopy(retriever.store.cfg.data["rerank"])
    base_retrieval = copy.deepcopy(retriever.store.cfg.data["retrieval"])
    # DEV tuning starts with K1=50; K1=30 is tested as an explicit variant.
    if base_retrieval.get("k1_rerank") is None:
        base_retrieval["k1_rerank"] = 50
    results = []
    for name, override in VARIANTS.items():
        rerank_cfg = copy.deepcopy(base_rerank)
        retrieval_cfg = copy.deepcopy(base_retrieval)
        rerank_cfg["weights"].update(override.get("weights", {}))
        if "mmr_lambda" in override:
            rerank_cfg["mmr_lambda"] = override["mmr_lambda"]
        if "k1_rerank" in override:
            retrieval_cfg["k1_rerank"] = override["k1_rerank"]
        if "rrf_k" in override:
            retrieval_cfg["rrf_k"] = override["rrf_k"]
        retriever.store.cfg.data["rerank"] = rerank_cfg
        retriever.store.cfg.data["retrieval"] = retrieval_cfg
        retriever.store._retrieve_cache.clear()
        rows = []
        for question in questions:
            result = retriever.search(question, {"final_k": args.final_k})
            rows.append(evaluate_pair(
                question_id=question["id"],
                condition="C",
                retrieval=result.to_dict(),
                run={
                    "run_id": f"tune-{name}-{question['id']}",
                    "status": "success",
                    "split": "DEV",
                    "retrieved_evidence": result.final_evidence,
                },
                qrels=qrels,
                top_k=50,
            ))
        results.append({
            "variant": name,
            "rerank": rerank_cfg,
            "retrieval": retrieval_cfg,
            "summary": summarize(rows)["C"],
            "per_question": rows,
        })

    results.sort(key=lambda item: (
        item["summary"].get("final_context_gold_hit_rate") or 0,
        item["summary"].get("final_context_recall") or 0,
        item["summary"].get("rrf_recall_at_50") or 0,
    ), reverse=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"rerank-tuning-dev-{timestamp}.json"
    output_path.write_text(json.dumps({
        "report_version": "rerank-tuning-dev-v0.1",
        "embedding_backend": args.embedding_backend,
        "question_count": len(questions),
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output_path.relative_to(ROOT)),
        "ranking": [
            {
                "variant": item["variant"],
                "final_context_gold_hit_rate": item["summary"].get("final_context_gold_hit_rate"),
                "final_context_recall": item["summary"].get("final_context_recall"),
                "rrf_recall_at_50": item["summary"].get("rrf_recall_at_50"),
                "rerank_hit_at_5": item["summary"].get("rerank_hit_at_5"),
            }
            for item in results
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
