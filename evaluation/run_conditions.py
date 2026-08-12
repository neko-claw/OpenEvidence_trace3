from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .adapters.a5_retriever import A5EvidenceRetrieverAdapter
from .adapters.a5_system import build_a5_workflow
from .adapters.fixture_retriever import FixtureRetriever
from .adapters.full_system import A5FullSystemAdapter, MockFullSystem
from .adapters.hybrid_retriever import HybridReferenceRetriever
from .adapters.reference_retriever import ReferenceRetriever
from .diagnostics import config_hash, retrieval_trace, write_jsonl
from .runner import run_condition


ROOT = Path(__file__).resolve().parent.parent


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 B4 离线 C/D/E 条件")
    parser.add_argument("--condition", default="C,D,E", help="逗号分隔，例如 C,D,E")
    parser.add_argument(
        "--retriever",
        default="fixture",
        choices=["fixture", "reference", "reference-rerank", "canonical-rerank", "hybrid", "hybrid-rerank"],
    )
    parser.add_argument(
        "--embedding-backend",
        default="fallback",
        choices=["fallback", "local", "api"],
        help="hybrid 检索的 embedding 后端；fallback 仅用于工程链路校验",
    )
    parser.add_argument("--split", default="ALL", choices=["DEV", "STRESS", "ALL"])
    parser.add_argument("--evidence", default="data/fixtures/evidence.jsonl")
    parser.add_argument("--questions", default="data/fixtures/questions.jsonl")
    parser.add_argument("--qrels", default="data/fixtures/qrels.jsonl")
    parser.add_argument("--config", default="configs/conditions.yaml")
    parser.add_argument("--output-dir", default="artifacts/b4")
    parser.add_argument("--initial-k", type=int, default=50, help="保留多少条初检候选，用于 Recall@50 等诊断")
    parser.add_argument("--final-k", type=int, default=4, help="最终放入上下文的证据条数")
    parser.add_argument("--seed", type=int, default=0, help="E 劣化/条件顺序随机种子（确定性复现）")
    parser.add_argument("--replicate", type=int, default=1, help="REPEAT 子集重复序号（写入 RunRecord）")
    parser.add_argument("--full-system", default="mock", choices=["mock", "a5"])
    parser.add_argument("--a5-root", default=None)
    parser.add_argument("--a5-demo", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    evidence_path = ROOT / args.evidence
    questions_path = ROOT / args.questions
    qrels_path = ROOT / args.qrels
    config_path = ROOT / args.config
    output_dir = ROOT / args.output_dir
    config_text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    config = {
        "config_hash": config_hash(config_text),
        "dataset_version": "fixture-v0.1",
        "corpus_version": "fixture-corpus-v0.1",
        "index_version": "fixture-index-v0.1",
        "prompt_version": "prompt-v0.1",
        "seed": args.seed,
        "replicate": args.replicate,
        "initial_k": args.initial_k,
        "final_k": args.final_k,
    }
    questions = load_jsonl(questions_path)
    if args.split != "ALL":
        questions = [q for q in questions if q.get("split") == args.split]
    conditions = [condition.strip().upper() for condition in args.condition.split(",") if condition.strip()]
    if args.retriever in {"reference", "reference-rerank"}:
        retriever = ReferenceRetriever(
            evidence_path,
            index_version=(
                "reference-bm25-rerank-v0.1"
                if args.retriever == "reference-rerank"
                else "reference-bm25-v0.1"
            ),
            rerank=args.retriever == "reference-rerank",
        )
        config["index_version"] = retriever.index_version
    elif args.retriever in {"canonical-rerank", "hybrid", "hybrid-rerank"}:
        retriever = HybridReferenceRetriever(
            evidence_path,
            config_path=ROOT / "config.yaml",
            embedding_backend=args.embedding_backend,
            use_vector=args.retriever != "canonical-rerank",
            use_rerank=True,
            final_k=args.final_k,
        )
        config["index_version"] = retriever.index_version
        config["corpus_version"] = retriever.store.corpus_version
    else:
        retriever = FixtureRetriever(evidence_path, qrels_path, index_version=config["index_version"])

    if args.full_system == "a5":
        if not args.a5_root:
            raise SystemExit("--full-system a5 requires --a5-root")
        a5_root = Path(args.a5_root).resolve()
        if not a5_root.is_dir():
            raise SystemExit(f"A5 root does not exist: {a5_root}")
        if not isinstance(retriever, HybridReferenceRetriever):
            raise SystemExit("--full-system a5 requires --retriever hybrid or hybrid-rerank")
        a5_retriever = A5EvidenceRetrieverAdapter(
            evidence_path,
            a5_root,
            config_path=ROOT / "config.yaml",
            embedding_backend=args.embedding_backend,
            use_rerank=True,
            final_k=args.final_k,
        )
        config["full_system_adapter"] = A5FullSystemAdapter(
            a5_root,
            build_a5_workflow(a5_root, a5_retriever, demo=args.a5_demo),
        )
        config["model"] = "a5-mock-claim-generator"
        config["model_snapshot"] = "a5-mock-claim-generator"
        config["provider_fingerprint"] = "offline/a5-workflow"
        config["a5_demo"] = args.a5_demo
        config["system_version"] = "a5-workflow-v0.1"
    else:
        config["full_system_adapter"] = MockFullSystem()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_path = output_dir / f"runs-{timestamp}.jsonl"
    trace_path = output_dir / f"retrieval-{timestamp}.jsonl"
    stress_path = output_dir / f"stress-{timestamp}.jsonl"
    runs = []
    traces = []
    stresses = []
    for question in questions:
        for condition in conditions:
            run, trace = run_condition(
                question, condition, retriever, config=config,
                conditions_path=str(config_path),
            )
            runs.append(run)
            if trace.get("retrieval") is not None:
                traces.append(retrieval_trace(run.run_id, condition, trace["retrieval"]))
            if trace.get("stress") is not None:
                stresses.append({"run_id": run.run_id, **trace["stress"]})

    write_jsonl(run_path, runs)
    write_jsonl(trace_path, traces)
    write_jsonl(stress_path, stresses)
    summary = {
        "run_file": str(run_path.relative_to(ROOT)),
        "retrieval_file": str(trace_path.relative_to(ROOT)),
        "stress_file": str(stress_path.relative_to(ROOT)),
        "question_count": len(questions),
        "conditions": conditions,
        "run_count": len(runs),
        "status_counts": {
            status: sum(run.status == status for run in runs)
            for status in sorted({run.status for run in runs})
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
