"""LLM judge：匿名 + 双 judge + JSON 输出评分

用法：
  python -m evaluation.judge --runs data/experiments/runs/runs_xxx.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

from core.config import load_config
from core.dataclasses import Question, Score, load_jsonl, save_jsonl
from core.llm import LLMClient
from generation import prompts


def anonymize(runs: list[dict]) -> tuple[list[dict], dict]:
    """匿名：把 A/B/C/D 条件标签随机映射为 ①②③④，记录映射表"""
    rng = random.Random(42)
    per_question: dict[str, dict] = {}
    anon_runs = []
    mapping: dict[str, str] = {}
    for r in runs:
        qid = r["question_id"]
        if qid not in per_question:
            per_question[qid] = {c: f"OPT{chr(0x2460 + i)}" for i, c in enumerate(sorted(set(rr["condition"] for rr in runs if rr["question_id"] == qid)))}
        label = per_question[qid][r["condition"]]
        mapping[(qid, r["condition"])] = label
        anon = dict(r)
        anon["condition_label"] = label
        anon_runs.append(anon)
    return anon_runs, mapping


def judge_run(llm: LLMClient, q: Question, run: dict, judge_id: str,
              model: str | None = None) -> Score:
    msgs = prompts.build_judge_prompt(q, run["answer"], q.rubric)
    obj, meta = llm.chat_json(msgs, temperature=0.0, model=model)
    verdicts = obj.get("verdicts", [])
    n_sup = sum(1 for v in verdicts if v.get("decision") == "supported")
    n_total = len(verdicts)
    return Score(
        run_id=run["run_id"], question_id=q.id, condition=run["condition"],
        judge_id=judge_id,
        metric_version="v0.1",
        rubric_version=(q.rubric or {}).get("rubric_version")
            or q.extras.get("rubric_version", "v0.1"),
        relevance=float(obj.get("relevance", 0) or 0),
        correctness=float(obj.get("correctness", 0) or 0),
        completeness=float(obj.get("completeness", 0) or 0),
        faithfulness=float(obj.get("faithfulness", 0) or 0),
        claim_support_rate=n_sup / n_total if n_total else 0.0,
        unsupported_claim_rate=(n_total - n_sup) / n_total if n_total else 1.0,
        latency_ms=meta["latency_ms"], input_tokens=meta["input_tokens"],
        output_tokens=meta["output_tokens"], estimated_cost=meta["estimated_cost"],
        notes=obj.get("notes", ""),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="runs JSONL 路径")
    ap.add_argument("--questions", default="data/questions/formal12.jsonl")
    ap.add_argument("--judges", nargs="+", default=["judge1", "judge2"],
                    help="judge 数量（多 judge 交叉评分）")
    ap.add_argument("--model", default=None, help="覆盖 judge 模型（建议与生成模型不同）")
    ap.add_argument("--sample", type=float, default=1.0, help="抽样比例（双评抽样）")
    args = ap.parse_args()

    cfg = load_config()
    llm = LLMClient(cfg["llm"])
    model = args.model or cfg["llm"].get("judge_model") or "unknown-judge-family"
    qs = {q["id"]: Question.from_dict(q) for q in load_jsonl(args.questions)}
    raw_runs = load_jsonl(args.runs)

    # 匿名 + 随机展示位置（规划 §6.3：匿名随机、位置偏差审计留痕）
    anon_runs, mapping = anonymize(raw_runs)
    # 记录匿名映射表，供报告追溯（条件 -> 匿名标签）
    mapping_path = cfg.path("artifacts") / "b5" / "judge_anonymize_mapping.json"
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    mapping_path.write_text(json.dumps(
        {f"{k[0]}::{k[1]}": v for k, v in sorted(mapping.items(), key=lambda kv: kv[0])},
        ensure_ascii=False, indent=2), encoding="utf-8")

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = cfg.path("scores_dir") / f"scores_{ts}.jsonl"
    for idx, run in enumerate(anon_runs):
        q = qs.get(run["question_id"])
        if q is None:
            continue
        for judge_id in args.judges:
            # 每题/每 judge 独立随机位置，种子落盘可复现（位置偏差审计）
            rng = random.Random(1000 + idx * 7 + (1 if judge_id == args.judges[0] else 2))
            position = rng.randint(1, 6)
            score = judge_run(llm, q, run, judge_id, model=model)
            score.anonymous_label = run.get("condition_label", "")
            score.position = position
            score.randomization_seed = 1000 + idx * 7 + (1 if judge_id == args.judges[0] else 2)
            score.judge_family = model
            score.citation_count = len(run.get("citations") or [])
            score.displayed_citation_count = score.citation_count
            save_jsonl(str(out_path), [score.to_dict()])
            print(f"{score.condition} {run['question_id']} by {judge_id}: "
                  f"faith={score.faithfulness} comp={score.completeness} "
                  f"corr={score.correctness} rel={score.relevance}")
    print(f"\njudge 评分完成 -> {out_path}（匿名映射: {mapping_path}）")


if __name__ == "__main__":
    main()
