"""ClinicalTrials.gov API v2 采集：NCT 试验 -> 标准 Evidence"""
from __future__ import annotations

import hashlib
import json
import os
import time

import httpx

BASE = "https://clinicaltrials.gov/api/v2"


class CTGovClient:
    def __init__(self, cache_dir: str = "data/raw/ctgov", sleep: float = 0.3):
        self.cache_dir = cache_dir
        self.sleep = sleep
        os.makedirs(cache_dir, exist_ok=True)

    def search(self, query: str, page_size: int = 20) -> list[dict]:
        """搜索返回原始 protocolSection 记录列表（v2 API 用 pageToken 翻页，不接受 page 数字）"""
        cache_key = "search_" + hashlib.sha1(query.encode()).hexdigest()[:16]
        path = os.path.join(self.cache_dir, f"{cache_key}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        out = []
        page_token = None
        for _ in range(3):
            params = {
                "query.term": query,
                "pageSize": min(100, page_size),
                "fields": "protocolSection",
                "format": "json",
            }
            if page_token:
                params["pageToken"] = page_token
            resp = httpx.get(f"{BASE}/studies", params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            out.extend(data.get("studies", []))
            page_token = data.get("nextPageToken")
            if not page_token or len(out) >= page_size:
                break
            time.sleep(self.sleep)
        out = out[:page_size]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        return out


def to_evidence(study: dict) -> dict:
    """protocolSection -> Evidence dict"""
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    design = ps.get("designModule", {})
    cond = ps.get("conditionsModule", {})
    intv = ps.get("armsInterventionsModule", {})
    desc = ps.get("descriptionModule", {})
    nct = ident.get("nctId", "")
    title = ident.get("briefTitle", "")
    summary = (desc.get("briefSummary", "") or "")[:4000]
    interventions = ", ".join(
        i.get("name", "") for i in intv.get("interventions", []) if i.get("name"))
    text = f"{summary}\n干预: {interventions}".strip()
    content_hash = hashlib.sha1((title + text).encode()).hexdigest()[:16]
    return {
        "id": f"nct_{nct}",
        "source_type": "clinicaltrial",
        "title": title,
        "text": text,
        "published_at": (status.get("lastUpdatePostDateStruct", {}) or {}).get("date", ""),
        "url": f"https://clinicaltrials.gov/study/{nct}",
        "nct_id": nct,
        "evidence_level": "rct" if "PARALLEL" in str(design.get("designInfo", {})) else "trial",
        "population": " | ".join(cond.get("conditions", [])),
        "intervention": interventions,
        "status": status.get("overallStatus", ""),
        "content_hash": content_hash,
    }


def collect_ctg(query: str, page_size: int = 20, cache_dir: str = "data/raw/ctgov") -> list[dict]:
    client = CTGovClient(cache_dir=cache_dir)
    studies = client.search(query, page_size=page_size)
    return [to_evidence(s) for s in studies if s.get("protocolSection", {}).get("identificationModule", {}).get("nctId")]
