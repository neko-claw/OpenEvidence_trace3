"""引用校验：白名单 + 支持性检查（简化版，作为 P0 基础）"""
from __future__ import annotations

import re
from typing import Any, Optional

from core.dataclasses import Claim


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


def split_claims(answer: str, run_id: str) -> list[dict]:
    """把回答按行拆成候选 Claim（P0 简化：按"证据说明"章节的列表项拆分，绑定 [E#]/[S#] 引用）。
    正式实现应由生成模型返回结构化 Claim[]；此处为确定性回退，保证主终点可算。"""
    claims = []
    n = 0
    for line in answer.splitlines():
        line = line.strip()
        if line.startswith(("-", "*")) and len(line) > 8:
            n += 1
            text = line.lstrip("-* ")
            e_ids = extract_citations(text)
            s_ids = extract_search_citations(text)
            claims.append(Claim(
                claim_id=f"{run_id}_c{n}", run_id=run_id, text=text,
                criticality="important",
                # P0 简化：evidence_ids 暂存引用编号（E1/S1），Score 阶段按 retrieved_evidence 映射回证据 ID
                evidence_ids=[f"E{i}" for i in e_ids] + [f"S{i}" for i in s_ids],
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
