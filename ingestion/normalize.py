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

# 摘要正文过短（<50 字符）时回退为标题，避免空文本进检索索引
MIN_ABSTRACT_CHARS = 50


def _norm(s: str) -> str:
    """归一化空白：去除控制字符与 Unicode 行分隔符，避免污染 JSONL 行结构。"""
    if s is None:
        return ""
    s = re.sub(r"[\u0000-\u001f\u007f\u2028\u2029\u0085]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


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
    # 改进 3：无摘要/过短摘要回退为标题并标记 content_status，避免空文本进索引
    content_status = "abstract" if len(abstract) >= MIN_ABSTRACT_CHARS else "title_only"
    body = abstract if abstract else title
    return {
        "id": f"pmid:{pmid}",
        "record_kind": "abstract",
        "source_type": "pubmed",
        "title": title,
        "abstract_or_chunk": body,
        "authors": raw.get("authors") or [],
        "published_at": raw.get("published_at"),
        "year": raw.get("year"),
        "url": _pubmed_url(pmid),
        "pmid": pmid,
        "doi": raw.get("doi"),
        "nct_id": None,
        "pmcid": raw.get("pmcid") or None,
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
        "extras": {"content_status": content_status},
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
    content_status = "abstract" if len(abstract) >= MIN_ABSTRACT_CHARS else "title_only"
    body = abstract if abstract else title
    return {
        "id": f"epmc:{src}:{pid}",
        "record_kind": "abstract",
        "source_type": "europepmc",
        "title": title,
        "abstract_or_chunk": body,
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
            "content_status": content_status,
        },
    }


def normalize_fulltext_chunks(hit: dict, chunks: list, query_topics) -> list:
    """一篇 OA 全文 → 多个 chunk 级 Evidence 记录。

    chunks 为 [{text, section, start, end}, ...]（europepmc.chunk_sections 输出）；
    每个 chunk 记录携带 section 与字符区间元数据，供证据 span 定位；
    过短 chunk（< FULLTEXT_MIN_CHUNK_CHARS）视为噪声丢弃。
    """
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
        body = re.sub(r"[\u0000-\u001f\u007f\u2028\u2029\u0085]", " ", (chunk.get("text") or "")).strip()
        if len(body) < config.FULLTEXT_MIN_CHUNK_CHARS:
            continue
        records.append({
            "id": f"epmc:{pmcid}:chunk:{i:03d}",
            "record_kind": "fulltext_chunk",
            "source_type": "europepmc",
            "title": title,
            "abstract_or_chunk": body,
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
            "content_hash": content_hash(title, body),
            "fetched_at": FETCHED_AT,
            "extras": {"chunk_index": i, "chunk_total": len(chunks),
                       "section": chunk.get("section"),
                       "char_start": chunk.get("start"),
                       "char_end": chunk.get("end"),
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


# ---------------------------------------------------------------- 跨源去重（改进 2）

# 同 PMID 记录保留优先级：指南（人工 key）> PubMed > Europe PMC
_SOURCE_PRIORITY = {"guideline": 3, "pubmed": 2, "europepmc": 1}


def merge_duplicate_pmids(records: list) -> list:
    """按 PMID 合并跨源重复记录（指南 > PubMed > Europe PMC）。

    现状问题：同一文献可能同时出现 guideline:xxx 与 pmid:xxx（指南回填了 PMID）、
    或 pubmed:xxx 与 epmc:MED:xxx（同一篇在两侧都被抓到），导致检索冗余与
    Hit@k/gold/citation 计数歧义。本函数把同 PMID 的多条记录合并为一条：

    - guideline 与 abstract 同 PMID：保留 guideline id（人工 key 稳定），
      用 abstract 记录补齐 pmcid/doi/journal/mesh 等字段；
    - pubmed 与 europepmc 同 PMID：保留 pubmed id，从 epmc 补齐 pmcid 等；
    - 合并信息写入 extras.dedup_merged_ids，被合并的记录不再出现在语料。

    注意：fulltext_chunk 记录虽然携带文献 PMID，但它们是证据片段层，
    绝不参与同 PMID 合并（否则会把整篇全文的 chunk 全部删除）。
    """
    by_pmid = {}
    for r in records:
        if r.get("record_kind") == "fulltext_chunk":
            continue
        pmid = r.get("pmid")
        if pmid:
            by_pmid.setdefault(pmid, []).append(r)

    merged = {r["id"]: r for r in records}
    for pmid, group in by_pmid.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda r: _SOURCE_PRIORITY.get(r["source_type"], 0),
                         reverse=True)
        winner = ordered[0]
        merged_ids = list((winner.get("extras") or {}).get("dedup_merged_ids") or [])
        for other in ordered[1:]:
            if other["id"] in merged:
                del merged[other["id"]]
            for fld in ("pmcid", "doi", "journal", "mesh_terms", "keywords",
                        "publication_types", "page", "authors"):
                if not winner.get(fld) and other.get(fld):
                    winner[fld] = other[fld]
            wt, ot = set(winner.get("topics") or []), set(other.get("topics") or [])
            if ot - wt:
                winner["topics"] = sorted(wt | ot)
            merged_ids.append(other["id"])
        if merged_ids:
            winner["extras"] = dict(winner.get("extras") or {})
            winner["extras"]["dedup_merged_ids"] = sorted(set(merged_ids))
    return list(merged.values())


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
