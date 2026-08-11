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
    """Run 契约（对齐实施规划 §3.1 与 evaluation/schemas/run.schema.json）。

    B4 骨架此前缺少 seed/replicate/model/model_snapshot/provider_fingerprint/
    code_commit/verification_decision 字段，导致与 core.dataclasses.Run（B3 实验
    运行器）的输出 schema 不一致，B5 评分需要兼容两套格式。本 PR 补齐为统一契约。
    """
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
    replicate: int = 1                 # REPEAT 子集重复序号
    seed: int = 0                      # 条件顺序 / 采样随机种子
    model: str = ""
    model_snapshot: str = ""          # 模型快照标识（A/B/C/D/E 必须一致，§6.2 公平性）
    provider_fingerprint: str = ""    # LLM provider 标识（base_url + model）
    code_commit: str = ""             # 运行时代码 commit（config_hash 已含时可为空）
    verification_decision: str = "PASS"  # PASS | WARN | REFUSE
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
