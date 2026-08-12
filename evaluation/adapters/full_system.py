from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class FullSystemResult:
    """Stable B4 boundary for the complete-system D condition."""

    question_id: str
    system_version: str
    agent_plan: dict[str, Any] = field(default_factory=dict)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    retrieved_evidence: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    verification_decision: str = "PASS"
    answer: str | None = None
    refusal_reason: str | None = None
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)


class FullSystemAdapter(Protocol):
    def run(self, question: dict[str, Any], config: dict[str, Any]) -> FullSystemResult:
        ...


class MockFullSystem:
    """Offline D implementation used until the real A5 adapter is selected."""

    system_version = "mock-full-system-v0.1"

    def run(self, question: dict[str, Any], config: dict[str, Any]) -> FullSystemResult:
        started = time.perf_counter()
        evidence = list(config.get("evidence", []))
        context_ids = {item.get("evidence_id") for item in evidence}
        claims = []
        for point in question.get("atomic_points", []):
            gold = [item for item in question.get("gold_source_ids", []) if item in context_ids]
            claims.append({
                "claim_id": f"{question['id']}:{point['id']}",
                "text": point.get("text", ""),
                "criticality": point.get("criticality", "important"),
                "evidence_ids": gold[:2],
                "decision": "supported" if gold else "insufficient",
                "verification_method": "mock_full_system_gold_overlap",
            })
        answer = (
            f"[D] offline full-system run: {len(evidence)} evidence records, "
            f"{sum(c['decision'] == 'supported' for c in claims)}/{len(claims)} claims supported."
            if question.get("answerable", True) and evidence
            else "[D] full-system refused: insufficient evidence or unanswerable question."
        )
        return FullSystemResult(
            question_id=question["id"],
            system_version=config.get("system_version", self.system_version),
            agent_plan={"skill": "evidence_research@v0.1", "steps": ["retrieve", "audit", "release"]},
            tool_trace=[
                {"tool": "search_evidence", "status": "mock_success", "count": len(evidence)},
                {"tool": "citation_audit", "status": "mock_success", "count": len(claims)},
            ],
            retrieved_evidence=evidence,
            claims=claims,
            citations=[{"evidence_id": item.get("evidence_id"), "valid": True} for item in evidence],
            verification_decision="PASS" if evidence else "REFUSE",
            answer=answer,
            refusal_reason=None if evidence else "insufficient evidence",
            latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
            estimated_cost=0.0,
        )


class A5FullSystemAdapter:
    """Adapter for the Track 1 A5 workflow, normalized to the B4 result."""

    def __init__(self, a5_root: Path, workflow: Any):
        self.a5_root = a5_root.resolve()
        self.workflow = workflow
        if str(self.a5_root) not in sys.path:
            sys.path.insert(0, str(self.a5_root))

    def run(self, question: dict[str, Any], config: dict[str, Any]) -> FullSystemResult:
        from a5.domain.models import Question as A5Question

        started = time.perf_counter()
        a5_question = A5Question(
            question_id=question["id"],
            text=question["question"],
            metadata={
                "track3_question_id": question["id"],
                **question.get("extras", {}),
                **({"mock_safety_decision": "ALLOW"} if config.get("a5_demo") else {}),
            },
        )
        run = self.workflow.answer(a5_question)
        decision = run.decision.value if run.decision is not None else "REFUSE"
        answer = run.final_answer.text if run.final_answer is not None else None
        claims = [claim.model_dump(mode="json") for claim in run.claims]
        evidence = [record.model_dump(mode="json") for record in run.retrieved_evidence]
        cited_ids = run.final_answer.cited_evidence_ids if run.final_answer else []
        citations = [{"evidence_id": evidence_id, "valid": True} for evidence_id in cited_ids]
        traces = [trace.model_dump(mode="json") for trace in run.trace]
        return FullSystemResult(
            question_id=question["id"],
            system_version=config.get("system_version", run.agent_version),
            agent_plan=run.agent_plan.model_dump(mode="json") if run.agent_plan else {},
            tool_trace=traces,
            retrieved_evidence=evidence,
            claims=claims,
            citations=citations,
            verification_decision=decision,
            answer=answer,
            refusal_reason="; ".join(run.final_answer.limitations) if run.final_answer and decision == "REFUSE" else None,
            latency_ms=max(1, int(run.latency_ms or (time.perf_counter() - started) * 1000)),
            errors=[{"error": run.error}] if run.error else [],
        )


def build_full_system_adapter(config: dict[str, Any] | None = None) -> FullSystemAdapter:
    config = config or {}
    adapter = config.get("full_system_adapter")
    return adapter if adapter is not None else MockFullSystem()
