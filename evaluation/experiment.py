"""一键实验运行器：A/A2/B/C/D（可选 E）批量跑题，随机条件顺序 + 全量 JSONL 留痕

用法：
  python -m evaluation.experiment                     # 正式题 12 道 × A/B/C/D
  python -m evaluation.experiment --questions dev8    # 开发题
  python -m evaluation.experiment --conditions A A2 B C D   # 含 A2 通用搜索对照
  python -m evaluation.experiment --include-a2        # 按 config.yaml a2.enabled 自动加入 A2
  python -m evaluation.experiment --limit 2           # 只跑前 2 道（冒烟测试）

每个 Run 记录（B3 重试与成本日志）：
  config_hash / dataset_version / corpus_version / index_version /
  seed / replicate / provider_fingerprint / attempt_count / cache_hits / status
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import time
import uuid
from pathlib import Path

from core.config import Config, load_config
from core.dataclasses import Question, Run, load_jsonl, save_jsonl
from core.llm import LLMClient
from evaluation.baseline import run_condition
from retrieval.index import EvidenceStore


def compute_config_hash(cfg: Config) -> str:
    """配置版本哈希：config.yaml 内容 sha1 + git commit（存在时）。"""
    h = hashlib.sha1()
    h.update((cfg.root / "config.yaml").read_bytes())
    digest = h.hexdigest()[:12]
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, cwd=cfg.root, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            digest += f"-{out.stdout.strip()}"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return digest


def resolve_conditions(cfg: Config, args) -> list[str]:
    """确定条件列表：CLI 显式传入优先；--include-a2 或 a2.enabled 时自动加入 A2。"""
    conds = list(args.conditions or cfg["evaluation"]["conditions"])
    include_a2 = args.include_a2 or cfg.get("a2", {}).get("enabled", False)
    if include_a2 and "A2" not in conds:
        conds.append("A2")
    if not conds:
        raise ValueError("条件列表为空")
    return conds


def load_questions(path: str, limit: int | None = None) -> list[Question]:
    qs = [Question.from_dict(d) for d in load_jsonl(path)]
    if limit:
        qs = qs[:limit]
    return qs


def run_experiment(cfg: Config, questions: list[Question], conditions: list[str],
                   store: EvidenceStore | None, seed: int = 42,
                   verbose: bool = False, tag: str = "",
                   replicate: int = 1) -> list[Run]:
    llm = LLMClient(cfg["llm"])
    runs: list[Run] = []
    ts = time.strftime("%Y%m%d_%H%M%S")
    runs_path = cfg.path("runs_dir") / f"runs_{tag or ts}.jsonl"
    config_hash = compute_config_hash(cfg)
    dataset_version = cfg.get("config_version", "v0.1.0")
    provider_fingerprint = f"{llm.base_url}/{llm.model}"
    model_snapshot = cfg["llm"].get("model_snapshot") or llm.model

    rng = random.Random(seed)
    for q in questions:
        cond_order = list(conditions)
        rng.shuffle(cond_order)   # 每道题条件顺序随机（公平性要求）
        for cond in cond_order:
            t0 = time.time()
            run_id = f"run_{uuid.uuid4().hex[:10]}"
            try:
                run = run_condition(q, cond, cfg, store=store, llm=llm, verbose=verbose)
                run.status = "ok"
            except Exception as e:  # 失败不静默丢弃，写入 error + status=error
                run = Run(question_id=q.id, condition=cond, model=llm.model,
                          error=f"{type(e).__name__}: {e}",
                          status="error", attempt_count=llm.retries)
            run.run_id = run_id
            run.latency_ms = run.latency_ms or int((time.time() - t0) * 1000)
            run.seed = seed
            run.replicate = replicate
            run.config_hash = config_hash
            run.dataset_version = dataset_version
            run.provider_fingerprint = provider_fingerprint
            run.model_snapshot = model_snapshot
            if store is not None:
                run.corpus_version = run.corpus_version or store.corpus_version
            runs.append(run)
            print(f"[{run.condition}] {q.id} -> {run.verification_decision} "
                  f"({run.latency_ms}ms, cost=${run.estimated_cost:.4f}, "
                  f"err={'Y' if run.error else 'N'}, cache={run.cache_hits})")
            save_jsonl(str(runs_path), [run.to_dict()])

    print(f"\n全部完成: {len(runs)} runs -> {runs_path}")
    return runs


def main() -> None:
    ap = argparse.ArgumentParser(description="赛道3 实验运行器（B3 基线与批量运行）")
    ap.add_argument("--questions", choices=["dev8", "formal12"], default="formal12")
    ap.add_argument("--conditions", nargs="+", default=None,
                    help="默认取 config evaluation.conditions；可显式传 A A2 B C D")
    ap.add_argument("--include-a2", action="store_true",
                    help="把 A2 通用搜索对照加入条件列表（或用 config a2.enabled=true）")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 道题（冒烟）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--replicate", type=int, default=1, help="REPEAT 子集重复序号")
    ap.add_argument("--no-retrieval", action="store_true", help="只跑 A（无证据库）")
    ap.add_argument("--tag", default="", help="输出文件名标签")
    ap.add_argument("--emb-backend", default=None,
                    help="覆盖 embedding 后端: api|local|fallback")
    args = ap.parse_args()

    cfg = load_config()
    q_path = cfg.path("questions_dev" if args.questions == "dev8" else "questions_formal")
    questions = load_questions(str(q_path), limit=args.limit)

    store = None
    if not args.no_retrieval:
        store = EvidenceStore(cfg)
        store.load().build_index(emb_backend=args.emb_backend)
        print(f"索引版本: {store.index_version}  语料版本: {store.corpus_version}  "
              f"证据数: {len(store.evidences)}")

    conditions = resolve_conditions(cfg, args)
    print(f"条件列表: {conditions}")

    run_experiment(cfg, questions, conditions, store=store,
                   seed=args.seed, tag=args.tag, replicate=args.replicate)


if __name__ == "__main__":
    main()
