from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.embeddings import EmbeddingClient
from retrieval.mmr import lexical_rescue_select, mmr_select
from retrieval.query_expansion import expand_query
from retrieval.rerank import feature_rerank

from evaluation.adapters.hybrid_retriever import HybridReferenceRetriever
from evaluation.evaluate_retrieval import evaluate_pair, load_jsonl, load_qrels, summarize


ROOT = Path(__file__).resolve().parents[1]


def _weights(base: dict, **updates: float) -> dict:
    result = copy.deepcopy(base)
    result.update(updates)
    return result


def _variants(base_weights: dict) -> dict[str, dict]:
    zero = {
        "lexical": 0.0,
        "pico_match": 0.0,
        "evidence_level": 0.0,
        "freshness": 0.0,
        "source_quality": 0.0,
        "redundancy": 0.0,
    }
    return {
        "default": {},
        "no_pico": {"weights": _weights(base_weights, pico_match=0.0)},
        "no_authority": {"weights": _weights(base_weights, evidence_level=0.0, source_quality=0.0)},
        "no_pico_authority": {"weights": _weights(base_weights, pico_match=0.0, evidence_level=0.0, source_quality=0.0)},
        "rrf_only": {"weights": _weights(base_weights, **zero, semantic=1.0)},
        "bm25_actual": {"lexical_scores": True},
        "bm25_actual_rank_norm": {"lexical_scores": True, "normalize_semantic": True},
        "rank_preserving_small_features": {
            "rank_preserving": True,
            "rank_mix": 0.75,
            "weights": {
                "semantic": 0.78,
                "lexical": 0.0,
                "pico_match": 0.08,
                "evidence_level": 0.05,
                "freshness": 0.03,
                "source_quality": 0.06,
                "redundancy": 0.0,
            },
        },
        "rank_preserving_no_pico": {
            "rank_preserving": True,
            "rank_mix": 0.75,
            "weights": {
                "semantic": 0.82,
                "lexical": 0.0,
                "pico_match": 0.0,
                "evidence_level": 0.08,
                "freshness": 0.04,
                "source_quality": 0.06,
                "redundancy": 0.0,
            },
        },
        "rank_guard_default": {
            "rank_preserving": True,
            "rank_mix": 0.75,
            "weights": copy.deepcopy(base_weights),
        },
        "rank_guard_no_authority": {
            "rank_preserving": True,
            "rank_mix": 0.75,
            "weights": _weights(base_weights, evidence_level=0.0, source_quality=0.0),
        },
        "limited_drop_5": {"max_rank_drop": 5},
        "limited_drop_10": {"max_rank_drop": 10},
        "limited_drop_15": {"max_rank_drop": 15},
        "controlled_rise_015": {"controlled_rise": True, "rise_weight": 0.15, "rise_cutoff": 50},
        "controlled_rise_025": {"controlled_rise": True, "rise_weight": 0.25, "rise_cutoff": 50},
        "controlled_rise_035": {"controlled_rise": True, "rise_weight": 0.35, "rise_cutoff": 50},
        "lexical_rescue_15_015": {
            "lexical_rescue": True, "rescue_cutoff": 15, "rescue_margin": 0.15,
        },
        "lexical_rescue_20_015": {
            "lexical_rescue": True, "rescue_cutoff": 20, "rescue_margin": 0.15,
        },
        "lexical_rescue_20_020": {
            "lexical_rescue": True, "rescue_cutoff": 20, "rescue_margin": 0.20,
        },
    }


def _candidate(store, row: dict, stage: str) -> dict:
    doc_id = row["doc_id"]
    record = store.get(doc_id)
    item = record.to_dict() if record else {"id": doc_id}
    item["evidence_id"] = doc_id
    item["rank"] = row.get("rank")
    item["score"] = row.get("score", row.get("final", 0.0))
    item["retrieval_stage"] = stage
    item.update({k: v for k, v in row.items() if k not in {"doc_id", "rank", "score"}})
    return item


def _run_variant(store, questions, qrels, name, override, final_k):
    base_retrieval = store.cfg.data["retrieval"]
    base_rerank = store.cfg.data["rerank"]
    rows = []
    for question in questions:
        stats = {}
        store.retrieve(
            question["question"],
            use_rerank=False,
            use_vector=True,
            k_final=final_k,
            stats=stats,
            q_freshness=question.get("freshness", "stable"),
        )
        bm25_rows = stats.get("bm25_candidates", [])
        vector_rows = stats.get("vector_candidates", [])
        rrf_rows = stats.get("rrf_candidates", [])
        candidates = [(row["doc_id"], float(row["score"])) for row in rrf_rows]
        weights = copy.deepcopy(override.get("weights", base_rerank["weights"]))
        lexical_scores = None
        if override.get("lexical_scores"):
            lexical_scores = {row["doc_id"]: float(row["score"]) for row in bm25_rows}
        ranked = feature_rerank(
            candidates,
            store.evidences,
            expand_query(question["question"]),
            weights,
            lexical_scores=lexical_scores,
            normalize_semantic=bool(override.get("normalize_semantic", False)),
            rank_preserving=bool(override.get("rank_preserving", False)),
            bm25_ranks={row["doc_id"]: int(row["rank"]) for row in bm25_rows},
            rank_mix=float(override.get("rank_mix", 0.75)),
            max_rank_drop=override.get("max_rank_drop"),
            controlled_rise=bool(override.get("controlled_rise", False)),
            rise_weight=float(override.get("rise_weight", 0.0)),
            rise_cutoff=int(override.get("rise_cutoff", 50)),
            q_freshness=question.get("freshness", "stable"),
        )
        mmr_lambda = float(override.get("mmr_lambda", base_rerank.get("mmr_lambda", 1.0)))
        final_ids = mmr_select(
            ranked,
            store.evidences,
            k_final=final_k,
            lambda_=mmr_lambda,
            max_per_source=base_rerank.get("max_per_source", 4),
            max_per_doc=base_rerank.get("max_per_doc", 2),
        )
        if override.get("lexical_rescue", False):
            final_ids = lexical_rescue_select(
                ranked,
                final_ids,
                {row["doc_id"]: int(row["rank"]) for row in bm25_rows},
                cutoff=int(override.get("rescue_cutoff", 20)),
                margin=float(override.get("rescue_margin", 0.15)),
            )
        final_rows = []
        for rank, doc_id in enumerate(final_ids, 1):
            feature = next(item for item in ranked if item["doc_id"] == doc_id)
            item = _candidate(store, feature, "mmr_selected")
            item["rank"] = rank
            item["feature_score"] = feature["final"]
            final_rows.append(item)
        retrieval = {
            "question_id": question["id"],
            "bm25_candidates": [_candidate(store, row, "bm25") for row in bm25_rows],
            "vector_candidates": [_candidate(store, row, "vector") for row in vector_rows],
            "rrf_candidates": [_candidate(store, row, "rrf") for row in rrf_rows],
            "rerank_candidates": [_candidate(store, row, "feature_rerank") for row in ranked],
            "final_evidence": final_rows,
        }
        rows.append(evaluate_pair(
            question_id=question["id"],
            condition="C",
            retrieval=retrieval,
            run={"run_id": f"component-ablation-{name}-{question['id']}", "status": "success", "split": question.get("split"), "retrieved_evidence": final_rows},
            qrels=qrels,
            top_k=50,
        ))
    return rows


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Rerank 组件消融（R0 RRF-only vs R1 特征+MMR 变体）")
    ap.add_argument("--questions", default="test_set/questions.jsonl",
                    help="题集 JSONL（默认正式主集，取 DEV/STRESS split）")
    ap.add_argument("--qrels", default="test_set/qrels.jsonl")
    ap.add_argument("--emb-backend", default=None, choices=["api", "local", "fallback"],
                    help="覆盖嵌入后端（默认取 config）")
    ap.add_argument("--final-k", type=int, default=4)
    args = ap.parse_args()

    evidence = ROOT / "data/processed/evidence.jsonl"
    questions = load_jsonl(ROOT / args.questions)
    qrels = load_qrels(ROOT / args.qrels, relevance_threshold=1)
    # STRESS 在独立文件（stress_20.jsonl），与主集分开加载
    stress_questions = load_jsonl(ROOT / "test_set/stress_20.jsonl")
    retriever = HybridReferenceRetriever(
        evidence,
        config_path=ROOT / "config.yaml",
        embedding_backend=args.emb_backend or "api",
        use_vector=True,
        use_rerank=False,
        final_k=args.final_k,
    )
    base_weights = copy.deepcopy(retriever.store.cfg.data["rerank"]["weights"])
    variants = _variants(base_weights)
    results = []
    for name, override in variants.items():
        dev = [q for q in questions if str(q.get("split")).lower() == "dev"]
        stress = [q for q in stress_questions]
        dev_rows = _run_variant(retriever.store, dev, qrels, name, override, args.final_k)
        stress_rows = _run_variant(retriever.store, stress, qrels, name, override, args.final_k)
        results.append({
            "variant": name,
            "override": override,
            "dev": summarize(dev_rows)["C"],
            "stress": summarize(stress_rows)["C"],
            "dev_per_question": dev_rows,
            "stress_per_question": stress_rows,
        })

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = ROOT / "artifacts/b4"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"rerank-component-ablation-{timestamp}.json"
    output.write_text(json.dumps({
        "report_version": "rerank-component-ablation-v0.1",
        "embedding_backend": retriever.embedding_backend,
        "questions": str(ROOT / args.questions),
        "qrels": str(ROOT / args.qrels),
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output.relative_to(ROOT)),
        "ranking": [
            {
                "variant": item["variant"],
                "dev_final_hit": item["dev"]["final_context_gold_hit_rate"],
                "dev_final_recall": item["dev"]["final_context_recall"],
                "dev_rerank_hit5": item["dev"].get("rerank_hit_at_5"),
                "stress_rerank_hit5": item["stress"].get("rerank_hit_at_5"),
                "stress_final_hit": item["stress"]["final_context_gold_hit_rate"],
                "stress_final_recall": item["stress"]["final_context_recall"],
            }
            for item in results
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
