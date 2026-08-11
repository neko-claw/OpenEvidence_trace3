"""PubMed E-utilities 连接器：esearch + efetch，XML 解析为标准记录。"""
from __future__ import annotations

import json
import logging
import re

import xml.etree.ElementTree as ET

from .. import config
from ..http_utils import fetch_json, fetch_text

log = logging.getLogger("ingestion.pubmed")

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _base_params():
    params = {"tool": "OpenEvidence-MVP", "email": config.NCBI_EMAIL}
    if config.NCBI_API_KEY:
        params["api_key"] = config.NCBI_API_KEY
    return params


def esearch(term: str, retmax: int = 300, sort=None):
    """执行 esearch，返回 PMID 列表。"""
    params = {**_base_params(), "db": "pubmed", "term": term,
              "retmax": retmax, "retmode": "json"}
    if sort:
        params["sort"] = sort
    data = fetch_json(f"{EUTILS}/esearch.fcgi", params=params,
                      headers={"User-Agent": config.USER_AGENT},
                      sleep=config.PUBMED_SLEEP)
    res = data.get("esearchresult", {})
    idlist = res.get("idlist", [])
    log.info("esearch(%s...) -> %d PMIDs (total %s)",
             term[:60], len(idlist), res.get("count"))
    return idlist


def efetch_articles(pmids):
    """分批 efetch（每批 200 个 PMID），返回解析后的记录列表。"""
    records = []
    for i in range(0, len(pmids), 200):
        batch = pmids[i:i + 200]
        params = {**_base_params(), "db": "pubmed", "id": ",".join(batch),
                  "retmode": "xml", "rettype": "abstract"}
        xml_text = fetch_text(f"{EUTILS}/efetch.fcgi", params=params,
                              headers={"User-Agent": config.USER_AGENT},
                              sleep=config.PUBMED_SLEEP)
        parsed = parse_articles_xml(xml_text)
        records.extend(parsed)
        log.info("efetch batch %d/%d -> %d parsed records",
                 i // 200 + 1, (len(pmids) - 1) // 200 + 1, len(parsed))
    return records


# ------------------------------------------------------------------ XML 解析

def _text(elem):
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def _pubdate_iso(article):
    """从 JournalIssue/PubDate 与 ArticleDate 提取 ISO 日期或年份。"""
    jd = article.find("Journal/JournalIssue")
    year = month = day = None
    if jd is not None:
        pd = jd.find("PubDate")
        if pd is not None:
            year = _text(pd.find("Year")) or None
            month = _text(pd.find("Month")) or None
            day = _text(pd.find("Day")) or None
            if not year:
                md = _text(pd.find("MedlineDate"))
                m = re.search(r"(\d{4})", md)
                if m:
                    year = m.group(1)
    if not year:
        ad = article.find("ArticleDate")
        if ad is not None:
            year = _text(ad.find("Year")) or None
            month = _text(ad.find("Month")) or None
            day = _text(ad.find("Day")) or None
    if not year:
        return None, None
    try:
        month = int(month) if month else None
        day = int(day) if day else None
    except ValueError:
        month = day = None
    if year and month and day:
        return f"{year}-{month:02d}-{day:02d}", int(year)
    if year and month:
        return f"{year}-{month:02d}", int(year)
    return year, int(year)


def _parse_one(article: ET.Element) -> dict:
    mc = article.find("MedlineCitation")
    art = mc.find("Article")
    pmid = _text(mc.find("PMID"))
    title = _text(art.find("ArticleTitle")) or ""

    # 摘要（含分段 Label）
    abstract = ""
    abs_el = art.find("Abstract")
    if abs_el is not None:
        parts = []
        for at in abs_el.findall("AbstractText"):
            label = at.get("Label")
            txt = "".join(at.itertext()).strip()
            if txt:
                parts.append(f"{label}: {txt}" if label else txt)
        abstract = " ".join(parts)

    # 作者
    authors = []
    al = art.find("AuthorList")
    if al is not None:
        for a in al.findall("Author"):
            coll = a.find("CollectiveName")
            if coll is not None:
                authors.append(_text(coll))
                continue
            ln = a.find("LastName")
            if ln is not None:
                name = _text(ln)
                fn = _text(a.find("ForeName"))
                if fn:
                    name = f"{name} {fn}"
                authors.append(name)

    journal = (_text(art.find("Journal/Title"))
               or _text(art.find("Journal/ISOAbbreviation")) or "")
    published_at, year = _pubdate_iso(art)

    # DOI
    doi = None
    pdata = article.find("PubmedData")
    if pdata is not None:
        for aid in pdata.findall("ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = _text(aid) or None

    pub_types = [_text(p) for p in art.findall("PublicationTypeList/PublicationType")]
    mesh = [_text(m) for m in mc.findall("MeshHeadingList/MeshHeading/DescriptorName")]
    keywords = []
    for kl in mc.findall("KeywordList/Keyword"):
        t = _text(kl)
        if t:
            keywords.append(t)

    return {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "authors": authors,
        "journal": journal,
        "published_at": published_at,
        "year": year,
        "doi": doi,
        "publication_types": pub_types,
        "mesh_terms": mesh,
        "keywords": keywords,
    }


def parse_articles_xml(xml_text: str):
    root = ET.fromstring(xml_text)
    records = []
    for child in root:
        if child.tag == "PubmedArticle":
            try:
                records.append(_parse_one(child))
            except Exception as exc:  # 单条解析失败不阻塞整批
                log.warning("parse article failed: %s", exc)
    return records


def save_idlist(slug: str, pmids):
    out = config.PUBMED_DIR / "idlists" / f"{slug}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"slug": slug, "pmids": pmids}, ensure_ascii=False), encoding="utf-8")
    return out


def load_idlist(slug: str):
    out = config.PUBMED_DIR / "idlists" / f"{slug}.json"
    if not out.exists():
        return None
    return json.loads(out.read_text(encoding="utf-8"))["pmids"]


def save_articles(records, batch_no: int):
    out = config.PUBMED_ARTICLE_DIR / f"records_{batch_no:04d}.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
