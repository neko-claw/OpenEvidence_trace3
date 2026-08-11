"""人工确认的权威指南清单（高血压 + 血脂）。

设计原则（对应实施规划 3.3 / 5.2）：
- “人工确认”指：由人工认定这些是权威组织发布的指南/共识；
- 指南的 PMID/DOI/摘要等机器可读元数据**不从人工记忆写入**，而是通过
  `config.GUIDELINE_TITLE_QUERIES` 在 PubMed 上检索，再经过
  `verify_terms`（标题必须包含）+ `exclude_terms`（排除评论/勘误等）+ 年份/期刊约束
  三重验证后才回填（`enrich_from_pubmed`），杜绝编造编号与错配；
- 检索不到可靠记录的（如 NICE / WHO 网页版、妊娠期指南）保留为元数据记录，
  标注 enriched=False，不强行回填。
"""
from __future__ import annotations

import logging

log = logging.getLogger("ingestion.guidelines")

# key: 指南唯一键；query_slug: 对应 config.GUIDELINE_TITLE_QUERIES 的 slug
CURATED_GUIDELINES = [
    {
        "key": "cn-hyp-2018",
        "title": "中国高血压防治指南（2018年修订版）",
        "title_en": "2018 Chinese Guidelines for Prevention and Treatment of Hypertension",
        "org": "中国高血压防治指南修订委员会",
        "year": 2018,
        "topic": "hypertension",
        "query_slug": "g_cn_hyp_2018",
        "verify_terms": ["chinese guidelines", "prevention and treatment of hypertension", "2018"],
        "exclude_terms": ["comments on", "comment on"],
        "prefer_journal": None,
        "url": "https://www.cma.org.cn/",
        "notes": "人工确认：中国高血压防治指南修订委员会发布，J Geriatr Cardiol 2019 英文版。",
    },
    {
        "key": "cn-hyp-2024",
        "title": "中国高血压防治指南（2024年修订版）",
        "title_en": "Clinical practice guideline for the management of hypertension in China (2024)",
        "org": "中国高血压防治指南修订委员会（中华医学会心血管病学分会等）",
        "year": 2024,
        "topic": "hypertension",
        "query_slug": "g_cn_hyp_2024",
        "verify_terms": ["hypertension", "guideline", "china", "management of hypertension"],
        "exclude_terms": ["association of", "prevalence of", "stage 1"],
        "prefer_journal": None,
        "url": "https://www.cma.org.cn/",
        "notes": "人工确认：2024 年发布的最新版中国高血压防治指南；PubMed 收录英文版于 Chinese Medical Journal。",
    },
    {
        "key": "cn-lipid-2023",
        "title": "中国血脂管理指南（2023年）",
        "title_en": "2023 Chinese guideline for lipid management",
        "org": "中国血脂管理指南修订联合专家委员会",
        "year": 2023,
        "topic": "lipids",
        "query_slug": "g_cn_lipid_2023",
        "verify_terms": ["2023 chinese guideline for lipid management"],
        "exclude_terms": ["a new guideline rich in"],
        "prefer_journal": None,
        "url": "https://www.cma.org.cn/",
        "notes": "人工确认：中国血脂管理指南修订联合专家委员会发布，中华心血管病杂志发表。",
    },
    {
        "key": "cn-lipid-primary-2024",
        "title": "中国血脂管理指南（基层版2024）",
        "title_en": "Chinese guideline for lipid management (primary care version 2024)",
        "org": "中国血脂管理指南修订联合专家委员会 等",
        "year": 2024,
        "topic": "lipids",
        "query_slug": "g_cn_lipid_primary_2024",
        "verify_terms": ["chinese guideline for lipid management", "primary care version"],
        "exclude_terms": [],
        "prefer_journal": None,
        "url": "https://www.cma.org.cn/",
        "notes": "人工确认：面向基层的 2024 版中国血脂管理指南。",
    },
    {
        "key": "cn-elderly-hyp-2019",
        "title": "中国老年高血压管理指南（2019）",
        "title_en": "2019 Chinese guideline for the management of hypertension in the elderly",
        "org": "中国老年医学学会高血压分会 等",
        "year": 2019,
        "topic": "hypertension",
        "query_slug": "g_cn_elder_hyp_2019",
        "verify_terms": ["chinese guideline", "hypertension in the elderly"],
        "exclude_terms": ["association of", "stage 1"],
        "prefer_journal": None,
        "url": "https://www.cma.org.cn/",
        "notes": "人工确认：中国老年医学学会等联合发布。",
    },
    {
        "key": "cn-elderly-hyp-2023",
        "title": "中国老年高血压管理指南（2023）",
        "title_en": "2023 Guideline for the management of hypertension in the elderly population in China",
        "org": "中国老年医学学会高血压分会、北京高血压防治协会 等",
        "year": 2023,
        "topic": "hypertension",
        "query_slug": "g_cn_elder_hyp_2023",
        "verify_terms": ["guideline for the management of hypertension in the elderly population in china", "2023"],
        "exclude_terms": [],
        "prefer_journal": None,
        "url": "https://www.cma.org.cn/",
        "notes": "人工确认：2023 版中国老年高血压管理指南，J Geriatr Cardiol 2024。",
    },
    {
        "key": "cn-pregnancy-hyp-2020",
        "title": "妊娠期高血压疾病诊治指南（2020）",
        "title_en": "Guideline for diagnosis and treatment of hypertensive disorders of pregnancy (2020)",
        "org": "中华医学会妇产科学分会妊娠期高血压疾病学组",
        "year": 2020,
        "topic": "hypertension",
        "query_slug": None,
        "verify_terms": [],
        "exclude_terms": [],
        "prefer_journal": None,
        "url": "https://www.cma.org.cn/",
        "notes": "人工确认：中华医学会妇产科学分会发布；PubMed 未检索到英文记录，保留元数据。",
    },
    {
        "key": "cn-rx-hyp-2017",
        "title": "高血压合理用药指南（第2版）",
        "title_en": "Guideline for rational antihypertensive drug use (2nd edition)",
        "org": "国家卫生计生委合理用药专家委员会 等",
        "year": 2017,
        "topic": "hypertension",
        "query_slug": None,
        "verify_terms": [],
        "exclude_terms": [],
        "prefer_journal": None,
        "url": "https://www.cma.org.cn/",
        "notes": "人工确认：国家卫生计生委合理用药专家委员会发布；PubMed 未检索到英文记录，保留元数据。",
    },
    {
        "key": "acc-aha-hbp-2017",
        "title": "2017 ACC/AHA Guideline for the Prevention, Detection, Evaluation, and Management of High Blood Pressure in Adults",
        "title_en": "2017 ACC/AHA Hypertension Guideline",
        "org": "American College of Cardiology / American Heart Association",
        "year": 2018,
        "topic": "hypertension",
        "query_slug": "g_accaha_hbp_2017",
        "verify_terms": ["guideline for the prevention, detection, evaluation, and management of high blood pressure in adults", "acc/aha"],
        "exclude_terms": ["correction to", "systematic review for", "response to", "executive summary", "letter", "commentary"],
        "prefer_journal": "hypertension",
        "url": "https://www.ahajournals.org/doi/10.1161/HYP.0000000000000065",
        "notes": "人工确认：ACC/AHA 发布，Hypertension 2018;71(6):e13-e115。",
    },
    {
        "key": "esh-2023",
        "title": "2023 ESH Guidelines for the management of arterial hypertension",
        "title_en": "2023 ESH Hypertension Guidelines",
        "org": "European Society of Hypertension",
        "year": 2023,
        "topic": "hypertension",
        "query_slug": "g_esh_2023",
        "verify_terms": ["esh guidelines", "arterial hypertension"],
        "exclude_terms": ["editors' commentary", "commentary", "comment on"],
        "prefer_journal": None,
        "url": "https://journals.lww.com/jhypertension/fulltext/2023/12000/2023_esh_guidelines_for_the_management_of.1.aspx",
        "notes": "人工确认：ESH 发布，J Hypertens 2023;41(12):1874-2071。",
    },
    {
        "key": "esc-2024",
        "title": "2024 ESC Guidelines for the management of elevated blood pressure and hypertension",
        "title_en": "2024 ESC Blood Pressure Guidelines",
        "org": "European Society of Cardiology",
        "year": 2024,
        "topic": "hypertension",
        "query_slug": "g_esc_2024",
        "verify_terms": ["esc guidelines", "elevated blood pressure and hypertension"],
        "exclude_terms": ["interpretation", "comment", "focus of the", "how practical", "innovation", "["],
        "prefer_journal": None,
        "url": "https://academic.oup.com/eurheartj/article/45/38/3912/7745794",
        "notes": "人工确认：ESC 发布，Eur Heart J 2024;45(38):3912-4018。",
    },
    {
        "key": "acc-aha-cholesterol-2018",
        "title": "2018 AHA/ACC Guideline on the Management of Blood Cholesterol",
        "title_en": "2018 AHA/ACC Cholesterol Guideline",
        "org": "American Heart Association / American College of Cardiology",
        "year": 2019,
        "topic": "lipids",
        "query_slug": "g_accaha_chol_2018",
        "verify_terms": ["guideline on the management of blood cholesterol", "aha/acc"],
        "exclude_terms": ["systematic review for", "executive summary", "correction"],
        "prefer_journal": "circulation",
        "url": "https://www.ahajournals.org/doi/10.1161/CIR.0000000000000625",
        "notes": "人工确认：AHA/ACC 发布，Circulation 2019;139(25):e1082-e1143。",
    },
    {
        "key": "esc-eas-2019",
        "title": "2019 ESC/EAS Guidelines for the management of dyslipidaemias: lipid modification to reduce cardiovascular risk",
        "title_en": "2019 ESC/EAS Dyslipidaemia Guidelines",
        "org": "European Society of Cardiology / European Atherosclerosis Society",
        "year": 2019,
        "topic": "lipids",
        "query_slug": "g_esc_eas_2019",
        "verify_terms": ["esc/eas guidelines", "dyslipidaemias"],
        "exclude_terms": ["corrigendum", "changing landscape", "commentary"],
        "prefer_journal": None,
        "url": "https://academic.oup.com/eurheartj/article/41/1/111/5556353",
        "notes": "人工确认：ESC/EAS 发布，Eur Heart J 2020;41(1):111-188。",
    },
    {
        "key": "esc-prevention-2021",
        "title": "2021 ESC Guidelines on cardiovascular disease prevention in clinical practice",
        "title_en": "2021 ESC CVD Prevention Guidelines",
        "org": "European Society of Cardiology",
        "year": 2021,
        "topic": "both",
        "query_slug": "g_esc_prev_2021",
        "verify_terms": ["esc guidelines on cardiovascular disease prevention in clinical practice"],
        "exclude_terms": ["editorial", "comment", "sports cardiology"],
        "prefer_journal": None,
        "url": "https://academic.oup.com/eurheartj/article/42/34/3227/6358713",
        "notes": "人工确认：ESC 发布，Eur Heart J 2021;42(34):3227-3337。",
    },
    {
        "key": "kdigo-bp-2021",
        "title": "KDIGO 2021 Clinical Practice Guideline for the Management of Blood Pressure in Chronic Kidney Disease",
        "title_en": "KDIGO 2021 BP in CKD Guideline",
        "org": "Kidney Disease: Improving Global Outcomes (KDIGO)",
        "year": 2021,
        "topic": "hypertension",
        "query_slug": "g_kdigo_bp_2021",
        "verify_terms": ["kdigo", "clinical practice guideline", "management of blood pressure in chronic kidney disease"],
        "exclude_terms": ["executive summary", "commentary", "implications", "comment on", "commentary on", "is the"],
        "prefer_journal": None,
        "url": "https://kdigo.org/guidelines/blood-pressure-in-ckd/",
        "notes": "人工确认：KDIGO 发布，Kidney Int 2021;99(3S):S1-S87。",
    },
    {
        "key": "who-hyp-2021",
        "title": "WHO Guideline for the pharmacological treatment of hypertension in adults",
        "title_en": "WHO 2021 Hypertension Treatment Guideline",
        "org": "World Health Organization",
        "year": 2021,
        "topic": "hypertension",
        "query_slug": "g_who_hyp_2021",
        "verify_terms": ["who guideline for the pharmacological treatment of hypertension"],
        "exclude_terms": [],
        "prefer_journal": None,
        "url": "https://www.who.int/publications/i/item/9789240033986",
        "notes": "人工确认：WHO 发布，2021-08-25；PubMed 收录为中文翻译条目（PMID 36791691），原指南以 WHO 官网为准。",
    },
    {
        "key": "nice-ng136",
        "title": "NICE guideline NG136: Hypertension in adults: diagnosis and management",
        "title_en": "NICE NG136 Hypertension",
        "org": "National Institute for Health and Care Excellence (NICE)",
        "year": 2019,
        "topic": "hypertension",
        "query_slug": None,
        "verify_terms": [],
        "exclude_terms": [],
        "prefer_journal": None,
        "url": "https://www.nice.org.uk/guidance/ng136",
        "notes": "人工确认：NICE 发布，2019-08（2023-03 更新）；非 PubMed 收录，保留官方链接。",
    },
    {
        "key": "nice-cg181",
        "title": "NICE guideline CG181: Cardiovascular disease: risk assessment and reduction, including lipid modification",
        "title_en": "NICE CG181 CVD Risk / Lipid Modification",
        "org": "National Institute for Health and Care Excellence (NICE)",
        "year": 2014,
        "topic": "lipids",
        "query_slug": None,
        "verify_terms": [],
        "exclude_terms": [],
        "prefer_journal": None,
        "url": "https://www.nice.org.uk/guidance/cg181",
        "notes": "人工确认：NICE 发布，2014-07（2023-01 更新）；非 PubMed 收录，保留官方链接。",
    },
]


def _norm(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (s or "").lower())


def _title_ok(record, g) -> bool:
    """验证候选记录标题：必须包含全部 verify_terms，且不含 exclude_terms。

    注意：PubMed XML 中常见不换行空格（\xa0），统一归一化后再匹配。
    """
    import re
    title = re.sub(r"[\xa0\u2007\u202f]+", " ", (record.get("title") or "")).lower()
    title = re.sub(r"\s+", " ", title)
    for t in g.get("verify_terms") or []:
        if t.lower() not in title:
            return False
    for t in g.get("exclude_terms") or []:
        if t.lower() in title:
            return False
    return True


def _pick_best(candidates, g):
    """在通过标题验证的候选中按 年份接近 + 期刊偏好 挑选最佳记录。"""
    if not candidates:
        return None

    def score(c):
        s = 0.0
        year_diff = abs((c.get("year") or 0) - (g.get("year") or 0))
        s -= year_diff * 2.0
        j = (c.get("journal") or "").lower().strip()
        pref = g.get("prefer_journal")
        if pref and (j == pref or (j.split()[0] if j else "") == pref):
            s += 1.0
        return s

    return max(candidates, key=score)


def enrich_from_pubmed(curated, pubmed_records, preferred=None):
    """用 PubMed 抓取的真实记录回填指南的 PMID/DOI/期刊/摘要。

    curated: 指南条目；pubmed_records: 已解析的 PubMed 记录列表。
    preferred: {query_slug: [pmid...]}，来自专门指南标题查询。
    回填必须通过 verify_terms / exclude_terms / 年份 / 期刊约束验证；
    未通过或 query_slug 为 None 的条目保留 enriched=False（元数据记录）。
    """
    by_pmid = {r.get("pmid"): r for r in pubmed_records if r.get("pmid")}
    enriched = []
    for g in curated:
        rec = dict(g)
        slug = g.get("query_slug")
        best = None
        if slug and preferred:
            cands = []
            for pmid in preferred.get(slug, []):
                r = by_pmid.get(pmid)
                if r and _title_ok(r, g):
                    cands.append(r)
            best = _pick_best(cands, g)
        if best is not None:
            rec["enriched"] = True
            rec["enrich_score"] = round(1.0, 3)
            rec["pmid"] = best.get("pmid")
            rec["doi"] = best.get("doi")
            rec["journal"] = best.get("journal")
            rec["abstract"] = best.get("abstract", "")
            if best.get("year") and g.get("year") and \
                    abs(best["year"] - g["year"]) <= 2:
                rec["year"] = best["year"]
        else:
            rec["enriched"] = False
            rec["enrich_score"] = 0.0
            rec["pmid"] = None
            rec["doi"] = None
            rec["journal"] = None
            rec["abstract"] = ""
        log.info("guideline %s: enriched=%s pmid=%s", g["key"], rec["enriched"], rec.get("pmid"))
        enriched.append(rec)
    return enriched
