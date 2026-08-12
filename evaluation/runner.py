from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional, Tuple

from .conditions import get_condition_config
from .adapters.full_system import FullSystemResult, build_full_system_adapter
from .providers.mock import MockProvider
from .schemas import RunRecord
from .stress import apply_stress


def _run_id(question_id: str, condition: str, config_hash: str, seed: int, replicate: int) -> str:
    raw = f"{question_id}:{condition}:{config_hash}:seed={seed}:replicate={replicate}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def run_condition(
    question: Dict[str, Any],
    condition: str,
    retriever: Any,
    provider: Optional[Any] = None,
    config: Optional[Dict[str, Any]] = None,
    conditions_path: Optional[str] = None,
) -> Tuple[RunRecord, Dict[str, Any]]:
    condition = condition.upper()
    config = config or {}
    provider = provider or MockProvider()
    # 条件配置：代码默认 + configs/conditions.yaml 覆盖（版本化配置生效）
    condition_config = get_condition_config(condition, yaml_path=conditions_path)
    config_hash = config.get("config_hash", "local-dev-v0.1")
    dataset_version = config.get("dataset_version", "fixture-v0.1")
    corpus_version = config.get("corpus_version", "fixture-corpus-v0.1")
    index_version = config.get("index_version", getattr(retriever, "index_version", "unknown"))
    prompt_version = config.get("prompt_version", "prompt-v0.1")
    seed = int(config.get("seed", 0))
    replicate = int(config.get("replicate", 1))
    model = config.get("model") or getattr(provider, "model", "") or "mock"
    model_snapshot = config.get("model_snapshot") or model
    provider_fingerprint = config.get("provider_fingerprint") or getattr(
        provider, "provider_fingerprint", ""
    )
    code_commit = config.get("code_commit", "")
    run_id = _run_id(question["id"], condition, config_hash, seed, replicate)
    started = time.perf_counter()

    if condition == "E" and question.get("split") != "STRESS":
        run = RunRecord(
            run_id=run_id,
            question_id=question["id"],
            split=question.get("split", "unknown"),
            condition=condition,
            status="not_applicable",
            dataset_version=dataset_version,
            corpus_version=corpus_version,
            index_version=index_version,
            config_hash=config_hash,
            prompt_version=prompt_version,
            system_version=None,
            seed=seed,
            replicate=replicate,
            model=model,
            model_snapshot=model_snapshot,
            provider_fingerprint=provider_fingerprint,
            code_commit=code_commit,
            candidate_ids=[],
            retrieved_evidence=[],
            answer=None,
            claims=[],
            citations=[],
            error={"code": "E_REQUIRES_STRESS_SPLIT"},
        )
        return run, {"retrieval": None, "stress": None}

    if condition == "A":
        generated = provider.generate(question, [], condition)
        run = RunRecord(
            run_id=run_id,
            question_id=question["id"],
            split=question.get("split", "unknown"),
            condition=condition,
            status="success",
            dataset_version=dataset_version,
            corpus_version="none",
            index_version="none",
            config_hash=config_hash,
            prompt_version=prompt_version,
            system_version=None,
            seed=seed,
            replicate=replicate,
            model=model,
            model_snapshot=model_snapshot,
            provider_fingerprint=provider_fingerprint,
            code_commit=code_commit,
            candidate_ids=[],
            retrieved_evidence=[],
            answer=generated["answer"],
            claims=generated["claims"],
            citations=generated["citations"],
            verification_decision=generated.get("verification_decision", "PASS"),
            latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
            input_tokens=generated.get("input_tokens"),
            output_tokens=generated.get("output_tokens"),
            estimated_cost=generated.get("estimated_cost"),
        )
        return run, {"retrieval": None, "stress": None}

    retrieval_config = dict(config)
    if condition == "B":
        retrieval_config["use_rerank"] = False
    retrieval = retriever.search(question, retrieval_config)
    final_evidence = list(retrieval.final_evidence)
    stress_manifest = None
    tool_trace = []
    agent_plan = {}
    system_version = None
    full_system_result: FullSystemResult | None = None

    if condition == "D":
        # D 骨架：完整组件包（Wiki/Skill/MCP/Agent）尚未接入时用 mock plan/trace 占位；
        # 真实 D 应通过 FullSystemAdapter（见 run_a5.py）产出，并单独计入额外延迟/token/成本。
        adapter = build_full_system_adapter(config)
        full_system_result = adapter.run(question, {
            **config,
            "system_version": config.get("system_version")
            or condition_config.get("system_version")
            or "mock-full-system-v0.1",
            "evidence": final_evidence,
            "retrieval": retrieval.to_dict(),
        })
        final_evidence = list(full_system_result.retrieved_evidence)
        system_version = full_system_result.system_version
        agent_plan = full_system_result.agent_plan
        tool_trace = full_system_result.tool_trace
    elif condition == "E":
        # E 劣化：在“检索阶段候选集”（B/C 同源的 RRF 融合候选）上按预注册规则派生，
        # 返回的劣化列表即 E 的最终上下文（截断到 final_k），保证劣化对生成可见；
        # gold 删除规则在候选集中找不到 gold 时自动回退 topk_reduced 保 C/E 配对。
        stress_candidates = list(
            retrieval.rrf_candidates
            or retrieval.rerank_candidates
            or final_evidence
        )
        final_evidence, stress = apply_stress(
            stress_candidates,
            question,
            rule=condition_config["stress_rule"],
            seed=seed,
            final_k=int(config.get("final_k", 4)),
        )
        stress_manifest = stress.to_dict()

    generated = (
        {
            "answer": full_system_result.answer,
            "claims": full_system_result.claims,
            "citations": full_system_result.citations,
            "verification_decision": full_system_result.verification_decision,
            "input_tokens": full_system_result.input_tokens,
            "output_tokens": full_system_result.output_tokens,
            "estimated_cost": full_system_result.estimated_cost,
        }
        if full_system_result is not None
        else provider.generate(question, final_evidence, condition)
    )
    elapsed = max(1, int((time.perf_counter() - started) * 1000))
    run = RunRecord(
        run_id=run_id,
        question_id=question["id"],
        split=question.get("split", "unknown"),
        condition=condition,
        status="success",
        dataset_version=dataset_version,
        corpus_version=corpus_version,
        index_version=index_version,
        config_hash=config_hash,
        prompt_version=prompt_version,
        system_version=system_version,
        seed=seed,
        replicate=replicate,
        model=model,
        model_snapshot=model_snapshot,
        provider_fingerprint=provider_fingerprint,
        code_commit=code_commit,
        candidate_ids=[item.get("evidence_id", "") for item in retrieval.rrf_candidates],
        retrieved_evidence=final_evidence,
        answer=generated["answer"],
        claims=generated["claims"],
        citations=generated["citations"],
        verification_decision=generated.get("verification_decision", "PASS"),
        agent_plan=agent_plan,
        tool_trace=tool_trace,
        stress_manifest=stress_manifest,
        latency_ms=elapsed,
        input_tokens=generated.get("input_tokens"),
        output_tokens=generated.get("output_tokens"),
        estimated_cost=generated.get("estimated_cost"),
        d_extra_latency_ms=(full_system_result.latency_ms if full_system_result is not None else None),
        d_extra_input_tokens=(full_system_result.input_tokens if full_system_result is not None else None),
        d_extra_output_tokens=(full_system_result.output_tokens if full_system_result is not None else None),
        d_extra_estimated_cost=(full_system_result.estimated_cost if full_system_result is not None else None),
        error=(
            {"code": "FULL_SYSTEM_ERROR", "details": full_system_result.errors}
            if full_system_result is not None and full_system_result.errors
            else None
        ),
    )
    trace = {"retrieval": retrieval.to_dict(), "stress": stress_manifest}
    return run, trace
