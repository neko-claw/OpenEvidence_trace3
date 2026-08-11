"""图表：配对差值图 + 分组箱线图，导出 PNG

用法：
  python -m evaluation.charts --scores data/experiments/scores/scores_xxx.jsonl
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np

from core.config import load_config
from core.dataclasses import load_jsonl
from evaluation.stats import paired_deltas

# 注册中文字体（优先从 WSL 用户目录 / Windows 借用，找不到时回退 DejaVu）
for _fp in [Path.home() / ".local/share/fonts/msyh.ttc",
            Path.home() / ".local/share/fonts/simhei.ttf",
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")]:
    if _fp.exists():
        try:
            fm.fontManager.addfont(str(_fp))
        except Exception:
            pass
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def paired_delta_chart(scores: list[dict], metric: str, c1: str, c2: str,
                       questions: list[dict], out: Path) -> None:
    by_q = defaultdict(list)
    qtext = {q["id"]: q["question"] for q in questions}
    for s in scores:
        if s.get("metric_ok", True):
            pass
    deltas = []
    labels = []
    by_qid: dict[str, float] = {}
    for s in scores:
        by_qid.setdefault(s["question_id"], {}).update({s["condition"]: s.get(metric)})
    for qid, conds in by_qid.items():
        if conds.get(c1) is not None and conds.get(c2) is not None:
            deltas.append(float(conds[c2]) - float(conds[c1]))
            labels.append(f"{qid}\n{qtext.get(qid, '')[:12]}…")

    fig, ax = plt.subplots(figsize=(10, max(3, len(labels) * 0.5)))
    y = np.arange(len(deltas))
    colors = ["#2e8b57" if d > 0 else "#cd5c5c" for d in deltas]
    ax.barh(y, deltas, color=colors, alpha=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_title(f"配对差值 {c2} - {c1}  (metric: {metric})")
    ax.set_xlabel(f"{c2} 相对 {c1} 的差值")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"保存图表: {out}")


def box_by_condition(scores: list[dict], metric: str, out: Path) -> None:
    conds: dict[str, list[float]] = defaultdict(list)
    for s in scores:
        v = s.get(metric)
        if v is not None:
            conds[s["condition"]].append(float(v))
    fig, ax = plt.subplots(figsize=(8, 5))
    keys = sorted(conds)
    data = [conds[k] for k in keys]
    ax.boxplot(data, tick_labels=keys)
    ax.set_title(f"{metric} 按条件分布")
    ax.set_ylabel(metric)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    print(f"保存图表: {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", required=True)
    ap.add_argument("--questions", default="data/questions/formal12.jsonl")
    args = ap.parse_args()
    cfg = load_config()
    scores = load_jsonl(args.scores)
    questions = load_jsonl(args.questions)
    art = cfg.path("artifacts")
    for metric in ["faithfulness", "completeness", "correctness"]:
        for c1, c2 in [("A", "C"), ("B", "C")]:
            paired_delta_chart(scores, metric, c1, c2, questions,
                               art / f"delta_{metric}_{c2}-{c1}.png")
        box_by_condition(scores, metric, art / f"box_{metric}.png")


if __name__ == "__main__":
    main()
