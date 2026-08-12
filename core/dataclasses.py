"""数据契约：Question / Evidence / Claim / Run / Score（与实施规划 §3.1 对齐）"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class Question:
    """题目契约（兼容 B1 蓝图格式与 B3 运行器格式，双向可用）。

    B1 蓝图样例题字段（sample_questions.jsonl / B2 正式题将按此交付）：
      id/split/dataset_pack/topic/question_type/difficulty/question/answerable/
      as_of_date/source_provenance/source_group_id/gold_source_ids/key_points/rubric_version...
    B3 运行器题集（dev8/formal12/stress）使用精简字段 + rubric 内嵌 key_points。

    加载时：
    - `key_points`（蓝图顶层字段）自动映射进 rubric["key_points"]，judge 可直接消费；
    - 未识别的字段（language/note/source_provenance/rubric_version 等）保留在 extras，
      不再被静默丢弃。
    """
    id: str
    topic: str                # hypertension | lipids | ...
    difficulty: str           # easy | medium | hard（蓝图可为 int 2/3，兼容）
    question: str
    question_type: str        # mechanism | guideline | latest_trial | insufficient
    freshness: str = "stable"  # stable | up_to_date（蓝图格式无此字段，给默认值）
    gold_source_ids: list[str] = field(default_factory=list)
    split: str = ""           # DEV | TEST | STRESS | EXTERNAL | RESERVE
    dataset_pack: str = ""
    answerable: bool | None = None
    as_of_date: str = ""
    source_group_id: str = ""
    extras: dict[str, Any] = field(default_factory=dict)  # 其余未识别字段保留，不丢弃
    rubric: dict[str, Any] = field(default_factory=dict)  # 关键回答点 + 扣分项

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Question":
        d = dict(d)
        # 蓝图顶层 key_points -> rubric.key_points（judge 按 rubric 读取评分点）
        if "key_points" in d:
            rubric = dict(d.get("rubric") or {})
            rubric.setdefault("key_points", d["key_points"])
            d["rubric"] = rubric
        known = set(cls.__dataclass_fields__)
        extras = {k: v for k, v in d.items() if k not in known}
        if extras:
            d["extras"] = {**(d.get("extras") or {}), **extras}
        valid = {k: v for k, v in d.items() if k in known}
        return cls(**valid)


@dataclass
class Evidence:
    id: str
    source_type: str          # pubmed | clinicaltrial | guideline | europepmc | wiki
    title: str
    text: str                 # abstract 或 chunk
    authors: str = ""
    published_at: str = ""    # YYYY-MM-DD
    url: str = ""
    pmid: str = ""
    doi: str = ""
    nct_id: str = ""
    guideline_name: str = ""
    page: str = ""
    evidence_level: str = "unknown"  # guideline | systematic_review | rct | cohort | expert | unknown
    population: str = ""
    intervention: str = ""
    comparator: str = ""
    outcome: str = ""
    fetched_at: str = ""
    content_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Evidence":
        # 兼容 WSL 采集管线的字段名：abstract_or_chunk -> text（构造前注入，text 为必填）
        d = dict(d)
        d.setdefault("text", d.get("abstract_or_chunk") or "")
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        ev = cls(**valid)
        if not ev.text:
            ev.text = d.get("abstract_or_chunk", "") or ""
        return ev


@dataclass
class Claim:
    claim_id: str
    run_id: str
    text: str
    criticality: str = "important"   # critical | important | context
    evidence_ids: list[str] = field(default_factory=list)
    evidence_span_ids: list[str] = field(default_factory=list)
    entailment_score: Optional[float] = None
    population_match: Optional[bool] = None
    time_match: Optional[bool] = None
    conflict_ids: list[str] = field(default_factory=list)
    verification_method: str = ""
    decision: str = "pending"        # supported | unsupported | insufficient | refused

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Run:
    """一次实验运行记录（对齐实施规划 §3.1 Run 契约）

    condition: A | A2 | B | C | D | E
    - A   : closed-book 纯 LLM（B3 主责）
    - A2  : 通用搜索对照，不使用项目 Evidence store（B3 主责，可选）
    - B   : 冻结语料 + BM25/向量 RRF top-k，无 rerank（B3 主责）
    - C/D/E : rerank / 完整组件包 / 劣化（B4 主责）
    """
    run_id: str = field(default_factory=lambda: _uid("run"))
    question_id: str = ""
    condition: str = ""
    replicate: int = 1                # REPEAT 子集重复序号
    seed: int = 0                     # 条件顺序 / 采样随机种子
    model: str = ""
    model_snapshot: str = ""         # 模型快照标识（默认与 model 相同）
    prompt_version: str = ""
    config_hash: str = ""            # 配置版本哈希（config.yaml 内容 sha1）
    code_commit: str = ""            # git 提交短哈希（run.schema.json 必填字段）
    dataset_version: str = ""        # 数据集 manifest 版本
    corpus_version: str = ""         # 证据语料版本（证据内容 hash 集合）
    index_version: str = ""
    provider_fingerprint: str = ""   # LLM provider 标识（base_url + model）
    retrieved_evidence: list[dict] = field(default_factory=list)
    candidate_ids: list[str] = field(default_factory=list)   # RRF 初检候选 ID（≤100，供同源核验）
    answer: str = ""
    claims: list[dict] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)   # A2 条件为 ["S1",...] 与 [E#] 区分
    verification_decision: str = "PASS"   # PASS | WARN | REFUSE
    agent_plan: list[str] = field(default_factory=list)
    tool_trace: list[dict] = field(default_factory=list)
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0       # LLM + 检索/搜索成本合计（美元）
    cache_hits: int = 0               # 检索缓存命中数（确定性检索去重）
    attempt_count: int = 0            # LLM 调用实际尝试次数（重试日志）
    status: str = "ok"                # ok | error
    error: str = ""
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Run":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class Score:
    run_id: str
    question_id: str
    condition: str = ""
    judge_id: str = ""
    # 版本（score.schema.json 必填；judge 写入）
    metric_version: str = "v0.1"
    rubric_version: str = "v0.1"
    # 检索（B5 对齐：hit_at_5/mrr/recall_at_50/rerank_ndcg）
    hit_at_5: Optional[float] = None
    mrr: Optional[float] = None
    recall_at_50: Optional[float] = None
    rerank_ndcg: Optional[float] = None
    # 主终点（§6.4）：关键主张中未获证据支持的比例（critical claim 单独统计）
    unsupported_critical_claim_rate: Optional[float] = None
    # 内容（1-5，LLM judge / 人工）
    relevance: Optional[float] = None
    correctness: Optional[float] = None
    completeness: Optional[float] = None
    faithfulness: Optional[float] = None
    # 引用
    citation_precision: Optional[float] = None
    citation_coverage: Optional[float] = None
    claim_support_rate: Optional[float] = None
    unsupported_claim_rate: Optional[float] = None
    abstention_quality: Optional[float] = None   # 证据不足合理拒答 / 证据充分误拒答
    # 系统
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    # 审阅
    reviewer: str = ""
    adjudication: str = ""
    notes: str = ""
    # ---- judge 偏差审计字段（规划 §6.3 匿名随机 + 位置/长度/家族偏差审计；可选） ----
    position: Optional[int] = None                 # 匿名展示位置（随机）
    anonymous_label: str = ""                      # 匿名标签，如 OPT①
    randomization_seed: Optional[int] = None       # 每题位置随机种子
    judge_family: str = ""                        # judge 模型家族（偏差审计分组）
    citation_count: Optional[int] = None           # 展示给 judge 的引用数量
    displayed_citation_count: Optional[int] = None # 引用外观偏差审计
    control_type: str = ""                        # style | position_swap | wrong_citations
    control_id: str = ""                          # 控制样本配对 ID
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)


def load_jsonl(path: str) -> list[dict]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def save_jsonl(path: str, records: list[dict], mode: str = "a") -> None:
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w" if mode == "w" else "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
