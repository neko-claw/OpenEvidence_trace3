from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional, Tuple

from .conditions import get_condition_config
from .providers.mock import MockProvider
from .schemas import RunRecord
from .stress import apply_stress


def _run_id(question_id: str, condition: str, config_hash: str) -> str:
    raw = f"{question_id}:{condition}:{config_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def run_condition(
    question: Dict[str, Any],
    condition: str,
    retriever: Any,
    provider: Optional[Any] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[RunRecord, Dict[str, Any]]:
    condition = condition.upper()
    config = config or {}
    provider = provider or MockProvider()
    condition_config = get_condition_config(condition)
    config_hash = config.get("config_hash", "local-dev-v0.1")
    dataset_version = config.get("dataset_version", "fixture-v0.1")
    corpus_version = config.get("corpus_version", "fixture-corpus-v0.1")
    index_version = config.get("index_version", getattr(retriever, "index_version", "unknown"))
    prompt_version = config.get("prompt_version", "prompt-v0.1")
    run_id = _run_id(question["id"], condition, config_hash)
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
            retrieved_evidence=[],
            answer=generated["answer"],
            claims=generated["claims"],
            citations=generated["citations"],
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

    if condition == "D":
        system_version = condition_config.get("system_version")
        agent_plan = {"skill": "evidence_research@v0.1", "steps": ["retrieve", "rerank", "audit"]}
        tool_trace = [
            {"tool": "search_evidence", "status": "mock_success", "count": len(final_evidence)},
            {"tool": "validate_citation", "status": "mock_success", "count": len(final_evidence)},
        ]
    elif condition == "E":
        # E 的预注册规则作用于 C 的初检候选集，而不是只检查最终上下文。
        # 这样即使 rerank 已把 Gold 排到最终上下文之外，压力规则仍能记录
        # 候选集中的 Gold 删除；若被删证据已进入最终上下文，则同步移除。
        stress_candidates = list(
            retrieval.rrf_candidates
            or retrieval.rerank_candidates
            or final_evidence
        )
        _, stress = apply_stress(
            stress_candidates,
            question,
            rule=condition_config["stress_rule"],
            seed=int(config.get("seed", 0)),
        )
        removed_ids = set(stress.removed_evidence_ids)
        if removed_ids:
            final_evidence = [
                item for item in final_evidence
                if item.get("evidence_id") not in removed_ids
            ]
        stress_manifest = stress.to_dict()

    generated = provider.generate(question, final_evidence, condition)
    elapsed = max(1, int((time.perf_counter() - started) * 1000))
    run = RunRecord(
        run_id=run_id,
        question_id=question["id"],
        split=question.get("split", "unknown"),
        condition=condition,
        status="success" if not stress_manifest or stress_manifest.get("applicable", True) else "not_applicable",
        dataset_version=dataset_version,
        corpus_version=corpus_version,
        index_version=index_version,
        config_hash=config_hash,
        prompt_version=prompt_version,
        system_version=system_version,
        retrieved_evidence=final_evidence,
        answer=generated["answer"],
        claims=generated["claims"],
        citations=generated["citations"],
        agent_plan=agent_plan,
        tool_trace=tool_trace,
        stress_manifest=stress_manifest,
        latency_ms=elapsed,
        input_tokens=generated.get("input_tokens"),
        output_tokens=generated.get("output_tokens"),
        estimated_cost=generated.get("estimated_cost"),
    )
    trace = {"retrieval": retrieval.to_dict(), "stress": stress_manifest}
    return run, trace
