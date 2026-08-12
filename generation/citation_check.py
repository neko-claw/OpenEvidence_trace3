"""引用校验：白名单 + 支持性检查（简化版，作为 P0 基础）"""
from __future__ import annotations

import re
from typing import Any, Optional

from core.dataclasses import Claim


# 语义拒答检测（Gate 6 简化版：回答主体明确表示“无法回答/证据不足/检索缺口”时
# 判定 REFUSE；部分拒答由 judge/rubric 进一步处理）
REFUSAL_MARKERS = [
    # 中文
    "无法回答", "不能回答", "无法得出", "无法给出", "没有足够证据", "证据不足",
    "检索缺口", "未找到", "未检索到", "没有直接证据", "无法确定", "不能确定",
    "无法判断", "不做结论", "不能得出结论", "无法得出结论", "不足以回答",
    "无法基于", "无法给出任何", "现有证据无法", "本次检索未找到", "现有证据不支持",
    # 英文
    "cannot answer", "cannot be answered", "insufficient evidence",
    "no evidence", "not enough evidence", "unable to determine",
    "cannot be determined", "no direct evidence", "cannot conclude",
]


def detect_refusal(text: str, *, has_context: bool, head_chars: int = 350) -> tuple[bool, str]:
    """语义拒答检测：回答主体（开头段）为拒答/证据不足时返回 (True, reason)。

    规则：
    - 空回答 -> 拒答；
    - 拒答标记出现在回答开头 head_chars 字符内 -> 判拒答；
    - 只有局限段出现标记（如“证据年份有限”）不算拒答；
    - has_context=False（closed-book A）时只对空回答判拒答，模型诚实的
      “没有把握”留给人/评分器判断，不在此强制。
    """
    t = (text or "").strip()
    if not t:
        return True, "empty answer"
    if not has_context:
        return False, ""
    head = t[:head_chars]
    hits = [m for m in REFUSAL_MARKERS if m in head]
    if hits:
        return True, f"refusal markers in opening: {hits[:3]}"
    return False, ""


def extract_citations(text: str) -> list[str]:
    """提取 [E1] [E2] 形式的引用编号"""
    return sorted(set(re.findall(r"\[E(\d+)\]", text)))


def extract_search_citations(text: str) -> list[str]:
    """提取 A2 条件 [S1] [S2] 形式的搜索引用编号（与 [E#] 严格区分）"""
    return sorted(set(re.findall(r"\[S(\d+)\]", text)))


def check_citation_whitelist(text: str, n_evidence: int) -> tuple[list[int], list[int]]:
    """返回 (合法编号列表, 非法编号列表)。非法 = 超出本次检索证据范围"""
    cites = [int(c) for c in extract_citations(text)]
    valid = [c for c in cites if 1 <= c <= n_evidence]
    invalid = [c for c in cites if c not in valid]
    return valid, invalid


def check_search_citation_whitelist(text: str, n_results: int) -> tuple[list[int], list[int]]:
    """A2 条件 [S#] 白名单检查。非法 = 超出本次搜索结果范围"""
    cites = [int(c) for c in extract_search_citations(text)]
    valid = [c for c in cites if 1 <= c <= n_results]
    invalid = [c for c in cites if c not in valid]
    return valid, invalid


def citation_precision(text: str, n_evidence: int) -> float:
    """被引用证据中真正存在于本次上下文的比例"""
    valid, invalid = check_citation_whitelist(text, n_evidence)
    total = len(valid) + len(invalid)
    if total == 0:
        return 0.0
    return len(valid) / total


def split_claims(answer: str, run_id: str, n_evidence: int | None = None,
                 n_search: int | None = None,
                 evidence_records: list[dict] | None = None) -> list[dict]:
    """把回答按行拆成候选 Claim（P0 简化：按"证据说明"章节的列表项拆分，绑定 [E#]/[S#] 引用）。

    正式实现应由生成模型返回结构化 Claim[]；此处为确定性回退，保证主终点可算。

    decision 判定（v0.1 口径 = 引用编号存在性，报告需披露）：
    - supported    ：claim 至少含一个有效 [E#]（1..n_evidence）或 [S#]（1..n_search）
    - insufficient ：有证据上下文但 claim 无有效引用（相关但不支持 / 未引用）
    - pending      ：无证据上下文（A 条件不强制引用，留给 judge/人工判定）

    criticality（v0.2 增强）：含高风险/安全/剂量/结局表述的 claim 标 critical，
    支撑主结论且带引用的标 important；默认 important。
    evidence_ids（v0.2 增强）：传入 evidence_records 时映射为真实证据 ID
    （如 pmid:xxx / nct:NCTxxx），供 citation_precision/coverage 按文献级去重。

    verification_method 恒为 "citation_existence + rule_criticality"；
    语义支持性（Gate 5）由 B5/judge 补充。
    """
    def _valid(ids: list[str], n: int | None) -> bool:
        """ids 为非空且都在 1..n 范围内（n 为 None 时不限制）。extract_citations 返回字符串编号。"""
        if not ids or n is None:
            return bool(ids)
        return all(1 <= int(i) <= n for i in ids)

    # 高风险/安全相关表述 -> critical claim（供 unsupported_critical_claim_rate 使用）
    CRITICAL_MARKERS = [
        "剂量", "死亡", "致死", "致命", "禁忌", "停药", "出血", "横纹肌溶解",
        "心肌梗死", "卒中", "中风", "肾功能衰竭", "严重", "高钾", "低血压",
        "dose", "mortality", "fatal", "contraindication", "stroke",
        "myocardial infarction", "rhabdomyolysis", "bleeding", "hyperkalemia",
    ]

    has_ctx = (n_evidence or 0) > 0 or (n_search or 0) > 0
    claims = []
    n = 0
    for line in answer.splitlines():
        line = line.strip()
        if line.startswith(("-", "*")) and len(line) > 8:
            n += 1
            text = line.lstrip("-* ")
            e_ids = extract_citations(text)
            s_ids = extract_search_citations(text)
            if _valid(e_ids, n_evidence) or _valid(s_ids, n_search):
                decision = "supported"
            elif has_ctx:
                decision = "insufficient"
            else:
                decision = "pending"
            # criticality：含风险/安全/结局关键词 -> critical，其余 important
            critical = any(m in text for m in CRITICAL_MARKERS)
            criticality = "critical" if critical else "important"
            # evidence_ids：优先映射为真实证据 ID；无映射时保留 E#/S# 编号
            mapped: list[str] = []
            if evidence_records:
                for i in e_ids:
                    idx = int(i) - 1
                    if 0 <= idx < len(evidence_records):
                        mapped.append(str(evidence_records[idx].get("id", f"E{i}")))
            mapped += [f"S{i}" for i in s_ids]
            if not mapped:
                mapped = [f"E{i}" for i in e_ids] + [f"S{i}" for i in s_ids]
            claims.append(Claim(
                claim_id=f"{run_id}_c{n}", run_id=run_id, text=text,
                criticality=criticality,
                evidence_ids=mapped,
                decision=decision,
                verification_method="citation_existence + rule_criticality",
            ).to_dict())
    return claims


def check_claims_supported(claims: list[dict], text: str, n_evidence: int) -> tuple[float, float]:
    """简化支持性检查：
    - claim_support_rate: 带引用且引用合法的主张比例
    - unsupported_claim_rate: 无引用或引用非法的比例
    完整版需做 Evidence span 对齐 + NLI，见实施规划 §5.7 Gate 5。
    """
    if not claims:
        return 0.0, 1.0
    supported = 0
    for c in claims:
        cites = extract_citations(c["text"])
        if cites and all(1 <= int(x) <= n_evidence for x in cites):
            supported += 1
    rate = supported / len(claims)
    return rate, 1.0 - rate


def find_invalid_urls(text: str, allowed: Optional[set[str]] = None) -> list[str]:
    """找出回答中出现的真实域名 URL。

    allowed 非空时作为白名单（A2 条件：URL 必须来自搜索结果快照）。
    """
    urls = re.findall(r"https?://[^\s)\]]+", text)
    if allowed is not None:
        return [u for u in urls if u not in allowed]
    return urls
