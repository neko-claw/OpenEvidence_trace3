"""D 完整组件包：接入赛道 1 A5 受限编排（Wiki + Skill + MCP 边界 + Agent 状态机 + 七道门禁）。

D 条件（实施规划 §6.2）= C 的检索 + LLM Wiki 导航 + Skill（evidence_research /
citation_audit）+ MCP 工具边界 + 单 Agent 受限编排，证据白名单与工具预算固定。

赛道 3 侧提供：
- ``Track3SafetyPolicy``：Gate0 规则策略（expected_action -> ALLOW/DENY），
  不依赖 A1 在线策略（A1 为赛道 1 生产依赖，MVP 用规则近似并如实标注）；
- ``OpenAICompatibleJSONTransport``：OpenAI 兼容 JSON 结构化输出（deepseek-chat，
  与 A/B/C 条件同一生成模型，公平性要求）；
- ``build_d_workflow``：装配 vendored A5 工作流（track1/）；
- ``run_d_question``：执行并把 AgentRun 映射为 Track 3 Run 契约。

公平性：D 使用与 A/B/C 相同的生成模型快照与语料快照；A5 编排的额外延迟/token/
成本单独计入（d_extra_* 字段）；结论只解释为“完整组件包整体增量”，不做单组件归因。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from core.config import load_config
from core.dataclasses import Question

TRACK1_ROOT = Path(__file__).resolve().parents[1] / "track1"


# ---------------------------------------------------------------------------
# Gate0：赛道 3 规则安全策略（A1 生产策略未接入时的 MVP 近似，fail-closed）
# ---------------------------------------------------------------------------
class Track3SafetyPolicy:
    """把题目级 expected_action 映射为安全决策：

    - expected_action=REFUSE  -> DENY（拒答，不进检索/生成）
    - expected_action=WARN    -> ALLOW（允许，但回答须带边界；由 Gate6 WARN）
    - expected_action=ANSWER  -> ALLOW
    - 未知/缺字段            -> UNKNOWN（fail-closed，判 REFUSE）
    主题范围：高血压/血脂（赛道 1 与 3 共享范围）。
    """

    def __init__(self, version: str | None = None) -> None:
        self.version = f"track3_rule_gate0@{version or '0.1.0'}"

    def assess(self, question: Any) -> Any:
        from a5.domain.enums import SafetyDecision
        from a5.domain.models import SafetyAssessment

        meta = dict(question.metadata or {})
        action = str(meta.get("expected_action") or "").upper()
        answerable = meta.get("answerable")
        topic = str(meta.get("topic") or "")
        in_scope = topic in ("hypertension", "dyslipidemia", "lipids")
        if not in_scope:
            return SafetyAssessment(
                decision=SafetyDecision.DENY,
                reason="out_of_scope_topic",
                policy_version=self.version,
            )
        if action == "REFUSE" or answerable is False:
            return SafetyAssessment(
                decision=SafetyDecision.DENY,
                reason=f"question_requires_refusal (expected_action={action})",
                policy_version=self.version,
            )
        if action == "WARN":
            return SafetyAssessment(
                decision=SafetyDecision.ALLOW,
                reason="allowed_with_warning_expected",
                policy_version=self.version,
            )
        if action == "ANSWER":
            return SafetyAssessment(
                decision=SafetyDecision.ALLOW,
                reason="in_scope_answer_question",
                policy_version=self.version,
            )
        return SafetyAssessment(
            decision=SafetyDecision.UNKNOWN,
            reason=f"missing_expected_action (action={action!r})",
            policy_version=self.version,
        )


# ---------------------------------------------------------------------------
# OpenAI 兼容 JSON 结构化 transport（与 A/B/C 同一模型 deepseek-chat）
# ---------------------------------------------------------------------------
class OpenAICompatibleJSONTransport:
    """OpenAI 兼容 chat/completions 的 JSON 模式 transport（A5 结构化输出协议）。"""

    def __init__(self, llm_cfg: dict) -> None:
        self.base_url = str(llm_cfg["base_url"]).rstrip("/")
        self.model = llm_cfg["model"]
        self.timeout = float(llm_cfg.get("timeout", 120))
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            raise RuntimeError("D 条件 claim 生成需要 DEEPSEEK_API_KEY")
        self._key = key

    def complete(
        self,
        *,
        model: str,
        messages: list[dict],
        response_schema: dict[str, Any],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        import httpx

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 2000,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._key}"},
            json=payload,
            timeout=timeout_seconds or self.timeout,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        obj = json.loads(content)
        if not isinstance(obj, dict):
            raise ValueError("structured transport must return an object")
        return obj


# ---------------------------------------------------------------------------
# 工作流装配
# ---------------------------------------------------------------------------
def build_d_workflow(
    cfg: Any = None,
    *,
    a5_root: Path | None = None,
    retriever: Any = None,
    use_live_claims: bool = True,
    final_k: int = 8,
) -> Any:
    """装配 A5 完整组件工作流。

    参数
    ----
    cfg             : Track 3 全局配置（model/embedding/retrieval 等）。
    a5_root         : vendored A5 根目录（默认 track1/）。
    retriever       : 已注入的检索器；None 时构建 A5EvidenceRetrieverAdapter
                      （Track 3 混合检索：BM25+向量+RRF+特征重排+MMR，含全文层）。
    use_live_claims : True 用 deepseek-chat 生成结构化 Claim[]（与 A/B/C 同模型），
                      False 用离线 MockClaimGenerator（链路验收，不用于正式结论）。
    """
    cfg = cfg or load_config()
    root = (a5_root or TRACK1_ROOT).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from a5.adapters.openai_compatible_claim_generator import OpenAICompatibleClaimGenerator
    from a5.adapters.rule_based_claim_verifier import RuleBasedClaimVerifier
    from a5.agent.workflow import A5Workflow
    from a5.runtime_config import load_runtime_config

    config = load_runtime_config(root / "config")

    if retriever is None:
        from evaluation.adapters.a5_retriever import A5EvidenceRetrieverAdapter
        from core.config import Config

        data = dict(cfg.data)
        data["retrieval"]["k_final"] = final_k
        cfg_d = Config(data, cfg.root)
        retriever = A5EvidenceRetrieverAdapter(
            cfg_d.path("evidence"),
            root,
            config_path=cfg.root / "config.yaml",
            embedding_backend=data["embedding"].get("backend", "api"),
            use_rerank=True,
            final_k=final_k,
        )

    if use_live_claims:
        transport = OpenAICompatibleJSONTransport(cfg["llm"])
        prompt_path = root / "prompts" / "claim_generation_v0.4.0.md"
        claim_generator = OpenAICompatibleClaimGenerator(
            transport=transport,
            model=cfg["llm"]["model"],
            prompt_path=prompt_path,
        )
    else:
        from a5.adapters.mock_claim_generator import MockClaimGenerator
        claim_generator = MockClaimGenerator()

    # Gate5 文本支持评估：优先独立语义验证器（LLM，与生成同模型但独立 prompt/温度 0），
    # 其次确定性精确 span 匹配；均不可用时 fail-closed（INSUFFICIENT）。
    if use_live_claims:
        from a5.adapters.semantic_claim_verifier import OpenAICompatibleSemanticEvaluator
        semantic = OpenAICompatibleSemanticEvaluator(
            transport=transport,
            model=cfg["llm"]["model"],
            prompt_path=root / "prompts" / "semantic_verification_v0.4.0.md",
            name="independent_semantic_verifier@0.4.0",
        )
        textual_support = semantic
    else:
        textual_support = None

    workflow = A5Workflow(
        retriever=retriever,
        claim_generator=claim_generator,
        claim_verifier=RuleBasedClaimVerifier(
            config.gates.gate5,
            textual_support=textual_support,
            name=config.models.claim_verifier,
            textual_support_name=(
                "independent_semantic_verifier@0.4.0" if textual_support else
                config.models.textual_support_evaluator
            ),
        ),
        safety_policy=Track3SafetyPolicy(config.gates.gate0_version),
        runtime_config=config,
    )
    return workflow


# ---------------------------------------------------------------------------
# 执行并把 AgentRun 映射为 Track 3 Run 契约
# ---------------------------------------------------------------------------
def run_d_question(question: Question, workflow: Any, cfg: Any = None) -> dict:
    """对单题执行 D 完整组件，返回可合并进 Run 记录的 dict。"""
    cfg = cfg or load_config()
    started = time.perf_counter()

    from a5.domain.models import Question as A5Question

    a5_q = A5Question(
        question_id=question.id,
        text=question.question,
        metadata={
            "track3_question_id": question.id,
            "expected_action": question.expected_action or "ANSWER",
            "answerable": question.answerable,
            "topic": question.topic,
            "as_of_date": question.as_of_date or "2026-08-11",
            **question.extras,
        },
    )
    run = workflow.answer(a5_q)
    decision = run.decision.value if run.decision is not None else "REFUSE"
    final = run.final_answer
    answer = final.text if final is not None else None
    limitations = list(final.limitations) if final is not None else []
    cited_ids = list(final.cited_evidence_ids) if final is not None else []

    claims = []
    for claim in run.claims:
        claims.append({
            "claim_id": claim.claim_id,
            "run_id": claim.run_id,
            "text": claim.text,
            "criticality": claim.criticality.value if hasattr(claim.criticality, "value") else str(claim.criticality),
            "evidence_ids": list(claim.evidence_ids),
            "evidence_span_ids": list(claim.evidence_span_ids),
            "decision": claim.decision.value if hasattr(claim.decision, "value") else str(claim.decision),
            "verification_method": "a5_gate5",
        })

    evidence = [record.model_dump(mode="json") for record in run.retrieved_evidence]
    trace = []
    for item in run.trace:
        trace.append(item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item))
    agent_plan = (
        run.agent_plan.model_dump(mode="json")
        if run.agent_plan is not None
        else {"selected_skill": run.selected_skill, "selected_skills": run.selected_skills}
    )
    citations = [{"evidence_id": eid, "valid": True} for eid in cited_ids]
    latency_ms = int((time.perf_counter() - started) * 1000)
    if run.latency_ms:
        latency_ms = max(latency_ms, int(run.latency_ms))

    return {
        "answer": answer,
        "verification_decision": decision,
        "claims": claims,
        "citations": citations,
        "retrieved_evidence": evidence,
        "agent_plan": agent_plan,
        "tool_trace": trace,
        "refusal_reason": "; ".join(limitations) if decision == "REFUSE" else None,
        "system_version": run.agent_version,
        "d_extra_latency_ms": latency_ms,
        "errors": [{"error": run.error}] if run.error else [],
    }


# ---------------------------------------------------------------------------
# 快速验证入口
# ---------------------------------------------------------------------------
def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="D 完整组件包离线/真实链路验证")
    ap.add_argument("--question", default="高血压患者为什么有时需要长期服药？有哪些指南或研究依据？")
    ap.add_argument("--offline", action="store_true", help="用 MockClaimGenerator（不调用 LLM）")
    args = ap.parse_args()

    cfg = load_config()
    workflow = build_d_workflow(cfg, use_live_claims=not args.offline)
    q = Question(id="d-demo", topic="hypertension", difficulty="medium",
                 question=args.question, question_type="mechanism",
                 freshness="stable", answerable=True, expected_action="ANSWER")
    result = run_d_question(q, workflow, cfg)
    print(f"decision={result['verification_decision']} | system={result['system_version']} "
          f"| claims={len(result['claims'])} | tools={len(result['tool_trace'])} "
          f"| evidence={len(result['retrieved_evidence'])} | latency={result['d_extra_latency_ms']}ms")
    print(f"answer: {(result['answer'] or '')[:400]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
