from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RetrievalResult:
    question_id: str
    query: str
    query_rewrites: List[str]
    index_version: str
    bm25_candidates: List[Dict[str, Any]] = field(default_factory=list)
    vector_candidates: List[Dict[str, Any]] = field(default_factory=list)
    rrf_candidates: List[Dict[str, Any]] = field(default_factory=list)
    rerank_candidates: List[Dict[str, Any]] = field(default_factory=list)
    final_evidence: List[Dict[str, Any]] = field(default_factory=list)
    feature_scores: List[Dict[str, Any]] = field(default_factory=list)
    index_stats: Dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StressManifest:
    stress_id: str
    question_id: str
    base_condition: str
    stress_rule: str
    seed: int
    original_candidate_ids: List[str]
    removed_evidence_ids: List[str] = field(default_factory=list)
    injected_evidence_ids: List[str] = field(default_factory=list)
    perturbed_candidate_ids: List[str] = field(default_factory=list)
    applicable: bool = True
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RunRecord:
    run_id: str
    question_id: str
    split: str
    condition: str
    status: str
    dataset_version: str
    corpus_version: str
    index_version: str
    config_hash: str
    prompt_version: str
    system_version: Optional[str]
    retrieved_evidence: List[Dict[str, Any]]
    answer: Optional[str]
    claims: List[Dict[str, Any]]
    citations: List[Dict[str, Any]]
    agent_plan: Dict[str, Any] = field(default_factory=dict)
    tool_trace: List[Dict[str, Any]] = field(default_factory=list)
    stress_manifest: Optional[Dict[str, Any]] = None
    latency_ms: int = 0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    estimated_cost: Optional[float] = None
    cache_hits: int = 0
    attempt_count: int = 1
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
