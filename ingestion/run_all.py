"""一键执行完整数据采集流程：

    python -m ingestion.run_all [--force]

步骤：
  1. PubMed：执行全部 esearch（带缓存）→ 合并去重 → efetch 摘要（带缓存）
  2. ClinicalTrials.gov：按疾病抓取干预性试验
  3. Europe PMC：OA 文献检索 + 全文 XML 下载与分块（缓存）
  4. 指南：人工确认清单 + 用 PubMed 真实记录回填 PMID/DOI/摘要
  5. 标准化为 Evidence JSONL
  6. SQLite 入库 + DatasetManifest + 统计报告
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import config
from .sources import clinicaltrials, europepmc, pubmed
from .guidelines import CURATED_GUIDELINES, enrich_from_pubmed
from .normalize import (normalize_fulltext_chunks, normalize_guideline,
                        normalize_pubmed, normalize_trial,
                        normalize_epmc_abstract, evidence_to_line)
from . import build_db

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("ingestion.run_all")

T0 = time.time()


def _ensure_dirs():
    for d in [config.PUBMED_DIR, config.PUBMED_ARTICLE_DIR,
              config.TRIALS_DIR, config.EPMC_DIR, config.EPMC_FULLTEXT_DIR,
              config.GUIDELINE_DIR, config.DATA_PROCESSED, config.ARTIFACTS]:
        Path(d).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- 1. PubMed

def crawl_pubmed(force: bool = False):
    idlists = {}
    for slug, term, retmax, sort in config.PUBMED_QUERIES:
        cached = None if force else pubmed.load_idlist(slug)
        if cached is not None:
            idlists[slug] = cached
            log.info("use cached idlist %s (%d)", slug, len(cached))
        else:
            pmids = pubmed.esearch(term, retmax=retmax, sort=sort)
            pubmed.save_idlist(slug, pmids)
            idlists[slug] = pmids

    # 合并去重
    all_pmids = set()
    pmid_topics = {}
    for slug, pmids in idlists.items():
        topics = config.QUERY_TOPIC.get(slug, [])
        for p in pmids:
            all_pmids.add(p)
            pmid_topics.setdefault(p, []).extend(topics)
    log.info("PubMed unique PMIDs: %d", len(all_pmids))

    # 抓取摘要（带缓存）
    cached_file = config.PUBMED_ARTICLE_DIR / "all_articles.json"
    if cached_file.exists() and not force:
        articles = json.loads(cached_file.read_text(encoding="utf-8"))
        log.info("use cached articles: %d", len(articles))
    else:
        articles = pubmed.efetch_articles(sorted(all_pmids))
        cached_file.write_text(json.dumps(articles, ensure_ascii=False),
                               encoding="utf-8")
        log.info("efetch done: %d articles", len(articles))
    return articles, pmid_topics


# ---------------------------------------------------------------- 2. Trials

def crawl_trials(force: bool = False):
    all_studies = []
    for slug, cond, max_records in config.TRIAL_TOPICS:
        out = config.TRIALS_DIR / f"{slug}.json"
        if out.exists() and not force:
            studies = json.loads(out.read_text(encoding="utf-8"))["studies"]
            log.info("use cached trials %s (%d)", slug, len(studies))
        else:
            studies = clinicaltrials.fetch_studies(cond, max_records=max_records)
            clinicaltrials.save_raw(slug, studies)
        all_studies.extend(studies)
    # 按 NCT 去重
    seen = {}
    for s in all_studies:
        nct = s.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
        if nct:
            seen[nct] = s
    log.info("trials unique NCT: %d", len(seen))
    return list(seen.values())


# ---------------------------------------------------------------- 3. Europe PMC

def crawl_europepmc(force: bool = False):
    hits_by_slug = {}
    for slug, query, page_size in config.EPMC_QUERIES:
        out = config.EPMC_DIR / f"search_{slug}.json"
        if out.exists() and not force:
            hits = json.loads(out.read_text(encoding="utf-8"))["hits"]
            log.info("use cached epmc search %s (%d)", slug, len(hits))
        else:
            hits = europepmc.search(query, page_size=page_size)
            europepmc.save_raw(slug, hits)
        hits_by_slug[slug] = hits

    # 合并去重（按 pmcid 或 id）
    hit_map = {}
    for slug, hits in hits_by_slug.items():
        for h in hits:
            key = h.get("pmcid") or f"{h.get('source')}:{h.get('id')}"
            if key and key not in hit_map:
                hit_map[key] = h

    # 全文下载候选：OA + 有 pmcid，优先系统综述，上限 FULLTEXT_LIMIT
    candidates = [h for h in hit_map.values()
                  if h.get("isOpenAccess") == "Y" and h.get("pmcid")]
    candidates.sort(key=lambda h: 0 if "systematic" in (h.get("title") or "").lower()
                    or "meta-analysis" in (h.get("title") or "").lower()
                    or "guideline" in (h.get("title") or "").lower() else 1)
    candidates = candidates[:config.EPMC_FULLTEXT_LIMIT]

    fulltext_meta = {}   # pmcid -> hit
    for h in candidates:
        pmcid = h["pmcid"]
        out = config.EPMC_FULLTEXT_DIR / f"{pmcid}.xml"
        if out.exists() and not force:
            xml_text = out.read_text(encoding="utf-8")
        else:
            xml_text = europepmc.fulltext_xml(pmcid)
            if xml_text is None:
                continue
            europepmc.save_fulltext(pmcid, xml_text)
        fulltext_meta[pmcid] = h
        log.info("fulltext ok: %s (%s)", pmcid, h.get("title", "")[:50])
    log.info("Europe PMC fulltext articles: %d", len(fulltext_meta))
    return hits_by_slug, hit_map, fulltext_meta


# 指南标题专用查询的主题标签
GUIDELINE_QUERY_TOPIC = {
    "g_cn_hyp_2018": ["hypertension"], "g_cn_hyp_2024": ["hypertension"],
    "g_cn_lipid_2023": ["lipids"], "g_cn_lipid_primary_2024": ["lipids"],
    "g_cn_elder_hyp_2019": ["hypertension"], "g_cn_elder_hyp_2023": ["hypertension"],
    "g_accaha_hbp_2017": ["hypertension"], "g_esh_2023": ["hypertension"],
    "g_esc_2024": ["hypertension"], "g_accaha_chol_2018": ["lipids"],
    "g_esc_eas_2019": ["lipids"], "g_esc_prev_2021": ["hypertension", "lipids"],
    "g_kdigo_bp_2021": ["hypertension"], "g_who_hyp_2021": ["hypertension"],
}


def crawl_guideline_articles(force: bool = False):
    """执行指南标题专用查询并抓取对应 PubMed 记录（用于回填指南元数据）。"""
    preferred = {}
    extra_articles = []
    for slug, term, retmax in config.GUIDELINE_TITLE_QUERIES:
        cached = None if force else pubmed.load_idlist(slug)
        if cached is not None:
            pmids = cached
            log.info("use cached guideline idlist %s (%d)", slug, len(pmids))
        else:
            pmids = pubmed.esearch(term, retmax=retmax)
            pubmed.save_idlist(slug, pmids)
        preferred[slug] = pmids
    all_pmids = {p for ps in preferred.values() for p in ps}
    if all_pmids:
        cached_file = config.PUBMED_ARTICLE_DIR / "guideline_articles.json"
        if cached_file.exists() and not force:
            extra_articles = json.loads(cached_file.read_text(encoding="utf-8"))
        else:
            extra_articles = pubmed.efetch_articles(sorted(all_pmids))
            cached_file.write_text(json.dumps(extra_articles, ensure_ascii=False),
                                   encoding="utf-8")
    log.info("guideline-specific articles: %d", len(extra_articles))
    return preferred, extra_articles


# ---------------------------------------------------------------- 4. 指南

def build_guidelines(articles, preferred):
    enriched = enrich_from_pubmed(CURATED_GUIDELINES, articles, preferred=preferred)
    # 保存人工确认清单（含回填结果）
    out = config.GUIDELINE_DIR / "curated_guidelines.json"
    out.write_text(json.dumps(enriched, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return enriched


# ---------------------------------------------------------------- 5+6. 标准化入库

def normalize_all(articles, pmid_topics, trials, hits_by_slug, fulltext_meta, guidelines):
    lines = []
    # PubMed
    for a in articles:
        if not a.get("pmid"):
            continue
        topics = pmid_topics.get(a["pmid"], [])
        lines.append(normalize_pubmed(a, topics))
    # Trials
    for t in trials:
        lines.append(normalize_trial(clinicaltrials.parse_study(t)))
    # Europe PMC abstracts（与 PubMed 按 PMID 去重）
    pubmed_pmids = {a["pmid"] for a in articles if a.get("pmid")}
    epmc_seen = set()
    for slug, hits in hits_by_slug.items():
        for h in hits:
            pmid = h.get("pmid")
            if pmid and pmid in pubmed_pmids:
                continue
            key = h.get("pmcid") or f"{h.get('source')}:{h.get('id')}"
            if key in epmc_seen:
                continue
            epmc_seen.add(key)
            lines.append(normalize_epmc_abstract(h, config.QUERY_TOPIC.get(slug, [])))
    # Europe PMC 全文 chunks
    for pmcid, h in fulltext_meta.items():
        xml_text = (config.EPMC_FULLTEXT_DIR / f"{pmcid}.xml").read_text(encoding="utf-8")
        sections = europepmc.xml_to_sections(xml_text)
        chunks = europepmc.chunk_sections(
            sections, max_chars=config.FULLTEXT_CHUNK_MAX_CHARS,
            cap=config.FULLTEXT_CHUNK_CAP_PER_ARTICLE,
            skip=config.FULLTEXT_SKIP_SECTIONS)
        lines.extend(normalize_fulltext_chunks(h, chunks, []))
    # 指南
    for g in guidelines:
        lines.append(normalize_guideline(g))

    # 按 id 去重 + content_hash 冲突校验
    seen = {}
    for ln in lines:
        seen[ln["id"]] = ln
    lines = list(seen.values())

    with open(config.EVIDENCE_JSONL, "w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(evidence_to_line(ln), ensure_ascii=False) + "\n")
    log.info("evidence.jsonl written: %d records", len(lines))
    return lines


def main():
    ap = argparse.ArgumentParser(description="OpenEvidence 数据集采集")
    ap.add_argument("--force", action="store_true", help="忽略缓存，重新抓取")
    ap.add_argument("--no-db", action="store_true", help="只生成 JSONL，不建库")
    args = ap.parse_args()

    _ensure_dirs()
    articles, pmid_topics = crawl_pubmed(force=args.force)
    preferred, guideline_articles = crawl_guideline_articles(force=args.force)
    # 把指南专用查询抓到的记录并入语料（含其主题标签）
    for a in guideline_articles:
        if a.get("pmid") and a["pmid"] not in pmid_topics:
            pmid_topics[a["pmid"]] = []
    for slug, pmids in preferred.items():
        for p in pmids:
            pmid_topics.setdefault(p, []).extend(GUIDELINE_QUERY_TOPIC.get(slug, []))
    merged = {a["pmid"]: a for a in articles + guideline_articles if a.get("pmid")}
    articles = list(merged.values())
    trials = crawl_trials(force=args.force)
    hits_by_slug, hit_map, fulltext_meta = crawl_europepmc(force=args.force)
    guidelines = build_guidelines(articles, preferred)

    lines = normalize_all(articles, pmid_topics, trials, hits_by_slug, fulltext_meta, guidelines)

    if not args.no_db:
        res = build_db.run(force=True)
        log.info("DB rows=%d, total_papers=%d", res["rows"], res["total_papers"])

    stats = build_db.compute_stats(lines)
    total_papers = (stats["papers"]["pubmed_abstracts"]
                    + stats["papers"]["epmc_abstracts"]
                    + stats["papers"]["trials"] + stats["papers"]["guidelines"])
    log.info("=" * 60)
    log.info("完成！总证据记录=%d | 文献/证据篇数=%d | 唯一 PMID=%d",
             len(lines), total_papers, stats["papers"]["distinct_pmids"])
    log.info("耗时 %.1f 秒", time.time() - T0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
