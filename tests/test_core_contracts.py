"""契约测试：确定性指标与引用白名单（不依赖 LLM）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.metrics import (hit_at_k, mrr, recall_at_k, ndcg_at_k,
                                citation_precision as cp, claim_support_rate,
                                unsupported_claim_rate, abstention_quality)
from generation.citation_check import (extract_citations, check_citation_whitelist,
                                       citation_precision as ccp,
                                       check_claims_supported, find_invalid_urls,
                                       split_claims)
from core.dataclasses import Question


def test_hit_at_k():
    assert hit_at_k(["a", "b", "c"], {"b"}, 2) == 1.0
    assert hit_at_k(["a", "b", "c"], {"x"}, 2) == 0.0


def test_mrr():
    assert abs(mrr(["a", "b", "c"], {"b"}) - 0.5) < 1e-9
    assert mrr(["a", "b"], {"x"}) == 0.0


def test_recall_at_k():
    assert recall_at_k(["a", "b", "c"], {"a", "x"}, 2) == 0.5


def test_ndcg_at_k():
    assert abs(ndcg_at_k(["a", "b"], {"a"}, 2) - 1.0) < 1e-9


def test_citation_precision_metrics():
    assert cp([1, 2], [3]) == 2 / 3


def test_claim_support():
    claims = [
        {"decision": "supported"},
        {"decision": "supported"},
        {"decision": "unsupported"},
    ]
    assert abs(claim_support_rate(claims) - 2 / 3) < 1e-9
    assert abs(unsupported_claim_rate(claims) - 1 / 3) < 1e-9


def test_abstention_quality():
    assert abstention_quality("insufficient", "REFUSE") == 1.0
    assert abstention_quality("guideline", "REFUSE") == 0.0
    assert abstention_quality("guideline", "PASS") == 1.0


def test_extract_citations():
    assert extract_citations("结论 [E1][E3] 支持") == ["1", "3"]


def test_whitelist():
    text = "引用 [E1] 和 [E5]"
    valid, invalid = check_citation_whitelist(text, n_evidence=3)
    assert valid == [1]
    assert invalid == [5]


def test_whitelist_precision():
    assert ccp("引用 [E1][E2]", n_evidence=2) == 1.0
    assert ccp("引用 [E9]", n_evidence=2) == 0.0


def test_claims_supported_rate():
    claims = [{"text": "降压降低风险 [E1]"}, {"text": "无引用结论"}]
    rate, unsup = check_claims_supported(claims, "", n_evidence=2)
    assert rate == 0.5
    assert unsup == 0.5


def test_find_invalid_urls():
    assert find_invalid_urls("见 https://pubmed.ncbi.nlm.nih.gov/x 的来源") == \
        ["https://pubmed.ncbi.nlm.nih.gov/x"]
    assert find_invalid_urls("无链接") == []


# ---------- 契约对齐：B1 蓝图 Question 格式 <-> B3 运行器 Question（P0a） ----------

def test_question_blueprint_format_loads():
    """B2 正式题将按 B1 蓝图格式（无 freshness、key_points 在顶层）交付，
    必须能被运行器 Question 加载，且 key_points 映射进 rubric 供 judge 使用。"""
    blueprint = {
        "id": "DEV-S01", "split": "DEV", "dataset_pack": "DEV",
        "topic": "hypertension", "question_type": "stable_knowledge_mechanism",
        "difficulty": 2, "language": "zh",
        "question": "长期血压升高为什么会导致左心室肥厚？",
        "answerable": True, "as_of_date": "2024-06-01",
        "source_provenance": "B1 蓝图样例", "source_group_id": "DEV-S01",
        "gold_source_ids": [], "key_points": ["压力负荷致心肌细胞肥大", "RAAS/交感激活"],
        "rubric_version": "v0.1", "note": "样例",
    }
    q = Question.from_dict(blueprint)
    # 蓝图格式无 freshness -> 用默认值，不抛 TypeError
    assert q.freshness == "stable"
    assert q.split == "DEV" and q.dataset_pack == "DEV"
    assert q.answerable is True and q.as_of_date == "2024-06-01"
    assert q.source_group_id == "DEV-S01"
    # key_points 顶层字段 -> rubric.key_points（judge 消费路径）
    assert q.rubric.get("key_points") == ["压力负荷致心肌细胞肥大", "RAAS/交感激活"]
    # 其余未识别字段保留，不静默丢弃
    assert q.extras.get("source_provenance") == "B1 蓝图样例"
    assert q.extras.get("rubric_version") == "v0.1"


def test_question_blueprint_fields_are_preserved():
    q = Question.from_dict({
        "id": "DEV-S01", "split": "DEV", "dataset_pack": "DEV",
        "topic": "hypertension", "question_type": "mechanism",
        "difficulty": 2, "question": "为什么长期血压升高会造成心肌重构？",
        "answerable": True, "as_of_date": "2026-08-01",
        "source_group_id": "source-01", "gold_source_ids": [],
        "key_points": ["压力负荷"], "language": "zh-CN",
        "rubric_version": "rubric-v0.1",
    })
    assert q.freshness == "stable"
    assert q.split == "DEV" and q.dataset_pack == "DEV"
    assert q.answerable is True and q.source_group_id == "source-01"
    assert q.rubric["key_points"] == ["压力负荷"]
    assert q.extras["rubric_version"] == "rubric-v0.1"


def test_question_runtime_format_roundtrip():
    """运行器题集格式（rubric 内嵌 key_points）round-trip 不受影响。"""
    d = {"id": "q01", "topic": "hypertension", "difficulty": "easy",
         "question": "高血压为什么需要长期服药？", "question_type": "mechanism",
         "freshness": "stable", "gold_source_ids": [],
         "rubric": {"key_points": ["慢性病需长期管理"]}}
    q = Question.from_dict(d)
    assert q.freshness == "stable"
    assert q.rubric["key_points"] == ["慢性病需长期管理"]
    assert q.to_dict()["id"] == "q01"


# ---------- claims decision：主终点确定性路径（P0b） ----------

def test_split_claims_decision_supported_with_valid_citation():
    answer = "## 证据说明\n- 血压达标可降低风险 [E1]。\n- 无引用的结论。"
    claims = split_claims(answer, "run1", n_evidence=3)
    assert claims[0]["decision"] == "supported"
    assert claims[0]["evidence_ids"] == ["E1"]
    assert claims[0]["verification_method"] == "citation_existence + rule_criticality"
    # 有证据上下文但无有效引用 -> insufficient
    assert claims[1]["decision"] == "insufficient"


def test_split_claims_decision_out_of_range_is_insufficient():
    answer = "## 证据说明\n- 结论 [E9] 超出证据范围。"
    claims = split_claims(answer, "run1", n_evidence=3)
    assert claims[0]["decision"] == "insufficient"


def test_split_claims_a_condition_stays_pending():
    """A 条件无证据上下文：claims 不强制引用，decision 保持 pending（留给 judge/人工）。"""
    answer = "## 证据说明\n- 基于模型知识作答。"
    claims = split_claims(answer, "run1")
    assert claims[0]["decision"] == "pending"


def test_claims_support_rate_usable_from_split_claims():
    """P0b：metrics.claim_support_rate 对 split_claims 输出不再恒为 0。"""
    answer = "## 证据说明\n- 有引用结论 [E1]。\n- 这是无引用的补充说明结论。"
    claims = split_claims(answer, "run1", n_evidence=2)
    assert abs(claim_support_rate(claims) - 0.5) < 1e-9
    assert abs(unsupported_claim_rate(claims) - 0.5) < 1e-9


def test_split_claims_has_condition_aware_decisions():
    claims = split_claims("- 有效引用 [E1]\n- 这是一条没有引用的补充结论。", "run-1", n_evidence=2)
    assert [claim["decision"] for claim in claims] == ["supported", "insufficient"]
    assert claims[0]["verification_method"] == "citation_existence + rule_criticality"
    assert split_claims("- 这是一条没有检索上下文的主张。", "run-2")[0]["decision"] == "pending"


def test_detect_refusal_gate():
    """Gate 6 简化版：回答主体为拒答/证据不足 -> REFUSE；局限段出现不算。"""
    from generation.citation_check import detect_refusal
    # 开头即拒答
    is_r, reason = detect_refusal(
        "## 结论摘要\n本次检索未找到足以回答该问题的可靠证据，因此不做结论。\n\n## 局限与边界\n检索缺口...",
        has_context=True)
    assert is_r and "未找到" in reason
    # 有实质回答 + 局限段提到证据年份 -> 不算拒答
    is_r2, _ = detect_refusal(
        "## 结论摘要\n证据表明降压可降低心血管事件风险 [E1]。\n## 局限与边界\n证据年份有限。",
        has_context=True)
    assert not is_r2
    # 空回答 -> 拒答
    assert detect_refusal("", has_context=True)[0]
    # closed-book A 不强制
    assert not detect_refusal("基于我的知识，目前证据有限。", has_context=False)[0]


def test_split_claims_criticality_and_real_ids():
    """v0.2：criticality 规则判定 + evidence_ids 映射为真实证据 ID。"""
    claims = split_claims(
        "- 他汀相关肌病风险与剂量相关 [E1]。\n- 生活方式干预可降低 LDL-C [E2]。",
        "run-x", n_evidence=2,
        evidence_records=[{"id": "pmid:111"}, {"id": "pmid:222"}])
    assert claims[0]["criticality"] == "critical"       # 含“剂量/风险”
    assert claims[0]["evidence_ids"] == ["pmid:111"]     # E1 -> 真实 ID
    assert claims[1]["criticality"] == "important"
    assert claims[1]["evidence_ids"] == ["pmid:222"]
    # 无 evidence_records 时保留 E# 编号（兼容旧调用）
    claims2 = split_claims("- 结论 [E1]。", "run-y", n_evidence=2)
    assert claims2[0]["evidence_ids"] == ["E1"]


def test_detect_refusal_with_citations_is_warn_not_pass():
    """Gate 6：拒答+引用 -> WARN；拒答无引用 -> REFUSE；实质回答 -> PASS。"""
    from generation.answer import AnswerGenerator
    from generation.citation_check import detect_refusal
    # 拒答 + 引用 -> is_refusal=True
    is_r, _ = detect_refusal(
        "## 结论摘要\n现有证据不支持该结论，无法给出确定剂量 [E1]。",
        has_context=True)
    assert is_r
    # 局限段出现"证据年份有限"不算拒答
    assert not detect_refusal(
        "## 结论摘要\n降压可降低事件风险 [E1]。\n## 局限与边界\n证据年份有限。",
        has_context=True)[0]
    # 新增标记：现有证据不支持
    assert detect_refusal(
        "## 结论摘要\n现有证据不支持将血压稳定降至 130 以下的确定性结论。",
        has_context=True)[0]
