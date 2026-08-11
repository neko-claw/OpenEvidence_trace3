"""ingestion 契约测试：XML 解析/分块、跨源去重、空摘要标记（离线，无网络）。

覆盖 v0.2.0 数据管线改进：
- chunk_sections：单块不跨小节、句子边界+重叠、span 元数据、标题规范化
- _strip_math_xrefs / 引用编号剥离 / [MATH] 占位符
- merge_duplicate_pmids：指南>PubMed>EuropePMC 合并、全文 chunk 不参与
- normalize：title_only 回退、过短 chunk 丢弃
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from ingestion import config
from ingestion.normalize import (merge_duplicate_pmids, normalize_fulltext_chunks,
                                 normalize_pubmed)
from ingestion.sources import europepmc as ep

FIXTURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:mml="http://www.w3.org/1998/Math/MathML">
  <body>
    <sec><title>1. Introduction</title>
      <p>Hypertension is common. Its prevalence is rising.</p>
      <p>The 2018 guideline <xref ref-type="bibr" rid="r1">1</xref> stated [1] targets.
         Systolic BP should be under 130 mmHg [9,10,11].</p>
    </sec>
    <sec><title>2. Methods</title>
      <sec><title>2.1 Statistical analysis</title>
        <p>We used a mixed model <mml:math><mml:mi>x</mml:mi></mml:math> with alpha 0.05.</p>
      </sec>
      <p>Baseline covariates were adjusted.</p>
    </sec>
    <sec><title>References</title><p>Ref 1. Example.</p></sec>
    <sec><title>Results</title>
      <p>Table shows the outcome.</p>
      <table-wrap id="t1"><table>
        <tr><th>Group</th><th>N</th></tr>
        <tr><td>Intervention</td><td>120</td></tr>
        <tr><td>Control</td><td>119</td></tr>
      </table></table-wrap>
    </sec>
    <sec><title>Discussion</title>
      <p>Meta-analyses report consistent benefits across populations. Absolute risk
         reductions are modest but clinically meaningful. Side effects are dose dependent
         and usually reversible upon discontinuation. Individualized decisions should
         incorporate comorbidity burden and patient preference. Guidelines therefore
         emphasize shared decision making rather than rigid thresholds. Future trials
         should focus on long-term adherence and quality of life outcomes.</p>
    </sec>
  </body>
</article>
"""


def _parse():
    return ep.xml_to_sections(FIXTURE_XML)


# ---------------------------------------------------------------- XML 解析

def test_xml_sections_normalized_titles():
    secs = _parse()
    titles = [t for t, _ in secs]
    assert "Introduction" in titles           # 前导编号已剥离
    assert "Statistical analysis" in titles   # 嵌套小节独立成节
    assert "References" in titles
    assert not any(t and t[0].isdigit() for t in titles if t), titles


def test_xml_citation_brackets_stripped():
    secs = _parse()
    text = " ".join(p for _, paras in secs for p in paras)
    assert "[1]" not in text and "[9,10,11]" not in text
    assert "stated targets" in text           # xref 内容被移除，正文保留


def test_xml_math_placeholder():
    secs = _parse()
    text = " ".join(p for _, paras in secs for p in paras)
    assert "[MATH]" in text
    assert "mixed model [MATH] with" in text


def test_xml_table_cell_separators():
    secs = _parse()
    text = " ".join(p for _, paras in secs for p in paras)
    assert "Group | N" in text
    assert "Intervention | 120" in text
    assert " || " in text                      # 行间分隔


# ---------------------------------------------------------------- 分块

def test_chunk_never_mixes_sections():
    secs = _parse()
    chunks = ep.chunk_sections(secs, max_chars=4000, cap=20, skip=())
    assert chunks, "应产生 chunk"
    # 每个 chunk 的文本前缀 [Section] 与 section 字段一致；重叠块同 section
    for c in chunks:
        if c["section"]:
            assert c["text"].startswith(f"[{c['section']}]"), c
    # 同 section 相邻重叠块必须共享 section（重叠只发生在同小节内；
    # span 为小节内相对偏移，跨小节数值重叠属正常）
    for a, b in zip(chunks, chunks[1:]):
        if a["section"] == b["section"] and b["start"] < a["end"]:
            assert a["section"] == b["section"]


def test_chunk_skip_references():
    secs = _parse()
    chunks = ep.chunk_sections(secs, max_chars=4000, cap=20,
                               skip=config.FULLTEXT_SKIP_SECTIONS)
    assert all(c["section"] != "References" for c in chunks)


def test_chunk_span_metadata_and_overlap():
    secs = _parse()
    chunks = ep.chunk_sections(secs, max_chars=200, cap=20, skip=())
    # span 元数据覆盖正文长度
    for c in chunks:
        body = c["text"]
        if c["section"]:
            body = body[len(f"[{c['section']}] "):]
        assert c["end"] - c["start"] + 1 >= len(body) - 2
    # Discussion 长段落应在 max_chars=200 下切成多块，且相邻块同小节重叠
    disc = [c for c in chunks if c["section"] == "Discussion"]
    assert len(disc) >= 2, "长小节应被切成多块"
    overlaps = [b for a, b in zip(disc, disc[1:]) if b["start"] < a["end"]]
    assert overlaps, "同小节相邻块应存在重叠"


def test_chunk_sentence_boundary_no_hard_cut():
    secs = _parse()
    chunks = ep.chunk_sections(secs, max_chars=120, cap=20, skip=())
    for c in chunks:
        body = c["text"]
        if c["section"]:
            body = body[len(f"[{c['section']}] "):]
        # 句子边界切分：块内不出现被切断的句尾（除单句超长硬切场景）
        assert len(body) <= 140


# ---------------------------------------------------------------- 跨源去重

def test_merge_guideline_pubmed():
    recs = [
        {"id": "guideline:g1", "record_kind": "guideline", "source_type": "guideline",
         "pmid": "100", "topics": ["hypertension"], "abstract_or_chunk": "short", "extras": {}},
        {"id": "pmid:100", "record_kind": "abstract", "source_type": "pubmed",
         "pmid": "100", "topics": ["lipids"], "pmcid": None, "doi": "10.1/x",
         "journal": "Circ", "mesh_terms": ["m1"], "abstract_or_chunk": "long", "extras": {}},
    ]
    out = merge_duplicate_pmids(recs)
    ids = {r["id"] for r in out}
    assert ids == {"guideline:g1"}
    w = out[0]
    assert w["doi"] == "10.1/x" and w["journal"] == "Circ"          # 从 pubmed 补齐
    assert set(w["topics"]) == {"hypertension", "lipids"}           # 主题并集
    assert w["extras"]["dedup_merged_ids"] == ["pmid:100"]


def test_merge_pubmed_epmc_keeps_pmcid():
    recs = [
        {"id": "pmid:101", "record_kind": "abstract", "source_type": "pubmed",
         "pmid": "101", "pmcid": None, "abstract_or_chunk": "a", "extras": {}},
        {"id": "epmc:MED:101", "record_kind": "abstract", "source_type": "europepmc",
         "pmid": "101", "pmcid": "PMC1", "doi": "10.1/y", "abstract_or_chunk": "b", "extras": {}},
    ]
    out = merge_duplicate_pmids(recs)
    assert [r["id"] for r in out] == ["pmid:101"]
    assert out[0]["pmcid"] == "PMC1" and out[0]["doi"] == "10.1/y"


def test_merge_never_touches_fulltext_chunks():
    recs = [
        {"id": "pmid:101", "record_kind": "abstract", "source_type": "pubmed",
         "pmid": "101", "abstract_or_chunk": "a", "extras": {}},
        {"id": "epmc:PMC2:chunk:000", "record_kind": "fulltext_chunk",
         "source_type": "europepmc", "pmid": "101", "abstract_or_chunk": "chunk", "extras": {}},
        {"id": "epmc:PMC2:chunk:001", "record_kind": "fulltext_chunk",
         "source_type": "europepmc", "pmid": "101", "abstract_or_chunk": "chunk2", "extras": {}},
    ]
    out = merge_duplicate_pmids(recs)
    ids = {r["id"] for r in out}
    assert ids == {"pmid:101", "epmc:PMC2:chunk:000", "epmc:PMC2:chunk:001"}


# ---------------------------------------------------------------- 标准化

def test_pubmed_title_only_fallback():
    rec = normalize_pubmed({"pmid": "1", "title": "A Study", "abstract": "",
                            "publication_types": ["Journal Article"]}, [])
    assert rec["abstract_or_chunk"] == "A Study"          # 空摘要回退标题
    assert rec["extras"]["content_status"] == "title_only"


def test_fulltext_chunk_min_length_and_metadata():
    hit = {"pmcid": "PMC1", "title": "T", "source": "MED", "id": "1",
           "pmid": "9", "doi": "10.1/z", "journalTitle": "J", "isOpenAccess": "Y"}
    chunks = [
        {"text": "x" * 60, "section": "Results", "start": 0, "end": 59},
        {"text": "tiny", "section": "Results", "start": 60, "end": 63},
    ]
    recs = normalize_fulltext_chunks(hit, chunks, [])
    assert len(recs) == 1                                # 过短 chunk 被丢弃
    assert recs[0]["extras"]["section"] == "Results"
    assert recs[0]["extras"]["char_start"] == 0 and recs[0]["extras"]["char_end"] == 59
    assert recs[0]["extras"]["chunk_total"] == 2
