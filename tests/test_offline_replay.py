"""离线回放端到端测试（P0-4：无 API key 链路验收；不依赖 LLM/网络）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_config
from core.dataclasses import Question
from core.llm import OfflineLLM
from evaluation.baseline import run_condition
from retrieval.index import EvidenceStore


def _small_store(cfg) -> EvidenceStore:
    store = EvidenceStore(cfg)
    store.add_evidence({"id": "e1", "source_type": "pubmed", "title": "高血压指南 2024",
                        "text": "诊室血压大于等于140/90mmHg诊断为高血压，需非同日多次测量确认。",
                        "published_at": "2024-01-01", "evidence_level": "guideline"})
    store.add_evidence({"id": "e2", "source_type": "clinicaltrial", "title": "新型降压药试验",
                        "text": "一项多中心随机对照试验评估新型降压药对心血管结局的影响。",
                        "published_at": "2023-05-01", "evidence_level": "rct"})
    store.add_evidence({"id": "e3", "source_type": "pubmed", "title": "他汀与 LDL-C",
                        "text": "他汀类药物显著降低低密度脂蛋白胆固醇与心血管事件风险。",
                        "published_at": "2020-03-01", "evidence_level": "systematic_review"})
    store.build_index(emb_backend="fallback")
    return store


def _q(qid: str = "q1") -> Question:
    return Question(id=qid, topic="hypertension", difficulty="easy",
                    question="高血压患者的诊室血压诊断标准是多少？",
                    question_type="guideline", freshness="stable")


def test_offline_condition_a_no_citations():
    cfg = load_config()
    run = run_condition(_q(), "A", cfg, store=None, llm=OfflineLLM())
    assert run.status == "ok" and run.error == ""
    assert "结论摘要" in run.answer
    assert run.citations == []
    assert run.verification_decision in ("PASS", "WARN")
    assert run.attempt_count == 1


def test_offline_condition_b_claims_and_candidates():
    cfg = load_config()
    store = _small_store(cfg)
    run = run_condition(_q(), "B", cfg, store=store, llm=OfflineLLM())
    assert run.status == "ok"
    assert run.answer
    assert run.index_version != "none"
    assert run.candidate_ids, "B 条件应落盘 RRF 初检候选"
    assert run.claims, "P0-2: run.claims 应有列表项拆分"
    # OfflineLLM 引用上下文中出现的 [E#]，claims 应绑定引用
    assert any(c["evidence_ids"] for c in run.claims), "claims 应绑定 [E#] 引用"
    assert run.tool_trace and "cache_hit" in run.tool_trace[0]


def test_offline_condition_a2_search_snapshot():
    cfg = load_config()
    run = run_condition(_q(), "A2", cfg, store=None, llm=OfflineLLM())
    assert run.status == "ok"
    trace = next(t for t in run.tool_trace if t.get("tool") == "general_search")
    assert trace["searches_used"] <= cfg["a2"]["max_searches"]
    assert trace["snapshot"]
    assert run.index_version == "none"
    assert run.citations, "A2 回答应引用 [S#]"
    assert all(c.startswith("S") for c in run.citations)


def test_offline_condition_e_derived_from_b_baseline():
    cfg = load_config()
    store = _small_store(cfg)
    run_b = run_condition(_q(), "B", cfg, store=store, llm=OfflineLLM())
    run_e = run_condition(_q(), "E", cfg, store=store, llm=OfflineLLM())
    assert run_e.tool_trace[0]["derived_from"] == "B_baseline_rerank_false"
    assert run_e.tool_trace[0]["degraded"] is True
    # E 候选 <= B 候选（top-k 减半）
    assert len(run_e.retrieved_evidence) <= len(run_b.retrieved_evidence)


def test_offline_experiment_smoke_writes_jsonl():
    from evaluation import experiment as exp
    cfg = load_config()
    store = _small_store(cfg)
    runs = exp.run_experiment(cfg, [_q("q1"), _q("q2")], ["A", "B", "A2", "E"],
                              store=store, offline=True, tag="test_offline")
    assert len(runs) == 8
    for r in runs:
        assert r.config_hash, "config_hash 应记录"
        assert r.provider_fingerprint.startswith("offline")
        assert r.model_snapshot == "offline-mock"
        assert r.run_id
        assert r.status == "ok"
