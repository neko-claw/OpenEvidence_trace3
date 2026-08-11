"""检索/重排单元测试（离线）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retrieval.rrf import rrf_merge
from retrieval.bm25 import BM25Index
from retrieval.rerank import _evidence_level_score, _freshness_score, _source_quality_score, _text_sim
from core.dataclasses import Evidence


def test_rrf_merge():
    l1 = [("a", 1.0), ("b", 0.5)]
    l2 = [("b", 1.0), ("c", 0.9)]
    merged = rrf_merge([l1, l2], k=60)
    assert merged[0][0] == "b"   # 两列表都出现 -> 最高


def test_bm25_match():
    docs = [
        {"id": "1", "title": "高血压治疗指南", "text": "血压大于等于140/90为高血压"},
        {"id": "2", "title": "血脂管理", "text": "低密度脂蛋白胆固醇目标"},
        {"id": "3", "title": "糖尿病饮食", "text": "血糖控制与饮食干预"},
        {"id": "4", "title": "甲状腺功能检查", "text": "甲功异常对代谢影响"},
    ]
    idx = BM25Index(docs)
    hits = idx.search("高血压 治疗", k=5)
    assert hits and hits[0][0] == "1"


def test_bm25_identifier():
    """医学术语/标识符走词法检索"""
    docs = [
        {"id": "pmid_1001", "title": "statin trial", "text": "LDL reduction 50 percent"},
        {"id": "pmid_2002", "title": "diet study", "text": "mediterranean diet olive oil"},
        {"id": "pmid_3003", "title": "hypertension cohort", "text": "blood pressure variability"},
        {"id": "pmid_4004", "title": "lipid guideline", "text": "cholesterol target management"},
    ]
    idx = BM25Index(docs)
    hits = idx.search("statin LDL", k=5)
    assert hits[0][0] == "pmid_1001"


def test_evidence_level_score():
    assert _evidence_level_score("guideline") > _evidence_level_score("rct") > _evidence_level_score("unknown")


def test_freshness_score():
    assert _freshness_score("2024-01-01", "stable") > _freshness_score("2010-01-01", "stable")


def test_source_quality():
    assert _source_quality_score("guideline") > _source_quality_score("wiki")


def test_text_sim():
    assert _text_sim("完全相同的内容", "完全相同的内容") > 0.5
    assert _text_sim("aaaa", "bbbb") == 0.0
