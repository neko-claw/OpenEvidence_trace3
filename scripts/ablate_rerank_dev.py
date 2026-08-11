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
    "rrf_direct": {"use_rerank": False},
    "semantic_only": {
        "weights": {
            "semantic": 1.0, "lexical": 0.0, "pico_match": 0.0,
            "evidence_level": 0.0, "freshness": 0.0,
            "source_quality": 0.0, "redundancy": 0.0,
        },
    },
    "relevance_first": {
        "weights": {
            "semantic": 0.8, "lexical": 0.2, "pico_match": 0.0,
            "evidence_level": 0.0, "freshness": 0.0,
            "source_quality": 0.0, "redundancy": 0.0,
        },
    },
    "default_no_mmr_penalty": {"mmr_lambda": 1.0},
    "default_mmr": {},
    "default_strong_mmr": {"mmr_lambda": 0.55},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DEV rerank/MMR component ablation")
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
    results = []

    for name, override in VARIANTS.items():
        use_rerank = override.get("use_rerank", True)
        retriever = HybridReferenceRetriever(
            ROOT / args.evidence,
            config_path=ROOT / "config.yaml",
            embedding_backend=args.embedding_backend,
            use_vector=True,
            use_rerank=use_rerank,
            final_k=args.final_k,
        )
        if use_rerank:
            rerank_cfg = copy.deepcopy(retriever.store.cfg.data["rerank"])
            rerank_cfg["weights"].update(override.get("weights", {}))
            if "mmr_lambda" in override:
                rerank_cfg["mmr_lambda"] = override["mmr_lambda"]
            retriever.store.cfg.data["rerank"] = rerank_cfg
            retriever.store._retrieve_cache.clear()

        rows = []
        for question in questions:
            result = retriever.search(question, {"final_k": args.final_k})
            rows.append(evaluate_pair(
                question_id=question["id"],
                condition="C",
                retrieval=result.to_dict(),
                run={
                    "run_id": f"ablation-{name}-{question['id']}",
                    "status": "success",
                    "split": "DEV",
                    "retrieved_evidence": result.final_evidence,
                },
                qrels=qrels,
                top_k=50,
            ))
        results.append({
            "variant": name,
            "use_rerank": use_rerank,
            "override": override,
            "summary": summarize(rows)["C"],
            "per_question": rows,
        })

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"rerank-ablation-dev-{timestamp}.json"
    output_path.write_text(json.dumps({
        "report_version": "rerank-ablation-dev-v0.1",
        "embedding_backend": args.embedding_backend,
        "question_count": len(questions),
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output_path.relative_to(ROOT)),
        "ranking": [
            {
                "variant": item["variant"],
                "rrf_recall_at_50": item["summary"].get("rrf_recall_at_50"),
                "rerank_hit_at_5": item["summary"].get("rerank_hit_at_5"),
                "final_context_gold_hit_rate": item["summary"].get("final_context_gold_hit_rate"),
                "final_context_recall": item["summary"].get("final_context_recall"),
            }
            for item in results
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
