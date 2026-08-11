from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .adapters.a5_retriever import A5EvidenceRetrieverAdapter
from .adapters.a5_system import build_a5_workflow


ROOT = Path(__file__).resolve().parent.parent


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B4 调用 A5 answer() 并保存 AgentRun")
    parser.add_argument("--a5-root", required=True)
    parser.add_argument("--evidence", default="data/processed/evidence.jsonl")
    parser.add_argument("--questions", default="data/fixtures/questions.jsonl")
    parser.add_argument("--split", default="DEV", choices=["DEV", "STRESS", "ALL"])
    parser.add_argument("--embedding-backend", default="fallback", choices=["fallback", "local", "api"])
    parser.add_argument("--demo", action="store_true", help="仅离线工程 smoke；使用 A5 FixtureSafetyPolicy")
    parser.add_argument("--output-dir", default="artifacts/b4")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    a5_root = Path(args.a5_root).resolve()
    questions = load_jsonl(ROOT / args.questions)
    if args.split != "ALL":
        questions = [row for row in questions if row.get("split") == args.split]
    retriever = A5EvidenceRetrieverAdapter(
        ROOT / args.evidence,
        a5_root,
        config_path=ROOT / "config.yaml",
        embedding_backend=args.embedding_backend,
        use_rerank=True,
        final_k=4,
    )
    workflow = build_a5_workflow(a5_root, retriever, demo=args.demo)
    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"a5-runs-{timestamp}.jsonl"
    rows = []
    for question in questions:
        metadata = {"track3_question_id": question["id"]}
        if args.demo:
            metadata["mock_safety_decision"] = "ALLOW"
        from a5.api import answer
        from a5.domain.models import Question

        a5_question = Question(question_id=question["id"], text=question["question"], metadata=metadata)
        run = answer(a5_question, workflow=workflow)
        rows.append(run.model_dump(mode="json"))
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps({
        "output": str(output_path.relative_to(ROOT)),
        "question_count": len(rows),
        "demo": args.demo,
        "embedding_backend": args.embedding_backend,
        "decisions": {decision: sum(row.get("decision") == decision for row in rows)
                      for decision in sorted({row.get("decision") for row in rows})},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
