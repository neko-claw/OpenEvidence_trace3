"""Evidence 标准化：把各源原始记录统一为规划 3.1 的数据契约。

输出字段（Evidence 契约 + 扩展字段）：
  id, record_kind, source_type, title, abstract_or_chunk, authors,
  published_at, year, url, pmid, doi, nct_id, pmcid, guideline_name,
  page, evidence_level, population, intervention, comparator, outcome,
  journal, publication_types, mesh_terms, keywords, topics,
  content_hash, fetched_at, extras
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from . import config

FETCHED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")

# ---------------------------------------------------------------- 工具

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def content_hash(title: str, body: str) -> str:
    raw = f"{_norm(title)}\n{_norm(body)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def evidence_level_from_types(pub_types) -> str:
    pts = {t.lower() for t in (pub_types or [])}
    if pts & {"guideline", "practice guideline"}:
        return "guideline"
    if "meta-analysis" in pts:
        return "meta-analysis"
    if "systematic review" in pts:
        return "systematic-review"
    if "randomized controlled trial" in pts:
        return "rct"
    if pts & {"clinical trial", "controlled clinical trial", "clinical trial, phase i",
              "clinical trial, phase ii", "clinical trial, phase iii", "clinical trial, phase iv"}:
        return "clinical-trial"
    if "review" in pts:
        return "review"
    return "other"


def tag_topics(text: str, query_topics) -> list:
    """查询主题 + 标题/摘要关键词共同确定主题标签。"""
    topics = set(query_topics or [])
    low = (text or "").lower()
    if any(t in low for t in config.HYPERTENSION_TERMS):
        topics.add("hypertension")
    if any(t in low for t in config.LIPID_TERMS):
        topics.add("lipids")
    return sorted(t for t in topics if t)


def _pubmed_url(pmid: str) -> str:
    return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"


# ---------------------------------------------------------------- PubMed 记录

def normalize_pubmed(raw: dict, query_topics) -> dict:
    pmid = raw["pmid"]
    title = _norm(raw.get("title"))
    abstract = _norm(raw.get("abstract"))
    pub_types = raw.get("publication_types") or []
    text = f"{title} {abstract}"
    return {
        "id": f"pmid:{pmid}",
        "record_kind": "abstract",
        "source_type": "pubmed",
        "title": title,
        "abstract_or_chunk": abstract,
        "authors": raw.get("authors") or [],
        "published_at": raw.get("published_at"),
        "year": raw.get("year"),
        "url": _pubmed_url(pmid),
        "pmid": pmid,
        "doi": raw.get("doi"),
        "nct_id": None,
        "pmcid": None,
        "guideline_name": None,
        "page": None,
        "evidence_level": evidence_level_from_types(pub_types),
        "population": None,
        "intervention": None,
        "comparator": None,
        "outcome": None,
        "journal": raw.get("journal"),
        "publication_types": pub_types,
        "mesh_terms": raw.get("mesh_terms") or [],
        "keywords": raw.get("keywords") or [],
        "topics": tag_topics(text, query_topics),
        "content_hash": content_hash(title, abstract),
        "fetched_at": FETCHED_AT,
        "extras": {},
    }


# ---------------------------------------------------------------- ClinicalTrials.gov 记录

def normalize_trial(raw: dict) -> dict:
    nct = raw["nct_id"]
    title = _norm(raw.get("title"))
    summary = _norm(raw.get("brief_summary"))
    return {
        "id": f"nct:{nct}",
        "record_kind": "trial",
        "source_type": "clinicaltrial",
        "title": title,
        "abstract_or_chunk": summary or title,
        "authors": [],
        "published_at": raw.get("published_at"),
        "year": raw.get("year"),
        "url": raw.get("url") or f"https://clinicaltrials.gov/study/{nct}",
        "pmid": None,
        "doi": None,
        "nct_id": nct,
        "pmcid": None,
        "guideline_name": None,
        "page": None,
        "evidence_level": "clinical-trial",
        "population": raw.get("population"),
        "intervention": " | ".join(raw.get("interventions") or []),
        "comparator": None,
        "outcome": " | ".join(raw.get("primary_outcomes") or []),
        "journal": None,
        "publication_types": ["Clinical Trial"],
        "mesh_terms": raw.get("conditions") or [],
        "keywords": [],
        "topics": tag_topics(f"{title} {summary} {' '.join(raw.get('conditions') or [])}", []),
        "content_hash": content_hash(title, summary),
        "fetched_at": FETCHED_AT,
        "extras": {
            "status": raw.get("status"),
            "phase": raw.get("phase"),
            "enrollment": raw.get("enrollment"),
            "enrollment_type": raw.get("enrollment_type"),
            "study_type": raw.get("study_type"),
            "intervention_types": raw.get("intervention_types"),
            "sponsor": raw.get("sponsor"),
            "official_title": raw.get("official_title"),
            "start_date": raw.get("start_date"),
            "last_update_date": raw.get("last_update_date"),
        },
    }


# ---------------------------------------------------------------- Europe PMC 记录

def _epmc_url(hit) -> str:
    src, pid = hit.get("source"), hit.get("id")
    if src and pid:
        return f"https://europepmc.org/article/{src}/{pid}"
    return None


def normalize_epmc_abstract(hit: dict, query_topics) -> dict:
    src = hit.get("source") or "MED"
    pid = hit.get("id") or ""
    pmid = hit.get("pmid") or None
    title = _norm(hit.get("title"))
    abstract = _norm(hit.get("abstractText"))
    year = None
    try:
        year = int(hit.get("pubYear")) if hit.get("pubYear") else None
    except (TypeError, ValueError):
        pass
    return {
        "id": f"epmc:{src}:{pid}",
        "record_kind": "abstract",
        "source_type": "europepmc",
        "title": title,
        "abstract_or_chunk": abstract,
        "authors": _split_author_string(hit.get("authorString")),
        "published_at": str(year) if year else None,
        "year": year,
        "url": _epmc_url(hit),
        "pmid": pmid,
        "doi": hit.get("doi") or None,
        "nct_id": None,
        "pmcid": hit.get("pmcid") or None,
        "guideline_name": None,
        "page": None,
        "evidence_level": "other",
        "population": None,
        "intervention": None,
        "comparator": None,
        "outcome": None,
        "journal": hit.get("journalTitle"),
        "publication_types": [],
        "mesh_terms": [],
        "keywords": [],
        "topics": tag_topics(f"{title} {abstract}", query_topics),
        "content_hash": content_hash(title, abstract),
        "fetched_at": FETCHED_AT,
        "extras": {
            "is_open_access": hit.get("isOpenAccess"),
            "in_epmc": hit.get("inEPMC"),
            "epmc_source": src,
            "epmc_id": pid,
        },
    }


def normalize_fulltext_chunks(hit: dict, chunks: list, query_topics) -> list:
    """一篇 OA 全文 → 多个 chunk 级 Evidence 记录。"""
    pmcid = hit.get("pmcid")
    if not pmcid:
        return []
    pmid = hit.get("pmid") or None
    title = _norm(hit.get("title"))
    year = None
    try:
        year = int(hit.get("pubYear")) if hit.get("pubYear") else None
    except (TypeError, ValueError):
        pass
    records = []
    for i, chunk in enumerate(chunks):
        records.append({
            "id": f"epmc:{pmcid}:chunk:{i:03d}",
            "record_kind": "fulltext_chunk",
            "source_type": "europepmc",
            "title": title,
            "abstract_or_chunk": chunk,
            "authors": _split_author_string(hit.get("authorString")),
            "published_at": str(year) if year else None,
            "year": year,
            "url": f"https://europepmc.org/article/PMC/{pmcid}",
            "pmid": pmid,
            "doi": hit.get("doi") or None,
            "nct_id": None,
            "pmcid": pmcid,
            "guideline_name": None,
            "page": None,
            "evidence_level": "other",
            "population": None,
            "intervention": None,
            "comparator": None,
            "outcome": None,
            "journal": hit.get("journalTitle"),
            "publication_types": [],
            "mesh_terms": [],
            "keywords": [],
            "topics": tag_topics(title, query_topics),
            "content_hash": content_hash(title, chunk),
            "fetched_at": FETCHED_AT,
            "extras": {"chunk_index": i, "chunk_total": len(chunks),
                       "epmc_source": hit.get("source"), "epmc_id": hit.get("id"),
                       "is_open_access": hit.get("isOpenAccess")},
        })
    return records


def _split_author_string(author_string):
    if not author_string:
        return []
    # Europe PMC authorString: "Zhang J, Li W; Wang X" 之类，按 ; 或 , 切分
    parts = re.split(r"[;,]", author_string)
    out = []
    for p in parts:
        p = p.strip()
        if p and p not in out:
            out.append(p)
    return out


# ---------------------------------------------------------------- 指南记录

def normalize_guideline(g: dict) -> dict:
    title = _norm(g.get("title"))
    desc = g.get("abstract") or g.get("notes") or ""
    topic = g.get("topic", "both")
    if topic == "both":
        query_topics = ["hypertension", "lipids"]
    else:
        query_topics = [topic]
    return {
        "id": f"guideline:{g['key']}",
        "record_kind": "guideline",
        "source_type": "guideline",
        "title": title,
        "abstract_or_chunk": desc,
        "authors": [g.get("org", "")],
        "published_at": str(g.get("year")) if g.get("year") else None,
        "year": g.get("year"),
        "url": g.get("url"),
        "pmid": g.get("pmid"),
        "doi": g.get("doi"),
        "nct_id": None,
        "pmcid": None,
        "guideline_name": title,
        "page": None,
        "evidence_level": "guideline",
        "population": None,
        "intervention": None,
        "comparator": None,
        "outcome": None,
        "journal": g.get("journal"),
        "publication_types": ["Guideline"],
        "mesh_terms": [],
        "keywords": [],
        "topics": tag_topics(title, query_topics),
        "content_hash": content_hash(title, desc),
        "fetched_at": FETCHED_AT,
        "extras": {
            "org": g.get("org"),
            "enriched": g.get("enriched", False),
            "enrich_score": g.get("enrich_score", 0.0),
            "title_en": g.get("title_en"),
            "notes": g.get("notes"),
        },
    }


def evidence_to_line(ev: dict) -> dict:
    """序列化：把 list 字段转 JSON 字符串（写入 JSONL 时便于阅读）。"""
    line = {}
    for k, v in ev.items():
        if isinstance(v, (list, dict)):
            line[k] = json.dumps(v, ensure_ascii=False)
        else:
            line[k] = v
    return line
