"""Evidence 入库：SQLite + DatasetManifest + 统计报告。"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections import Counter
from datetime import datetime, timezone

from . import config

log = logging.getLogger("ingestion.build_db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence (
    id                TEXT PRIMARY KEY,
    record_kind       TEXT,
    source_type       TEXT,
    title             TEXT,
    abstract_or_chunk TEXT,
    authors           TEXT,
    published_at      TEXT,
    year              INTEGER,
    url               TEXT,
    pmid              TEXT,
    doi               TEXT,
    nct_id            TEXT,
    pmcid             TEXT,
    guideline_name    TEXT,
    page              TEXT,
    evidence_level    TEXT,
    population        TEXT,
    intervention      TEXT,
    comparator        TEXT,
    outcome           TEXT,
    journal           TEXT,
    publication_types TEXT,
    mesh_terms        TEXT,
    keywords          TEXT,
    topics            TEXT,
    content_hash      TEXT,
    fetched_at        TEXT,
    extras            TEXT
);
CREATE INDEX IF NOT EXISTS idx_ev_pmid ON evidence(pmid);
CREATE INDEX IF NOT EXISTS idx_ev_nct  ON evidence(nct_id);
CREATE INDEX IF NOT EXISTS idx_ev_kind ON evidence(record_kind);
CREATE INDEX IF NOT EXISTS idx_ev_level ON evidence(evidence_level);
CREATE INDEX IF NOT EXISTS idx_ev_year ON evidence(year);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def load_evidence_lines():
    """从 evidence.jsonl + fulltext_chunks.jsonl 读取（list 字段已是 JSON 字符串）。

    注意：必须用 split("\n") 而非 splitlines()——splitlines() 会按 \u2028/\u2029 等
    Unicode 行分隔符拆分，而写入时仅以 \n 为行边界。
    """
    lines = []
    for path in (config.EVIDENCE_JSONL, config.FULLTEXT_CHUNKS_JSONL):
        if not path.exists():
            continue
        for ln in path.read_text(encoding="utf-8").split("\n"):
            if ln.strip():
                lines.append(json.loads(ln))
    return lines


def build_db(lines, force: bool = False):
    if config.EVIDENCE_DB.exists():
        config.EVIDENCE_DB.unlink()
    conn = sqlite3.connect(str(config.EVIDENCE_DB))
    conn.executescript(SCHEMA)
    cols = ["id", "record_kind", "source_type", "title", "abstract_or_chunk",
            "authors", "published_at", "year", "url", "pmid", "doi", "nct_id",
            "pmcid", "guideline_name", "page", "evidence_level", "population",
            "intervention", "comparator", "outcome", "journal",
            "publication_types", "mesh_terms", "keywords", "topics",
            "content_hash", "fetched_at", "extras"]
    rows = []
    for ln in lines:
        rows.append(tuple(ln.get(c) for c in cols))
    conn.executemany(
        f"INSERT OR REPLACE INTO evidence ({','.join(cols)}) VALUES ({','.join(['?'] * len(cols))})",
        rows)
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('evidence_count', ?)",
                 (str(len(rows)),))
    conn.commit()
    conn.close()
    log.info("SQLite written: %d rows -> %s", len(rows), config.EVIDENCE_DB)
    return len(rows)


# ---------------------------------------------------------------- 统计

def compute_stats(lines):
    s = {
        "total_records": len(lines),
        "by_record_kind": Counter(r["record_kind"] for r in lines),
        "by_source_type": Counter(r["source_type"] for r in lines),
        "by_evidence_level": Counter(r["evidence_level"] for r in lines),
        "by_topic": Counter(),
        "by_year": Counter(),
        "by_journal": Counter(),
        "trials_by_status": Counter(),
        "trials_by_phase": Counter(),
        "guidelines_enriched": Counter(),
        "papers": {
            "pubmed_abstracts": 0,
            "epmc_abstracts": 0,
            "trials": 0,
            "guidelines": 0,
            "distinct_pmids": 0,
        },
    }
    pmids = set()
    for r in lines:
        kind = r["record_kind"]
        raw_topics = r.get("topics") or []
        if isinstance(raw_topics, str):
            raw_topics = [t.strip().strip('"') for t in
                          raw_topics.strip("[]").split(",") if t.strip().strip('"')]
        for t in raw_topics:
            s["by_topic"][t] += 1
        y = r.get("year")
        if y:
            s["by_year"][y] += 1
        if kind == "abstract":
            if r["source_type"] == "pubmed":
                s["papers"]["pubmed_abstracts"] += 1
                if r.get("pmid"):
                    pmids.add(r["pmid"])
            elif r["source_type"] == "europepmc":
                s["papers"]["epmc_abstracts"] += 1
                if r.get("pmid"):
                    pmids.add(r["pmid"])
        elif kind == "trial":
            s["papers"]["trials"] += 1
            ext = r.get("extras") or {}
            if isinstance(ext, str):
                ext = json.loads(ext)
            s["trials_by_status"][ext.get("status")] += 1
            phase = ext.get("phase") or "NA"
            s["trials_by_phase"][phase] += 1
        elif kind == "guideline":
            s["papers"]["guidelines"] += 1
            ext = r.get("extras") or {}
            if isinstance(ext, str):
                ext = json.loads(ext)
            s["guidelines_enriched"][str(ext.get("enriched"))] += 1
        j = r.get("journal")
        if j:
            s["by_journal"][j] += 1
    s["papers"]["distinct_pmids"] = len(pmids)
    return s


def compute_chunk_stats(chunk_lines, stats):
    """统计全文 chunk 层（独立文件）。"""
    n = len(chunk_lines)
    articles = set()
    pmids = set()
    for r in chunk_lines:
        if r.get("pmcid"):
            articles.add(r["pmcid"])
        if r.get("pmid"):
            pmids.add(r["pmid"])
    stats["fulltext_chunks"] = {
        "chunk_count": n,
        "article_count": len(articles),
        "articles_with_pmid": len(pmids),
    }
    return stats


def _counter_to_dict(c, topn=None):
    items = sorted(c.items(), key=lambda kv: -kv[1])
    if topn:
        items = items[:topn]
    return {k: v for k, v in items}


def write_manifest(lines, ingest_stats=None):
    hashes = {}
    for path in (config.EVIDENCE_JSONL, config.FULLTEXT_CHUNKS_JSONL):
        if path.exists():
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    m = {
        "dataset_version": "v0.2.0",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_cutoff": datetime.now(timezone.utc).date().isoformat(),
        "source_datasets": [
            "PubMed (E-utilities esearch/efetch, abstracts)",
            "ClinicalTrials.gov Data API v2 (interventional studies)",
            "Europe PMC REST API (open-access abstracts + full-text chunks)",
            "Manual curated guidelines (hypertension & dyslipidemia)",
        ],
        "licenses": {
            "PubMed": "U.S. National Library of Medicine, free access; abstracts are U.S. Government work",
            "ClinicalTrials.gov": "Public domain (U.S. HHS data), no attribution required",
            "EuropePMC": "Records metadata freely available; full-text only for OPEN_ACCESS articles",
            "guidelines": "教学使用；仅保存书目元数据与公开摘要，不保存版权全文",
        },
        "storage_layout": {
            "evidence.jsonl": "主集：题录/摘要 + 试验 + 指南（用于检索召回）",
            "fulltext_chunks.jsonl": "增强层：Europe PMC OA 全文分块（用于生成/验证时按需增强）",
            "evidence.db": "SQLite：主集与全文 chunk 同表，record_kind 区分；供检索层查询",
        },
        "split_hashes": hashes,
        "source_group_policy": "跨源去重：PubMed 与 Europe PMC 以 PMID 为稳定键；试验以 NCT ID；指南以人工 key",
        "dedup_method": "PMID/NCT/guideline-key 唯一键 + 跨源同 PMID 合并（指南>PubMed>Europe PMC）",
        "dedup_threshold": None,
        "topics": ["hypertension", "dyslipidemia"],
        "record_counts": dict(Counter(r["record_kind"] for r in lines)),
        "chunk_policy": {
            "max_chars_per_chunk": config.FULLTEXT_CHUNK_MAX_CHARS,
            "overlap_chars": config.FULLTEXT_CHUNK_OVERLAP_CHARS,
            "cap_per_article": config.FULLTEXT_CHUNK_CAP_PER_ARTICLE,
            "min_chunk_chars": config.FULLTEXT_MIN_CHUNK_CHARS,
            "section_aware": True,
            "skip_sections": sorted(config.FULLTEXT_SKIP_SECTIONS),
        },
        "processing_stats": ingest_stats or {},
        "pipeline": "cd OpenEvidence && python -m ingestion.run_all",
        "generator": "ingestion.build_db.write_manifest",
    }
    config.MANIFEST_JSON.write_text(
        json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return m


def write_stats(lines, stats, ingest_stats=None):
    papers = stats["papers"]
    total_papers = (papers["pubmed_abstracts"] + papers["epmc_abstracts"]
                    + papers["trials"] + papers["guidelines"])
    md = f"""# 数据集统计报告

生成时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}

## 总量
- 证据记录总数：**{stats['total_records']}**
- **文献/证据篇数（去重口径）：{total_papers}**
  - PubMed 摘要：{papers['pubmed_abstracts']}
  - Europe PMC 独有摘要：{papers['epmc_abstracts']}
  - ClinicalTrials.gov 试验：{papers['trials']}
  - 人工确认指南：{papers['guidelines']}
- 唯一 PMID 数：{papers['distinct_pmids']}
- 全文增强层（Europe PMC OA）：{stats.get('fulltext_chunks', {}).get('article_count', 0)} 篇 / {stats.get('fulltext_chunks', {}).get('chunk_count', 0)} 个 chunk
  （存于 data/processed/fulltext_chunks.jsonl，生成/验证时按需加载）

## 数据处理（改进后口径）
- 跨源同 PMID 合并删除记录数：{ingest_stats.get('dedup_merged', 0) if ingest_stats else 'N/A'}
- 无摘要回退为标题（title_only）：{ingest_stats.get('title_only', 0) if ingest_stats else 'N/A'}
- 过短 chunk 丢弃：{ingest_stats.get('tiny_chunks_dropped', 0) if ingest_stats else 'N/A'}
- XML 解析失败（隔离）：{ingest_stats.get('xml_parse_failed', []) if ingest_stats else 'N/A'}

## 按记录类型
{json.dumps(dict(stats['by_record_kind']), ensure_ascii=False, indent=2)}

## 按来源
{json.dumps(dict(stats['by_source_type']), ensure_ascii=False, indent=2)}

## 按证据等级
{json.dumps(dict(stats['by_evidence_level']), ensure_ascii=False, indent=2)}

## 按主题
{json.dumps(dict(stats['by_topic']), ensure_ascii=False, indent=2)}

## 按年份（Top 15）
{json.dumps(_counter_to_dict(stats['by_year'], 15), ensure_ascii=False, indent=2)}

## 期刊 Top 20
{json.dumps(_counter_to_dict(stats['by_journal'], 20), ensure_ascii=False, indent=2)}

## 试验按状态
{json.dumps(_counter_to_dict(stats['trials_by_status']), ensure_ascii=False, indent=2)}

## 试验按分期
{json.dumps(_counter_to_dict(stats['trials_by_phase']), ensure_ascii=False, indent=2)}

## 指南回填（PubMed 真实元数据）
{json.dumps(dict(stats['guidelines_enriched']), ensure_ascii=False, indent=2)}
"""
    config.STATS_MD.write_text(md, encoding="utf-8")

    sj = {
        "total_records": stats["total_records"],
        "total_papers": total_papers,
        "papers": {k: v for k, v in papers.items()},
        "fulltext_chunks": stats.get("fulltext_chunks", {}),
        "by_record_kind": _counter_to_dict(stats["by_record_kind"]),
        "by_source_type": _counter_to_dict(stats["by_source_type"]),
        "by_evidence_level": _counter_to_dict(stats["by_evidence_level"]),
        "by_topic": _counter_to_dict(stats["by_topic"]),
        "by_year": _counter_to_dict(stats["by_year"], 15),
        "by_journal": _counter_to_dict(stats["by_journal"], 20),
        "trials_by_status": _counter_to_dict(stats["trials_by_status"]),
        "trials_by_phase": _counter_to_dict(stats["trials_by_phase"]),
        "processing_stats": ingest_stats or {},
    }
    config.STATS_JSON.write_text(json.dumps(sj, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    return total_papers


def run(force: bool = False, chunk_lines=None, ingest_stats=None):
    lines = load_evidence_lines()
    if not lines:
        raise RuntimeError("evidence.jsonl 为空，请先运行 python -m ingestion.run_all")
    n = build_db(lines, force=force)
    stats = compute_stats(lines)
    if chunk_lines is not None:
        stats = compute_chunk_stats(chunk_lines, stats)
    manifest = write_manifest(lines, ingest_stats=ingest_stats)
    total_papers = write_stats(lines, stats, ingest_stats=ingest_stats)
    log.info("manifest written: %s", config.MANIFEST_JSON)
    log.info("stats written: %s / %s", config.STATS_MD, config.STATS_JSON)
    return {"rows": n, "total_papers": total_papers,
            "chunks": stats.get("fulltext_chunks", {}).get("chunk_count", 0),
            "manifest": manifest}
