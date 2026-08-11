"""ClinicalTrials.gov Data API v2 连接器：抓取干预性试验并保存原始响应。"""
from __future__ import annotations

import json
import logging

from .. import config
from ..http_utils import fetch_json

log = logging.getLogger("ingestion.clinicaltrials")

BASE = "https://clinicaltrials.gov/api/v2/studies"


def fetch_studies(cond: str, max_records: int = 800):
    """按疾病条件抓取干预性研究，返回 protocolSection 字典列表。"""
    studies = []
    page_token = None
    params = {
        "query.cond": cond,
        "pageSize": 1000,
        "countTotal": "true",
        "filter.advanced": "AREA[StudyType]INTERVENTIONAL",
    }
    while len(studies) < max_records:
        if page_token:
            params["pageToken"] = page_token
        data = fetch_json(BASE, params=params,
                          headers={"User-Agent": config.USER_AGENT},
                          sleep=config.TRIALS_SLEEP)
        batch = data.get("studies", [])
        studies.extend(batch)
        total = data.get("totalCount", len(studies))
        page_token = data.get("nextPageToken")
        log.info("trials(cond=%s) fetched %d, totalCount=%s",
                 cond, len(studies), total)
        if not batch or not page_token:
            break
    return studies[:max_records]


def save_raw(slug: str, studies):
    out = config.TRIALS_DIR / f"{slug}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"slug": slug, "count": len(studies), "studies": studies},
                              ensure_ascii=False), encoding="utf-8")
    return out


def parse_study(study: dict) -> dict:
    """把一条 study 的 protocolSection 摊平成标准记录。"""
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    status = ps.get("statusModule", {})
    design = ps.get("designModule", {})
    cond_mod = ps.get("conditionModule", {})
    interv_mod = ps.get("interventionModule", {})
    elig = ps.get("eligibilityModule", {})
    outcome_mod = ps.get("outcomeModule", {})
    sponsor = ps.get("sponsorSection", {}).get("leadSponsor", {})
    desc = ps.get("descriptionModule", {})

    nct = ident.get("nctId", "")

    def _date(ds):
        if not ds:
            return None
        return ds.get("date")

    start = _date(status.get("startDateStruct"))
    last_update = _date(status.get("lastUpdatePostDateStruct"))
    published_at = start

    enrollment = design.get("enrollmentInfo", {})
    phases = design.get("phases", [])
    interventions = interv_mod.get("interventions", [])
    conditions = cond_mod.get("conditions", [])

    population = None
    sex = elig.get("sex")
    min_age = elig.get("minimumAge")
    max_age = elig.get("maximumAge")
    if sex or min_age or max_age:
        population = " | ".join(filter(None, [sex, min_age, max_age]))

    outcome_measures = []
    for po in outcome_mod.get("primaryOutcomes", []) or []:
        if po.get("measure"):
            outcome_measures.append(po["measure"])

    brief_summary = ""
    bs = desc.get("briefSummary")
    if isinstance(bs, dict):
        brief_summary = " ".join(bs.get("textBlock", []) or [])
    elif isinstance(bs, str):
        brief_summary = bs

    return {
        "nct_id": nct,
        "title": ident.get("briefTitle", "") or ident.get("officialTitle", ""),
        "official_title": ident.get("officialTitle", ""),
        "brief_summary": brief_summary,
        "status": status.get("overallStatus"),
        "start_date": start,
        "last_update_date": last_update,
        "published_at": published_at,
        "year": int(published_at[:4]) if published_at else None,
        "phase": ",".join(phases),
        "enrollment": enrollment.get("count"),
        "enrollment_type": enrollment.get("type"),
        "study_type": design.get("studyType"),
        "conditions": conditions,
        "interventions": [i.get("name") for i in interventions if i.get("name")],
        "intervention_types": [i.get("type") for i in interventions if i.get("type")],
        "sponsor": sponsor.get("name"),
        "population": population,
        "primary_outcomes": outcome_measures,
        "url": f"https://clinicaltrials.gov/study/{nct}",
    }
