"""run_condition：单个问题 × 单个条件的完整实验流程

B3 主责：A / A2 / B 三个条件在此实现；C/D/E 由 B4 扩展（E 骨架在本文件，供 B4 按预注册规则重写）。
"""
from __future__ import annotations

from typing import Any, Optional

from core.config import Config
from core.dataclasses import Question, Run
from core.llm import LLMClient
from evaluation.a2_search import search_general
from evaluation.stress import apply_stress
from generation.answer import AnswerGenerator
from retrieval.index import EvidenceStore

# D 完整组件工作流缓存（A5 装配一次、多题复用；vendored track1/ 不可用时回退 D≡C）
_D_WORKFLOW: Any = None
_D_WORKFLOW_ERROR: Optional[str] = None


def _get_d_workflow(cfg: Config):
    global _D_WORKFLOW, _D_WORKFLOW_ERROR
    if _D_WORKFLOW is None and _D_WORKFLOW_ERROR is None:
        try:
            from evaluation.d_full_system import build_d_workflow
            _D_WORKFLOW = build_d_workflow(cfg, use_live_claims=True)
        except Exception as e:  # vendored A5 缺失/导入失败 -> 记录并回退 D≡C
            _D_WORKFLOW_ERROR = f"{type(e).__name__}: {e}"
    return _D_WORKFLOW


def run_condition(q: Question, condition: str, cfg: Config,
                  store: Optional[EvidenceStore] = None,
                  llm: Optional[LLMClient] = None,
                  verbose: bool = False,
                  seed: int = 0) -> Run:
    """执行一个条件。store 为 None 时视为纯 LLM 条件（A）。

    condition 取值: A | A2 | B | C | D | E
    - A  : 纯 LLM，无检索，不提供证据（B3 主责）
    - A2 : 通用搜索对照，不使用项目 Evidence store，固定搜索预算 + 响应快照（B3 主责，可选）
    - B  : BM25 + 向量 + RRF 后直接取 top-k，无 rerank（B3 主责）
    - C  : B + 特征重排 + MMR（B4）
    - D  : C + Wiki/Agent（B4）
    - E  : 劣化检索（B4 主责）。统一走 evaluation/stress.py 预注册规则引擎
           （drop_all_gold_v1 / topk_reduced / inject_unsupporting_v1 /
           unanswerable_malicious，见 evaluation/preregistration/e_perturbation_rules.json），
           在 B/C 同源的 RRF 初检候选上派生，seed 参与注入/选择保证可复现。
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
    if condition in ("B", "C"):
        top_evs, features = store.retrieve(
            q.question,
            use_rerank=(condition == "C"),
            verbose=verbose,
            stats=stats,
            q_freshness=q.freshness,
        )
        trace = {"tools": ["bm25", "vector", "rrf"],
                 "rerank": condition == "C",
                 "retrieved": len(top_evs),
                 "candidates": len(stats.get("candidate_ids", [])),
                 "cache_hit": stats.get("cache_hit", False)}
        run.tool_trace.append(trace)
        run.index_version = store.index_version
        run.corpus_version = store.corpus_version
        run.cache_hits = 1 if stats.get("cache_hit") else 0
        run.candidate_ids = stats.get("candidate_ids", [])
    elif condition == "D":
        # D 完整组件包：A5（Wiki/Skill/MCP/Agent + 七道门禁）受限编排。
        # 由 evaluation.d_full_system 装配，检索走 A5 注入的混合检索器；
        # vendored track1/ 不可用或装配失败时回退 C（记录错误，报告披露）。
        workflow = _get_d_workflow(cfg)
        if workflow is not None:
            from evaluation.d_full_system import run_d_question
            d_res = run_d_question(q, workflow, cfg)
            run.answer = d_res.get("answer") or ""
            run.verification_decision = d_res.get("verification_decision") or "REFUSE"
            run.claims = d_res.get("claims") or []
            run.citations = [c.get("evidence_id") for c in (d_res.get("citations") or [])]
            run.retrieved_evidence = d_res.get("retrieved_evidence") or []
            run.agent_plan = d_res.get("agent_plan") or {}
            run.tool_trace = d_res.get("tool_trace") or []
            run.latency_ms = d_res.get("d_extra_latency_ms") or 0
            run.system_version = d_res.get("system_version") or ""
            errs = d_res.get("errors") or []
            if errs:
                run.error = "; ".join(str(e) for e in errs)
                run.status = "error"
            return run
        # 回退：D≡C（完整组件不可用，明确标记）
        top_evs, features = store.retrieve(
            q.question, use_rerank=True, verbose=verbose, stats=stats,
            q_freshness=q.freshness)
        run.tool_trace.append({"tools": ["bm25", "vector", "rrf", "rerank"],
                               "rerank": True, "d_fallback": True,
                               "d_error": _D_WORKFLOW_ERROR or "workflow unavailable",
                               "retrieved": len(top_evs),
                               "cache_hit": stats.get("cache_hit", False)})
        run.index_version = store.index_version
        run.corpus_version = store.corpus_version
        run.cache_hits = 1 if stats.get("cache_hit") else 0
        run.candidate_ids = stats.get("candidate_ids", [])
        run.agent_plan = ["D fallback: A5 full-system unavailable -> D≡C"]
    elif condition == "E":
        # 劣化派生（§6.2）：在 B/C 同源的 RRF 初检候选上按预注册规则派生（drop gold /
        # 降 top-k / 注入不支持证据 / 范围外+注入题），统一走 evaluation/stress.py。
        # stress_20.json（B2 正式压力集）的 perturb_type → 预注册规则映射：
        #   retrieval_damage        -> delete_gold_v1（= drop_all_gold_v1，删除 gold + 截断）
        #   injected_unsupported    -> inject_polluted_v1（注入题目声明的 polluted_evidence_ids）
        #   no_evidence_outscope    -> out_of_scope（题面承载，不改候选集）
        #   malicious_injection_fake_id -> malicious_fake_id（提示注入/伪造 ID，不改候选集）
        base_evs, base_feats = store.retrieve(
            q.question, use_rerank=False, verbose=verbose, stats=stats,
            q_freshness=q.freshness)
        candidates = [
            {**candidate, "evidence_id": candidate["doc_id"]}
            for candidate in stats.get("rrf_candidates", [])
        ]
        q_dict = q.to_dict()
        q_extra = q_dict.get("extras") or {}
        q_rubric = q_dict.get("rubric") or {}
        perturb_type = (
            q_extra.get("perturb_type") or q_dict.get("perturb_type") or ""
        )
        rule_map = {
            "retrieval_damage": "delete_gold_v1",
            "injected_unsupported": "inject_polluted_v1",
            "no_evidence_outscope": "out_of_scope",
            "malicious_injection_fake_id": "malicious_fake_id",
        }
        declared_rule = (
            q_extra.get("stress_rule")
            or q_dict.get("stress_rule")
            or q_rubric.get("stress_rule")
        )
        stress_rule = rule_map.get(perturb_type) or declared_rule or "drop_all_gold_v1"
        polluted_ids = (
            q_extra.get("polluted_evidence_ids")
            or q_dict.get("polluted_evidence_ids")
        )
        perturbed, manifest = apply_stress(
            candidates, q_dict, rule=stress_rule, seed=seed,
            final_k=cfg["retrieval"]["k_final"],
            polluted_ids=polluted_ids,
        )
        top_evs = [
            evidence.to_dict()
            for candidate in perturbed
            if (evidence := store.get(candidate["evidence_id"])) is not None
        ]
        features = [
            {**candidate, "doc_id": candidate["evidence_id"]}
            for candidate in perturbed
        ]
        run.tool_trace.append({"tools": ["bm25", "vector", "rrf", "degrade"],
                               "derived_from": "rrf_candidates_shared_by_B_and_C",
                               "perturbation": perturb_type or declared_rule or "",
                               "perturbation_executed": manifest.stress_rule,
                               "stress_manifest": manifest.to_dict(),
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
