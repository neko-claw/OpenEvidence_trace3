"""答案生成：A/B/C/D 共用安全层（引用白名单 + 拒答判定）"""
from __future__ import annotations

import re
from typing import Optional

from core.config import Config
from core.dataclasses import Question, Run
from core.llm import LLMClient
from generation import prompts
from generation.citation_check import (check_citation_whitelist, check_search_citation_whitelist,
                                       find_invalid_urls, extract_citations,
                                       extract_search_citations, split_claims)


class AnswerGenerator:
    def __init__(self, cfg: Config, llm: LLMClient):
        self.cfg = cfg
        self.llm = llm
        self.gen_cfg = cfg["generation"]

    def generate(self, q: Question, condition: str,
                 retrieved: list[dict], features: list[dict]) -> tuple[Run, list[dict]]:
        """生成 + 校验，返回 (Run, features)。"""
        run = Run(question_id=q.id, condition=condition,
                  model=self.llm.model,
                  prompt_version=self.gen_cfg["prompt_version"],
                  index_version="",  # 由实验 runner 填充
                  retrieved_evidence=retrieved)

        if condition == "A":
            msgs = prompts.build_prompt_a(q)
        elif condition == "A2":
            msgs = prompts.build_prompt_a2(q, retrieved)
        else:
            msgs = prompts.build_prompt_bcd(q, retrieved)

        # 拒答预判：检索质量门（基于 RRF 分而非未归一化的加权分）。
        # A/A2 条件无项目检索，跳过；真正“证据不足”题的拒答由生成模型处理。
        if condition in ("B", "C", "D") and features:
            best_rrf = max(f.get("rrf", f.get("semantic", 0.0)) for f in features)
            if best_rrf < self.gen_cfg["retrieval_quality_threshold"]:
                run.answer = self._abstain_text(q)
                run.verification_decision = "REFUSE"
                run.agent_plan.append(
                    f"abstain: best_rrf={best_rrf:.4f} < threshold")
                return run, features

        # A2 条件：搜索零结果时直接拒答（预算内确实没搜到，不补写结论）
        if condition == "A2" and not retrieved:
            run.answer = self._abstain_text(q)
            run.verification_decision = "REFUSE"
            run.agent_plan.append("abstain: general search returned 0 results")
            return run, features

        text, meta = self.llm.chat(msgs)
        run.answer = text
        run.latency_ms = meta["latency_ms"]
        run.input_tokens = meta["input_tokens"]
        run.output_tokens = meta["output_tokens"]
        run.estimated_cost = meta["estimated_cost"]
        run.attempt_count = meta.get("attempts", 1)  # 重试日志

        # ---- 引用白名单校验（B/C/D 用 [E#]；A2 用 [S#]；A 不允许任何引用） ----
        n_ev = len(retrieved)
        if condition == "A":
            bad_e = extract_citations(text)
            bad_s = extract_search_citations(text)
            invalid_urls = find_invalid_urls(text)
            if bad_e or bad_s or invalid_urls:
                run.verification_decision = "WARN"
                run.error = (f"A 条件出现引用或 URL: E={bad_e} S={bad_s} "
                             f"urls={invalid_urls}")
            run.citations = []
        elif condition == "A2":
            _, invalid_s = check_search_citation_whitelist(text, n_ev)
            allowed_urls = {r.get("url", "") for r in retrieved}
            bad_urls = find_invalid_urls(text, allowed=allowed_urls)
            if invalid_s or bad_urls:
                run.verification_decision = "WARN"
                run.error = (f"A2 非法引用(超出搜索结果范围): {invalid_s} "
                             f"非白名单 URL: {bad_urls}")
            run.citations = [f"S{c}" for c in extract_search_citations(text)]
        else:
            _, invalid = check_citation_whitelist(text, n_ev)
            if invalid:
                run.verification_decision = "WARN"
                run.error = f"非法引用编号(超出本次证据范围): {invalid}"
            run.citations = extract_citations(text)
        # claims 留痕（P0-2）：主终点 rubric_keypoint_score / unsupported_critical_claim_rate 依赖
        # decision 按引用编号存在性判定（v0.1 口径）：A 无证据上下文 -> pending；其余 supported/insufficient
        if condition == "A2":
            run.claims = split_claims(run.answer, run.run_id, n_search=n_ev)
        elif condition == "A":
            run.claims = split_claims(run.answer, run.run_id)
        else:
            run.claims = split_claims(run.answer, run.run_id, n_evidence=n_ev)
        return run, features

    def _abstain_text(self, q: Question) -> str:
        return (
            f"## 结论摘要\n本次检索未找到足以回答该问题的可靠证据，因此不做结论。\n\n"
            f"## 局限与边界\n检索缺口可能来自数据范围（高血压/血脂主题库）或证据质量不足。"
            f"如需进一步调研，建议补充指南全文与最新临床试验。\n\n"
            f"（仅供教学研究，不用于临床诊疗）"
        )
