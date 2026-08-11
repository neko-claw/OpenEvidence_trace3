"""PubMed E-utilities 采集：esearch + efetch，转标准 Evidence"""
from __future__ import annotations

import json
import os
import re
import time
import hashlib
import urllib.parse
from typing import Any

import httpx

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class PubMedClient:
    """带缓存与限速的 PubMed 客户端。响应缓存到 data/raw/"""

    def __init__(self, cache_dir: str = "data/raw/pubmed", sleep: float = 0.4):
        self.cache_dir = cache_dir
        self.sleep = sleep
        os.makedirs(cache_dir, exist_ok=True)

    def _cache_path(self, key: str) -> str:
        """长 key（URL 编码查询词/大批量 PMID）用 hash 缩略，避免文件名超 255 字节"""
        if len(key) <= 80:
            return os.path.join(self.cache_dir, f"{key}.json")
        h = hashlib.sha1(key.encode()).hexdigest()[:20]
        return os.path.join(self.cache_dir, f"{h}.json")

    def _cache_get(self, key: str) -> Any | None:
        path = self._cache_path(key)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return None

    def _cache_put(self, key: str, data: Any) -> None:
        path = self._cache_path(key)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def search(self, query: str, retmax: int = 20) -> list[str]:
        """esearch -> PMID 列表"""
        cache_key = "search_" + urllib.parse.quote(query[:100])
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        resp = httpx.get(
            f"{BASE}/esearch.fcgi",
            params={"db": "pubmed", "term": query, "retmax": retmax, "retmode": "json"},
            timeout=60,
        )
        resp.raise_for_status()
        pmids = resp.json()["esearchresult"].get("idlist", [])
        self._cache_put(cache_key, pmids)
        time.sleep(self.sleep)
        return pmids

    def fetch(self, pmids: list[str]) -> list[dict]:
        """efetch -> 摘要记录（分批 100 条）"""
        out = []
        for i in range(0, len(pmids), 100):
            batch = pmids[i:i + 100]
            cache_key = "fetch_" + "_".join(batch)
            cached = self._cache_get(cache_key)
            if cached is not None:
                out.extend(cached)
                continue
            resp = httpx.get(
                f"{BASE}/efetch.fcgi",
                params={"db": "pubmed", "id": ",".join(batch), "retmode": "xml"},
                timeout=120,
            )
            resp.raise_for_status()
            parsed = self._parse_xml(resp.text)
            self._cache_put(cache_key, parsed)
            out.extend(parsed)
            time.sleep(self.sleep)
        return out

    @staticmethod
    def _parse_xml(xml: str) -> list[dict]:
        """轻量 XML 解析：只取题目、摘要、作者、年份、DOI/PMID。不引第三方解析库亦可替换为 xml.etree"""
        import xml.etree.ElementTree as ET
        records = []
        root = ET.fromstring(xml)
        for art in root.iter("PubmedArticle"):
            pmid = (art.findtext(".//PMID") or "").strip()
            title = (art.findtext(".//ArticleTitle") or "").strip()
            abstract_parts = [t.text or "" for t in art.findall(".//AbstractText")]
            abstract = re.sub(r"\s+", " ", " ".join(abstract_parts)).strip()
            authors = ", ".join(
                f"{a.findtext('LastName','')} {a.findtext('ForeName','')}".strip()
                for a in art.findall(".//AuthorList/Author")
            )[:500]
            year = (art.findtext(".//PubDate/Year") or art.findtext(".//PubDate/MedlineDate") or "")[:4]
            doi = (art.findtext(".//ArticleId[@IdType='doi']") or "").strip()
            records.append({
                "pmid": pmid, "title": title, "abstract": abstract,
                "authors": authors, "year": year, "doi": doi,
            })
        return records


def to_evidence(rec: dict, query: str = "", source_type: str = "pubmed") -> dict:
    """PubMed 记录 -> 标准 Evidence dict"""
    import hashlib
    text = (rec.get("abstract") or "")[:4000]
    url = f"https://pubmed.ncbi.nlm.nih.gov/{rec.get('pmid','')}/"
    published = rec.get("year", "") + "-01-01" if rec.get("year") else ""
    content_hash = hashlib.sha1((rec.get("title","") + text).encode()).hexdigest()[:16]
    return {
        "id": f"pmid_{rec.get('pmid','')}",
        "source_type": source_type,
        "title": rec.get("title", ""),
        "text": text,
        "authors": rec.get("authors", ""),
        "published_at": published,
        "url": url,
        "pmid": rec.get("pmid", ""),
        "doi": rec.get("doi", ""),
        "evidence_level": "unknown",
        "content_hash": content_hash,
        "query": query,
    }


def collect_pubmed(query: str, retmax: int = 20, cache_dir: str = "data/raw/pubmed") -> list[dict]:
    """一键：搜索 -> 抓取 -> 转 Evidence dict"""
    client = PubMedClient(cache_dir=cache_dir)
    pmids = client.search(query, retmax=retmax)
    recs = client.fetch(pmids)
    return [to_evidence(r, query=query) for r in recs if r.get("abstract")]
