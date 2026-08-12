"""统计：配对差值、bootstrap CI、按题型分组、judge 一致性

用法：
  python -m evaluation.stats --scores data/experiments/scores/scores_xxx.jsonl
"""
from __future__ import annotations

import argparse
import random
from collections import defaultdict

import numpy as np

from core.config import load_config
from core.dataclasses import load_jsonl
from evaluation.questions import load_question_records


def _metric(s: dict, key: str) -> float | None:
    v = s.get(key)
    return float(v) if v is not None else None


def paired_deltas(scores: list[dict], metric: str, c1: str, c2: str) -> list[float]:
    """按题配对：score(c2) - score(c1)"""
    by_q: dict[str, dict[str, float]] = defaultdict(dict)
    for s in scores:
        by_q[s["question_id"]][s["condition"]] = _metric(s, metric)
    deltas = []
    for qid, conds in by_q.items():
        if c1 in conds and c2 in conds and conds[c1] is not None and conds[c2] is not None:
            deltas.append(conds[c2] - conds[c1])
    return deltas


def bootstrap_ci(deltas: list[float], n_boot: int = 2000, seed: int = 42,
                 alpha: float = 0.05) -> tuple[float, float]:
    """bootstrap 均值置信区间（n=12 小样本不用 t 分布过度断言）"""
    if not deltas:
        return (0.0, 0.0)
    rng = random.Random(seed)
    arr = np.array(deltas, dtype=float)
    means = np.empty(n_boot)
    for i in range(n_boot):
        sample = rng.choices(deltas, k=len(deltas))
        means[i] = np.mean(sample)
    lo = np.percentile(means, 100 * alpha / 2)
    hi = np.percentile(means, 100 * (1 - alpha / 2))
    return (float(lo), float(hi))


def mean_by_condition(scores: list[dict], metric: str) -> dict[str, float]:
    agg: dict[str, list[float]] = defaultdict(list)
    for s in scores:
        v = _metric(s, metric)
        if v is not None:
            agg[s["condition"]].append(v)
    return {c: float(np.mean(vs)) for c, vs in agg.items()}


def group_by_type(scores: list[dict], questions: list[dict], metric: str) -> dict:
    qtype = {q["id"]: q.get("question_type", "?") for q in questions}
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for s in scores:
        t = qtype.get(s["question_id"], "?")
        v = _metric(s, metric)
        if v is not None:
            out[t].setdefault(s["condition"], []).append(v)
    return {t: {c: float(np.mean(vs)) for c, vs in cmap.items()} for t, cmap in out.items()}


def judge_agreement(scores: list[dict], metric: str) -> float:
    """同一 run 两个 judge 的相关性（简单版：均方差越小越一致）"""
    by_run: dict[str, list[float]] = defaultdict(list)
    for s in scores:
        v = _metric(s, metric)
        if v is not None:
            by_run[s["run_id"]].append(v)
    pairs = [vs for vs in by_run.values() if len(vs) >= 2]
    if not pairs:
        return float("nan")
    mse = np.mean([(vs[0] - vs[1]) ** 2 for vs in pairs])
    return float(1.0 / (1.0 + mse))   # 0~1，越大越一致


def report(scores: list[dict], questions: list[dict] | None = None) -> str:
    lines = []
    metrics = ["relevance", "correctness", "completeness", "faithfulness",
               "claim_support_rate", "unsupported_claim_rate"]
    lines.append("=== 各条件均值 ===")
    for m in metrics:
        mm = mean_by_condition(scores, m)
        lines.append(f"  {m:24s} " + "  ".join(f"{c}:{v:.3f}" for c, v in sorted(mm.items())))
    lines.append("=== 配对差值 (C-A / B-A / D-C) ===")
    for c1, c2 in [("A", "B"), ("B", "C"), ("C", "D"), ("A", "C")]:
        for m in ["faithfulness", "completeness", "correctness"]:
            d = paired_deltas(scores, m, c1, c2)
            if d:
                lo, hi = bootstrap_ci(d)
                lines.append(f"  {c2}-{c1} {m:16s} mean={np.mean(d):+.3f} 95%CI=[{lo:+.3f},{hi:+.3f}] n={len(d)}")
    lines.append("=== judge 一致性 ===")
    for m in ["faithfulness", "correctness", "completeness"]:
        lines.append(f"  {m}: {judge_agreement(scores, m):.3f}")
    if questions:
        lines.append("=== 按题型分组 (faithfulness) ===")
        for t, cmap in group_by_type(scores, questions, "faithfulness").items():
            lines.append(f"  {t:14s} " + "  ".join(f"{c}:{v:.3f}" for c, v in sorted(cmap.items())))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", required=True)
    ap.add_argument("--questions", default=None,
                    help="题集 .json/.jsonl 路径（默认取 config paths.questions）")
    args = ap.parse_args()
    cfg = load_config()
    scores = load_jsonl(args.scores)
    q_path = args.questions or str(cfg.path("questions"))
    questions = load_question_records(q_path)
    print(report(scores, questions))


if __name__ == "__main__":
    main()
