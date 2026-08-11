"""B3 交付物测试：A2 通用搜索、Run 契约、引用校验、一致性审计（全部离线，不依赖 LLM/API）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_config
from core.dataclasses import Run
from evaluation.a2_search import search_general, SearchBudgetExceeded, GeneralSearchResult
from evaluation.consistency import audit_runs
from generation import prompts
from generation.citation_check import (extract_search_citations,
                                       check_search_citation_whitelist,
                                       extract_citations)


# ---------- 1. Run 契约（§3.1 对齐：B3 成本/重试日志字段） ----------

def test_run_contract_fields_exist():
    r = Run(question_id="q01", condition="B", model="m")
    for f in ("seed", "replicate", "config_hash", "dataset_version", "corpus_version",
              "provider_fingerprint", "model_snapshot", "cache_hits",
              "attempt_count", "status"):
        assert hasattr(r, f), f"Run 缺少契约字段 {f}"
    assert r.status == "ok"


def test_run_roundtrip_keeps_new_fields():
    r = Run(question_id="q01", condition="A2", seed=7, replicate=2,
            config_hash="abc", status="ok", attempt_count=1, cache_hits=1)
    d = r.to_dict()
    r2 = Run.from_dict(d)
    assert r2.seed == 7 and r2.replicate == 2 and r2.config_hash == "abc"
    assert r2.status == "ok" and r2.attempt_count == 1 and r2.cache_hits == 1


# ---------- 2. A2 通用搜索（mock provider，离线） ----------

def test_mock_search_returns_results_within_budget():
    cfg = load_config()
    results, meta = search_general("高血压的诊断标准是多少", cfg)
    assert meta["provider"] == "mock"
    assert 0 < len(results) <= cfg["a2"]["max_results_per_search"]
    assert meta["results_returned"] == len(results)
    assert meta["searches_used"] == 1
    assert meta["simulated"] is True
    assert meta["snapshot"], "应记录搜索响应快照"
    assert all(r.url.startswith("http") for r in results)
    assert all(r.simulated for r in results)


def test_mock_search_no_match_returns_empty_with_snapshot():
    cfg = load_config()
    results, meta = search_general("量子计算与火星探测", cfg)
    assert results == []
    assert meta["searches_used"] == 1
    assert meta["results_returned"] == 0
    assert meta["snapshot"], "零结果也必须保留响应快照"


def test_search_budget_never_exceeded():
    cfg = load_config()
    budget = {"provider": "mock", "max_searches": 1, "max_results_per_search": 2}
    results, meta = search_general("高血压 血脂 他汀 饮食 试验 指南", cfg, budget=budget)
    assert len(results) <= 2
    assert meta["searches_used"] <= 1


def test_search_unknown_provider_reports_error_not_crash():
    cfg = load_config()
    results, meta = search_general("高血压", cfg, budget={"provider": "nope"})
    assert results == []
    assert meta["error"], "未知 provider 应记录 error 而非崩溃"


# ---------- 3. A2 Prompt 与 [S#] 引用 ----------

def test_prompt_a2_uses_S_citation_and_no_E():
    from core.dataclasses import Question
    q = Question(id="q1", topic="hypertension", difficulty="easy",
                 question="高血压诊断标准？", question_type="guideline", freshness="stable")
    results = [GeneralSearchResult(url="https://x.example.com/1", title="网页一",
                                   snippet="摘要一", provider="mock", simulated=True)]
    msgs = prompts.build_prompt_a2(q, [r.to_dict() for r in results])
    user = msgs[1]["content"]
    assert "[S1]" in user
    assert "[E1]" not in user
    assert "通用搜索" in user


def test_search_citation_whitelist():
    text = "高血压标准是140/90 [S1]，同时 [S2] 和 [S9] 提及"
    assert extract_search_citations(text) == ["1", "2", "9"]
    valid, invalid = check_search_citation_whitelist(text, 2)
    assert valid == [1, 2] and invalid == [9]
    # [E#] 与 [S#] 互不干扰
    mixed = "证据 [E3] 与搜索 [S1]"
    assert extract_citations(mixed) == ["3"]
    assert extract_search_citations(mixed) == ["1"]


# ---------- 4. 一致性审计（B3 副责：交叉复核 B4） ----------

def _mk_run(qid: str, cond: str, **kw) -> Run:
    base = dict(question_id=qid, condition=cond, model="deepseek-chat",
                model_snapshot="deepseek-chat", prompt_version="v1",
                index_version="idx1", corpus_version="corp1",
                config_hash="cfg1", dataset_version="v0.1.1",
                answer="回答", status="ok")
    base.update(kw)
    return Run(**base)


def test_audit_passes_consistent_runs():
    runs = [
        _mk_run("q1", "B", retrieved_evidence=[{"id": "a"}, {"id": "b"}, {"id": "c"}]),
        _mk_run("q1", "C", retrieved_evidence=[{"id": "a"}, {"id": "b"}]),
    ]
    report = audit_runs(runs)
    assert report["summary"]["errors"] == 0
    assert report["summary"]["pass"] is True


def test_audit_detects_model_mismatch():
    runs = [
        _mk_run("q1", "B"),
        _mk_run("q1", "C", model="different-model"),
    ]
    report = audit_runs(runs)
    errs = [i for i in report["issues"] if i["check"] == "input_consistency"]
    assert any("model" in e["detail"] for e in errs)


def test_audit_detects_a2_budget_overflow():
    trace = [{"tool": "general_search", "searches_used": 5,
              "results_returned": 9, "snapshot": [{}]}]
    runs = [_mk_run("q1", "A2", index_version="none", corpus_version="none",
                    tool_trace=trace)]
    report = audit_runs(runs, a2_budget={"max_searches": 1, "max_results_per_search": 5})
    errs = [i for i in report["issues"] if i["check"] == "a2_budget"]
    assert len(errs) == 2


def test_audit_flags_e_outside_stress():
    # E 候选数（3）>= B 基线（2），劣化未生效 -> 应被标记
    runs = [
        _mk_run("q10", "E", tool_trace=[{"degraded": True}],
                retrieved_evidence=[{"id": "a"}, {"id": "b"}, {"id": "c"}]),
        _mk_run("q10", "B", retrieved_evidence=[{"id": "a"}, {"id": "b"}]),
    ]
    report = audit_runs(runs, q_splits={"q10": "test"})
    checks = {i["check"] for i in report["issues"]}
    assert "e_split" in checks
    assert "e_derivation" in checks
