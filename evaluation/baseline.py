"""run_condition：单个问题 × 单个条件的完整实验流程

B3 主责：A / A2 / B 三个条件在此实现；C/D/E 由 B4 扩展（E 骨架在本文件，供 B4 按预注册规则重写）。
"""
from __future__ import annotations

from typing import Optional

from core.config import Config
from core.dataclasses import Question, Run
from core.llm import LLMClient
from evaluation.a2_search import search_general
from generation.answer import AnswerGenerator
from retrieval.index import EvidenceStore


def run_condition(q: Question, condition: str, cfg: Config,
                  store: Optional[EvidenceStore] = None,
                  llm: Optional[LLMClient] = None,
                  verbose: bool = False) -> Run:
    """执行一个条件。store 为 None 时视为纯 LLM 条件（A）。

    condition 取值: A | A2 | B | C | D | E
    - A  : 纯 LLM，无检索，不提供证据（B3 主责）
    - A2 : 通用搜索对照，不使用项目 Evidence store，固定搜索预算 + 响应快照（B3 主责，可选）
    - B  : BM25 + 向量 + RRF 后直接取 top-k，无 rerank（B3 主责）
    - C  : B + 特征重排 + MMR（B4）
    - D  : C + Wiki/Agent（B4）
    - E  : 劣化检索（B4 主责）。骨架：在 B 的基线初检候选上按预注册规则派生
           （当前仅实现"top-k 减半"一种扰动；完整扰动集由 B4 读取
           evaluation/preregistration/e_perturbation_rules.json 后重写）
    """
    llm = llm or LLMClient(cfg["llm"])
    gen = AnswerGenerator(cfg, llm)
    run = Run(question_id=q.id, condition=condition, model=llm.model,
              prompt_version=cfg["generation"]["prompt_version"])

    if condition == "A":
        run.index_version = "none"
        run.corpus_version = "none"
        run.agent_plan = ["condition A: closed-book, no retrieval"]
        result, _ = gen.generate(q, condition, [], [])
        result.index_version = "none"
        result.corpus_version = "none"
        result.agent_plan = run.agent_plan
        return result

    if condition == "A2":
        # 通用搜索（不读项目 Evidence store / 索引），预算固定、响应快照落盘
        results, meta = search_general(q.question, cfg)
        run.index_version = "none"
        run.corpus_version = "none"
        run.tool_trace.append({
            "tool": "general_search",
            "provider": meta["provider"],
            "searches_used": meta["searches_used"],
            "results_returned": meta["results_returned"],
            "budget": meta["budget"],
            "simulated": meta["simulated"],
            "search_error": meta["error"],
            "snapshot": meta["snapshot"],
        })
        run.agent_plan = [
            f"condition A2: general search ({meta['provider']}, "
            f"{meta['searches_used']}/{meta['budget']['max_searches']} searches)",
        ]
        result, _ = gen.generate(q, condition, [r.to_dict() for r in results], [])
        result.index_version = "none"
        result.corpus_version = "none"
        result.agent_plan = run.agent_plan
        result.tool_trace = run.tool_trace
        # 搜索成本并入总成本（生成成本由 generate() 已记入）
        result.estimated_cost = round(result.estimated_cost + meta["cost"], 6)
        return result

    if store is None:
        raise ValueError(f"条件 {condition} 需要证据库，请先构建 EvidenceStore")

    # ---- 检索 ----
    stats: dict = {}
    if condition in ("B", "C", "D"):
        top_evs, features = store.retrieve(
            q.question,
            use_rerank=(condition in ("C", "D")),
            verbose=verbose,
            stats=stats,
            q_freshness=q.freshness,
        )
        trace = {"tools": ["bm25", "vector", "rrf"],
                 "rerank": condition in ("C", "D"),
                 "retrieved": len(top_evs),
                 "candidates": len(stats.get("candidate_ids", [])),
                 "cache_hit": stats.get("cache_hit", False)}
        run.tool_trace.append(trace)
        run.index_version = store.index_version
        run.corpus_version = store.corpus_version
        run.cache_hits = 1 if stats.get("cache_hit") else 0
        run.candidate_ids = stats.get("candidate_ids", [])
    elif condition == "E":
        # 劣化派生（§6.2）：先在 B 的基线初检（use_rerank=False）上取候选，
        # 再按预注册规则截断/扰动。当前骨架只实现 top-k 减半；
        # B4 合入 e_perturbation_rules.json 后在此扩展删除 gold / 注入不支持证据等扰动。
        base_evs, base_feats = store.retrieve(
            q.question, use_rerank=False, verbose=verbose, stats=stats,
            q_freshness=q.freshness)
        n = max(2, len(base_evs) // 2)
        top_evs = base_evs[:n]
        features = [f for f in base_feats if f["doc_id"] in {e["id"] for e in top_evs}]
        # 扰动标签优先取题目声明（stress 题 rubric.perturbation），执行逻辑仍为 top-k 减半骨架；
        # B4 合入 e_perturbation_rules.json 后按声明实现 gold 删除/注入不支持证据等扰动。
        declared = q.rubric.get("perturbation") if isinstance(q.rubric, dict) else None
        run.tool_trace.append({"tools": ["bm25", "vector", "rrf", "degrade"],
                               "derived_from": "B_baseline_rerank_false",
                               "perturbation": declared or "topk_halved",
                               "perturbation_executed": "topk_halved",
                               "retrieved": len(top_evs), "degraded": True,
                               "cache_hit": stats.get("cache_hit", False)})
        run.index_version = store.index_version
        run.corpus_version = store.corpus_version
        run.cache_hits = 1 if stats.get("cache_hit") else 0
        run.candidate_ids = stats.get("candidate_ids", [])

    # ---- 生成 + 校验 ----
    result, _ = gen.generate(q, condition, top_evs, features)
    result.index_version = store.index_version
    result.corpus_version = store.corpus_version
    result.agent_plan = run.agent_plan
    result.tool_trace = run.tool_trace
    result.cache_hits = run.cache_hits
    result.candidate_ids = run.candidate_ids
    return result
