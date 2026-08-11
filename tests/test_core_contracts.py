"""契约测试：确定性指标与引用白名单（不依赖 LLM）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evaluation.metrics import (hit_at_k, mrr, recall_at_k, ndcg_at_k,
                                citation_precision as cp, claim_support_rate,
                                unsupported_claim_rate, abstention_quality)
from generation.citation_check import (extract_citations, check_citation_whitelist,
                                       citation_precision as ccp,
                                       check_claims_supported, find_invalid_urls)


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
