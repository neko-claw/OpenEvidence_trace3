"""B3 副责：交叉复核 B4 输入一致性与搜索预算审计

审计维度（对应实施规划 §6.2 公平性控制）：
1. 输入一致性：同一 question_id 下 B/C/D（含 A2/A 参与时）的
   model / model_snapshot / prompt_version / index_version / corpus_version /
   config_hash / dataset_version 必须一致；A2 使用通用搜索（index_version=none）。
2. C 候选集同源：C 的最终证据应能回溯到 B 的初检候选集（宽松检查：B 与 C 的
   retrieved_evidence 交集占比，以及 C 的 RRF 排名合理性不做强断言）。
3. E 条件合规：仅出现在 STRESS 压力题；tool_trace 含 degrade 标记；
   劣化候选数应 <= B 基线候选数（top-k 减半规则）。
4. A2 搜索预算：searches_used <= max_searches；results_returned <= max_results_per_search。
5. Run 完整性：每行都有 answer / tokens / cost / status / error 留痕。

用法：
  python -m evaluation.consistency --runs data/experiments/runs/runs_xxx.jsonl \
      --questions data/questions/formal12.jsonl [--strict]
输出：JSON 报告（--out） + 控制台摘要。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

from core.config import load_config
from core.dataclasses import Run, load_jsonl
from evaluation.questions import load_question_records

# 参与配对对比的"检索条件"（引用 / 语料必须一致）
RETRIEVAL_CONDITIONS = ("B", "C", "D", "E")
# 允许的条件全集
KNOWN_CONDITIONS = ("A", "A2", "B", "C", "D", "E")


def _load_runs(path: str) -> list[Run]:
    return [Run.from_dict(d) for d in load_jsonl(path)]


def _load_question_splits(q_path: str | None) -> dict[str, str]:
    """返回 question_id -> split（优先取题集字段；旧 JSONL 按路径是否含 stress 回退）。"""
    if not q_path:
        return {}
    splits: dict[str, str] = {}
    path_text = str(q_path).lower()
    for d in load_question_records(q_path):
        qid = d.get("id", "")
        splits[qid] = str(d.get("split") or (
            "stress" if "stress" in path_text else "test"))
    return splits


def audit_runs(runs: list[Run], q_splits: dict[str, str] | None = None,
               a2_budget: dict | None = None) -> dict:
    """执行一致性审计，返回结构化报告。"""
    q_splits = q_splits or {}
    a2_budget = a2_budget or {}
    max_searches = a2_budget.get("max_searches", 1)
    max_results = a2_budget.get("max_results_per_search", 5)

    issues: list[dict] = []
    by_question: dict[str, dict[str, Run]] = defaultdict(dict)
    for r in runs:
        if r.condition not in KNOWN_CONDITIONS:
            issues.append({"level": "error", "check": "unknown_condition",
                           "question": r.question_id, "run": r.run_id,
                           "detail": f"未知条件 {r.condition}"})
            continue
        by_question[r.question_id][r.condition] = r

    for qid, conds in sorted(by_question.items()):
        # ---- 1. 元数据一致性：同一题的 B/C/D/E 必须同模型/同 prompt/同语料/同索引 ----
        ret_conds = [c for c in RETRIEVAL_CONDITIONS if c in conds]
        if len(ret_conds) >= 2:
            base = conds[ret_conds[0]]
            for c in ret_conds[1:]:
                other = conds[c]
                for field in ("model", "model_snapshot", "prompt_version",
                              "index_version", "corpus_version",
                              "config_hash", "dataset_version"):
                    if getattr(base, field) != getattr(other, field):
                        issues.append({"level": "error", "check": "input_consistency",
                                       "question": qid, "run": other.run_id,
                                       "detail": f"{c} 与 {ret_conds[0]} 的 {field} 不一致: "
                                                 f"{getattr(base, field)!r} vs {getattr(other, field)!r}"})
            # B 与 C 候选集同源（严格模式：C 的最终证据必须 ⊆ B 的 RRF 初检候选）
            if "B" in conds and "C" in conds:
                b_cand = set(conds["B"].candidate_ids)
                c_ids = {e["id"] for e in conds["C"].retrieved_evidence}
                if b_cand and c_ids:
                    outside = c_ids - b_cand
                    if outside:
                        issues.append({"level": "error", "check": "candidate_overlap",
                                       "question": qid,
                                       "detail": f"C 有 {len(outside)} 条证据不在 B 的初检候选集内: "
                                                 f"{sorted(outside)[:3]}"})
                elif c_ids:
                    # 旧 runs 无 candidate_ids 时退化为交集比例检查
                    b_ids = {e["id"] for e in conds["B"].retrieved_evidence}
                    overlap = len(b_ids & c_ids) / len(c_ids) if c_ids else 1.0
                    if overlap < 0.5:
                        issues.append({"level": "warn", "check": "candidate_overlap",
                                       "question": qid,
                                       "detail": f"C 证据与 B 初检候选交集 {overlap:.0%}（<50%），"
                                                 f"建议核对 C 是否复用 B 的同一候选集"})

        # ---- 2. A2 预算审计 ----
        if "A2" in conds:
            a2 = conds["A2"]
            trace = next((t for t in a2.tool_trace if t.get("tool") == "general_search"), {})
            searches = trace.get("searches_used", 0)
            results = trace.get("results_returned", 0)
            if searches > max_searches:
                issues.append({"level": "error", "check": "a2_budget",
                               "question": qid, "run": a2.run_id,
                               "detail": f"A2 搜索次数 {searches} > 预算 {max_searches}"})
            if results > max_results:
                issues.append({"level": "error", "check": "a2_budget",
                               "question": qid, "run": a2.run_id,
                               "detail": f"A2 结果数 {results} > 预算 {max_results}"})
            if not trace.get("snapshot"):
                issues.append({"level": "warn", "check": "a2_snapshot",
                               "question": qid, "run": a2.run_id,
                               "detail": "A2 未记录搜索响应快照"})

        # ---- 3. E 条件合规（仅 STRESS 压力题 + degrade 标记） ----
        if "E" in conds:
            e = conds["E"]
            split = q_splits.get(qid, "")
            if split != "stress":
                issues.append({"level": "warn", "check": "e_split",
                               "question": qid, "run": e.run_id,
                               "detail": f"E 条件出现在非 STRESS 题（split={split or '未知'}）"})
            deg = any(t.get("degraded") for t in e.tool_trace)
            if not deg:
                issues.append({"level": "warn", "check": "e_derivation",
                               "question": qid, "run": e.run_id,
                               "detail": "E 运行无 degrade 标记，无法确认按预注册规则派生"})
            if "B" in conds and e.retrieved_evidence:
                n_e = len(e.retrieved_evidence)
                n_b = len(conds["B"].retrieved_evidence)
                if n_b and n_e >= n_b:
                    issues.append({"level": "warn", "check": "e_derivation",
                                   "question": qid, "run": e.run_id,
                                   "detail": f"E 候选数 {n_e} 未少于 B 基线 {n_b}，"
                                             f"劣化可能未生效"})

        # ---- 4. Run 完整性 ----
        for c, r in conds.items():
            if r.status == "error":
                issues.append({"level": "info", "check": "run_error",
                               "question": qid, "run": r.run_id,
                               "detail": f"{c} 失败: {r.error[:120]}"})
            elif not r.answer and c != "A2":
                issues.append({"level": "warn", "check": "run_incomplete",
                               "question": qid, "run": r.run_id,
                               "detail": f"{c} 无回答文本"})

    # ---- 汇总 ----
    n_runs = len(runs)
    n_issues = len(issues)
    n_error = sum(1 for i in issues if i["level"] == "error")
    n_warn = sum(1 for i in issues if i["level"] == "warn")
    return {
        "audited_runs": n_runs,
        "audited_questions": len(by_question),
        "issues": issues,
        "summary": {
            "errors": n_error,
            "warns": n_warn,
            "infos": n_issues - n_error - n_warn,
            "pass": n_issues == 0,
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="B3 副责：B4 输入一致性 + 搜索预算交叉复核")
    ap.add_argument("--runs", required=True, help="runs JSONL 路径")
    ap.add_argument("--questions", default=None,
                    help="题集 .json/.jsonl 路径（默认取 config paths.questions）")
    ap.add_argument("--out", default=None, help="报告输出 JSON 路径")
    ap.add_argument("--strict", action="store_true", help="存在任何 error 即退出码 1")
    args = ap.parse_args()

    cfg = load_config()
    runs = _load_runs(args.runs)
    q_path = args.questions or str(cfg.path("questions"))
    q_splits = _load_question_splits(q_path)
    report = audit_runs(runs, q_splits, a2_budget=cfg.get("a2", {}))

    s = report["summary"]
    print(f"审计 {report['audited_questions']} 题 / {report['audited_runs']} runs: "
          f"{s['errors']} error, {s['warns']} warn, {s['infos']} info -> "
          f"{'✅ PASS' if s['pass'] else '❌ 发现问题'}")
    for i in report["issues"]:
        print(f"  [{i['level']:>5}] {i['check']}: {i['detail']} (q={i['question']})")

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"报告已保存: {args.out}")

    if args.strict and s["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
