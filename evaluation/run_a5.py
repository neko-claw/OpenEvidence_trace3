"""Run the Track 1 A5 workflow through the unified B4 RunRecord contract."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .adapters.a5_retriever import A5EvidenceRetrieverAdapter
from .adapters.a5_system import build_a5_workflow
from .adapters.full_system import A5FullSystemAdapter
from .adapters.hybrid_retriever import HybridReferenceRetriever
from .diagnostics import config_hash, write_jsonl
from .runner import run_condition


ROOT = Path(__file__).resolve().parent.parent


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run A5 and emit unified B4 RunRecord JSONL")
    parser.add_argument("--a5-root", required=True)
    parser.add_argument("--evidence", default="data/processed/evidence.jsonl")
    parser.add_argument("--questions", default="data/fixtures/questions.jsonl")
    parser.add_argument("--split", default="DEV", choices=["DEV", "STRESS", "ALL"])
    parser.add_argument("--embedding-backend", default="fallback", choices=["fallback", "local", "api"])
    parser.add_argument("--demo", action="store_true", help="Use A5 FixtureSafetyPolicy for offline smoke tests")
    parser.add_argument("--output-dir", default="artifacts/b4")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--replicate", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    a5_root = Path(args.a5_root).resolve()
    if not a5_root.is_dir():
        raise SystemExit(f"A5 root does not exist: {a5_root}")
    questions = load_jsonl(ROOT / args.questions)
    if args.split != "ALL":
        questions = [row for row in questions if row.get("split") == args.split]

    retriever = HybridReferenceRetriever(
        ROOT / args.evidence,
        config_path=ROOT / "config.yaml",
        embedding_backend=args.embedding_backend,
        use_rerank=True,
        final_k=4,
    )
    a5_retriever = A5EvidenceRetrieverAdapter(
        ROOT / args.evidence,
        a5_root,
        config_path=ROOT / "config.yaml",
        embedding_backend=args.embedding_backend,
        use_rerank=True,
        final_k=4,
    )
    workflow = build_a5_workflow(a5_root, a5_retriever, demo=args.demo)
    adapter = A5FullSystemAdapter(a5_root, workflow)

    config_text = (ROOT / "config.yaml").read_text(encoding="utf-8")
    config = {
        "config_hash": config_hash(config_text),
        "dataset_version": "a5-v0.1",
        "corpus_version": retriever.store.corpus_version,
        "index_version": retriever.index_version,
        "prompt_version": "a5-workflow-v0.1",
        "seed": args.seed,
        "replicate": args.replicate,
        "final_k": 4,
        "full_system_adapter": adapter,
        "model": "a5-mock-claim-generator",
        "model_snapshot": "a5-mock-claim-generator",
        "provider_fingerprint": "offline/a5-workflow",
        "a5_demo": args.demo,
        "system_version": "a5-workflow-v0.1",
    }

    rows = []
    retrieval_traces = []
    for question in questions:
        run, trace = run_condition(
            question,
            "D",
            retriever,
            config=config,
            conditions_path=str(ROOT / "configs/conditions.yaml"),
        )
        rows.append(run)
        retrieval_traces.append({
            "run_id": run.run_id,
            "condition": "D",
            "retrieval": trace.get("retrieval"),
        })

    output_dir = ROOT / args.output_dir
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"runs-a5-{timestamp}.jsonl"
    retrieval_path = output_dir / f"retrieval-a5-{timestamp}.jsonl"
    write_jsonl(output_path, rows)
    write_jsonl(retrieval_path, retrieval_traces)
    print(json.dumps({
        "run_file": str(output_path.relative_to(ROOT)),
        "retrieval_file": str(retrieval_path.relative_to(ROOT)),
        "question_count": len(rows),
        "condition": "D",
        "schema": "evaluation.schemas.RunRecord",
        "status_counts": {
            status: sum(row.status == status for row in rows)
            for status in sorted({row.status for row in rows})
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
