"""全局配置：路径、速率限制、检索查询。

速率限制说明（无 API key 时）：
- PubMed E-utilities  : 3 req/s 上限，这里取 0.4s/req（2.5 req/s）留余量
- Europe PMC REST     : 未认证约 4 req/s，取 0.3s/req
- ClinicalTrials v2   : 无鉴权，取 0.3s/req
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- 路径
ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
ARTIFACTS = ROOT / "artifacts"

PUBMED_DIR = DATA_RAW / "pubmed"
PUBMED_ARTICLE_DIR = PUBMED_DIR / "articles"
TRIALS_DIR = DATA_RAW / "clinicaltrials"
EPMC_DIR = DATA_RAW / "europepmc"
EPMC_FULLTEXT_DIR = EPMC_DIR / "fulltext"
GUIDELINE_DIR = DATA_RAW / "guidelines"

# ---------------------------------------------------------------- 网络
USER_AGENT = "OpenEvidence-MVP-dataset-crawler/0.1 (educational project; non-clinical use)"
NCBI_EMAIL = os.environ.get("NCBI_EMAIL", "openevidence-mvp@example.com")
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "") or None

PUBMED_SLEEP = 0.4
EPMC_SLEEP = 0.3
TRIALS_SLEEP = 0.3

# ---------------------------------------------------------------- 检索查询
# 每个查询: (slug, term, retmax, sort)
# sort: None=relevance, "pub_date"=按日期倒序（保证最新研究覆盖）
PUBMED_QUERIES = [
    # ---- 高血压：指南 ----
    ("hyp_guideline",
     'hypertension[MeSH] AND (practice guideline[pt] OR guideline[ti])',
     200, None),
    # ---- 高血压：系统综述 / Meta 分析 ----
    ("hyp_sysrev",
     'hypertension[MeSH] AND systematic review[pt] AND ("2019"[dp]:"2026"[dp])',
     400, None),
    ("hyp_meta",
     'hypertension[MeSH] AND meta-analysis[pt] AND ("2018"[dp]:"2026"[dp])',
     300, None),
    # ---- 高血压：最新 RCT / 临床试验 ----
    ("hyp_rct",
     'hypertension[MeSH] AND randomized controlled trial[pt] AND ("2020"[dp]:"2026"[dp])',
     400, "pub_date"),
    # ---- 高血压：治疗管理综述 ----
    ("hyp_mgmt_review",
     'hypertension[tiab] AND (management OR treatment) AND review[pt] AND ("2020"[dp]:"2026"[dp])',
     400, None),
    ("antihypertensive_drugs",
     '("antihypertensive agents"[MeSH] OR antihypertensive[tiab]) AND (efficacy OR safety) AND ("2020"[dp]:"2026"[dp])',
     400, None),
    # ---- 高血压：细分主题 ----
    ("resistant_hyp",
     'resistant hypertension[tiab] AND ("2019"[dp]:"2026"[dp])',
     300, None),
    ("bp_measurement",
     '(blood pressure measurement[tiab] OR home blood pressure monitoring[tiab] OR ambulatory blood pressure[tiab]) AND ("2019"[dp]:"2026"[dp])',
     300, None),
    ("sodium_hyp",
     '(sodium[MeSH] OR dietary salt[tiab] OR salt intake[tiab]) AND hypertension AND ("2019"[dp]:"2026"[dp])',
     300, None),
    ("dash_diet",
     '("DASH diet"[tiab] OR "dietary approaches to stop hypertension"[tiab]) AND ("2019"[dp]:"2026"[dp])',
     200, None),
    ("elderly_hyp",
     '(hypertension AND (elderly[tiab] OR "older adults"[tiab] OR aged[MeSH])) AND ("2019"[dp]:"2026"[dp])',
     300, None),
    ("pregnancy_hyp",
     '(hypertension AND (pregnancy[MeSH] OR gestational[tiab] OR preeclampsia[tiab])) AND ("2019"[dp]:"2026"[dp])',
     300, None),
    ("hyp_diabetes",
     '(hypertension AND diabetes[MeSH]) AND ("2019"[dp]:"2026"[dp])',
     300, None),
    ("lifestyle_bp",
     '(blood pressure[tiab] OR hypertension[tiab]) AND (physical activity[tiab] OR exercise[tiab] OR "weight loss"[tiab] OR alcohol[tiab]) AND ("2020"[dp]:"2026"[dp])',
     300, None),
    # ---- 血脂：指南 ----
    ("lipid_guideline",
     '(dyslipidemias[MeSH] OR hyperlipidemia[tiab] OR hypercholesterolemia[MeSH] OR hypertriglyceridemia[MeSH]) AND (practice guideline[pt] OR guideline[ti])',
     200, None),
    # ---- 血脂：系统综述 / Meta 分析 ----
    ("lipid_sysrev",
     '(dyslipidemias[MeSH] OR hypercholesterolemia[MeSH] OR hypertriglyceridemia[MeSH]) AND systematic review[pt] AND ("2019"[dp]:"2026"[dp])',
     400, None),
    # ---- 血脂：治疗与降脂药物 ----
    ("ldl_treatment",
     '("LDL cholesterol"[tiab] OR "low-density lipoprotein"[tiab] OR LDL-C[tiab]) AND (treatment[tiab] OR management[tiab] OR lowering[tiab]) AND ("2020"[dp]:"2026"[dp])',
     400, None),
    ("statins",
     'statins[MeSH] AND ("2020"[dp]:"2026"[dp])',
     400, "pub_date"),
    ("pcsk9",
     '("PCSK9 inhibitors"[tiab] OR alirocumab[tiab] OR evolocumab[tiab] OR inclisiran[tiab]) AND ("2019"[dp]:"2026"[dp])',
     300, None),
    ("ezetimibe_bempedoic",
     '(ezetimibe[tiab] OR "bempedoic acid"[tiab]) AND ("2019"[dp]:"2026"[dp])',
     200, None),
    ("triglycerides",
     '(triglycerides[MeSH] OR hypertriglyceridemia[tiab]) AND ("2019"[dp]:"2026"[dp])',
     300, None),
    ("omega3_lipids",
     '("omega-3"[tiab] OR "icosapent ethyl"[tiab] OR "fish oil"[tiab]) AND (lipids[tiab] OR cardiovascular[tiab]) AND ("2019"[dp]:"2026"[dp])',
     200, None),
    ("mediterranean_diet",
     '("mediterranean diet"[tiab]) AND (cardiovascular[tiab] OR lipids[tiab] OR "blood pressure"[tiab] OR cholesterol[tiab]) AND ("2019"[dp]:"2026"[dp])',
     300, None),
    ("lipoprotein_a",
     '("lipoprotein(a)"[tiab] OR "Lp(a)"[tiab]) AND ("2020"[dp]:"2026"[dp])',
     200, None),
    ("cv_risk_both",
     '(cardiovascular risk[tiab] AND (hypertension[tiab] OR lipid[tiab] OR cholesterol[tiab])) AND systematic review[pt] AND ("2020"[dp]:"2026"[dp])',
     300, None),
    # ---- 近三年宽覆盖（保证总量与时效性） ----
    ("broad_hypertension",
     'hypertension[MeSH] AND English[lang] AND hasabstract[text] AND ("2022"[dp]:"2026"[dp])',
     600, "pub_date"),
    ("broad_lipids",
     '(dyslipidemias[MeSH] OR hypercholesterolemia[MeSH] OR hypertriglyceridemia[MeSH] OR hyperlipidemia[tiab]) AND English[lang] AND hasabstract[text] AND ("2022"[dp]:"2026"[dp])',
     600, "pub_date"),
]

# 每个检索查询对应的主题标签（用于记录级 topic 标注）
QUERY_TOPIC = {
    "hyp_guideline": ["hypertension"], "hyp_sysrev": ["hypertension"], "hyp_meta": ["hypertension"],
    "hyp_rct": ["hypertension"], "hyp_mgmt_review": ["hypertension"], "antihypertensive_drugs": ["hypertension"],
    "resistant_hyp": ["hypertension"], "bp_measurement": ["hypertension"], "sodium_hyp": ["hypertension"],
    "dash_diet": ["hypertension", "lipids"], "elderly_hyp": ["hypertension"], "pregnancy_hyp": ["hypertension"],
    "hyp_diabetes": ["hypertension", "lipids"], "lifestyle_bp": ["hypertension"],
    "lipid_guideline": ["lipids"], "lipid_sysrev": ["lipids"], "ldl_treatment": ["lipids"],
    "statins": ["lipids"], "pcsk9": ["lipids"], "ezetimibe_bempedoic": ["lipids"],
    "triglycerides": ["lipids"], "omega3_lipids": ["lipids"], "mediterranean_diet": ["lipids"],
    "lipoprotein_a": ["lipids"], "cv_risk_both": ["hypertension", "lipids"],
    "broad_hypertension": ["hypertension"], "broad_lipids": ["lipids"],
}

# 指南标题专用检索（短关键词组合；长短语引号检索在 PubMed 上不可靠，故用可验证的关键词）
# 每个查询: (slug, term, retmax)；结果需经 guidelines.verify_terms 三重验证后才回填
GUIDELINE_TITLE_QUERIES = [
    ("g_cn_hyp_2018",
     'Chinese[Title] AND hypertension[Title] AND prevention[Title] AND (2018[dp] OR 2019[dp])', 10),
    ("g_cn_hyp_2024",
     'hypertension[Title] AND China[tiab] AND guideline[Title] AND (2024[dp] OR 2025[dp])', 10),
    ("g_cn_lipid_2023",
     'Chinese[Title] AND guideline[Title] AND (lipid[Title] OR dyslipidemia[Title] OR dyslipidaemia[Title]) AND (2023[dp] OR 2024[dp])', 10),
    ("g_cn_lipid_primary_2024",
     'Chinese[Title] AND lipid[Title] AND guideline[Title] AND (2024[dp] OR 2025[dp])', 10),
    ("g_cn_elder_hyp_2019",
     '(Chinese[Title] OR China[Title]) AND elderly[Title] AND hypertension[Title] AND guideline[Title] AND (2019[dp] OR 2020[dp])', 10),
    ("g_cn_elder_hyp_2023",
     '(Chinese[Title] OR China[Title]) AND elderly[Title] AND hypertension[Title] AND guideline[Title] AND (2023[dp] OR 2024[dp] OR 2025[dp])', 10),
    ("g_accaha_hbp_2017",
     '"2017 ACC/AHA"[Title] AND "High Blood Pressure"[Title]', 50),
    ("g_esh_2023",
     '"ESH"[Title] AND "arterial hypertension"[Title] AND "2023"[dp]', 10),
    ("g_esc_2024",
     '"ESC"[Title] AND "elevated blood pressure"[Title] AND "2024"[dp]', 10),
    ("g_accaha_chol_2018",
     '"AHA/ACC"[Title] AND "Blood Cholesterol"[Title] AND "2018"[dp]', 10),
    ("g_esc_eas_2019",
     '"dyslipidaemias"[Title] AND "2019"[dp] AND "ESC"[Title]', 10),
    ("g_esc_prev_2021",
     '"ESC Guidelines"[Title] AND "cardiovascular disease"[Title] AND "2021"[dp]', 10),
    ("g_kdigo_bp_2021",
     'KDIGO[Title] AND "blood pressure"[Title] AND (2021[dp] OR 2022[dp])', 20),
    ("g_who_hyp_2021",
     '"WHO Guideline"[tiab] AND hypertension[tiab] AND (2021[dp] OR 2022[dp] OR 2023[dp])', 10),
]

# ---------------------------------------------------------------- ClinicalTrials.gov
# (slug, cond 查询条件, 每个主题最多抓取条数)
TRIAL_TOPICS = [
    ("hypertension", "hypertension", 800),
    ("dyslipidemia", "dyslipidemia OR hyperlipidemia OR hypercholesterolemia OR hypertriglyceridemia", 800),
]

# ---------------------------------------------------------------- Europe PMC（全文/降级补充）
# (slug, query, pageSize)
EPMC_QUERIES = [
    ("oa_sysrev",
     '(TITLE:"hypertension" OR TITLE:"blood pressure" OR TITLE:"dyslipidemia" OR TITLE:"cholesterol" OR TITLE:"statin" OR TITLE:"lipid") '
     'AND (TITLE:"systematic review" OR TITLE:"meta-analysis" OR TITLE:"guideline") AND OPEN_ACCESS:Y',
     500),
    ("oa_rct",
     '(TITLE:"hypertension" OR TITLE:"blood pressure" OR TITLE:"statin" OR TITLE:"cholesterol" OR TITLE:"lipid") '
     'AND (TITLE:"randomized" OR TITLE:"trial") AND OPEN_ACCESS:Y AND PUB_YEAR:[2020 TO 2026]',
     500),
]
# 下载全文的 OA 文献上限（只对有 PMC 全文的文献下载）
EPMC_FULLTEXT_LIMIT = 120
# 全文分块参数
FULLTEXT_CHUNK_MAX_CHARS = 4000
FULLTEXT_CHUNK_CAP_PER_ARTICLE = 20
FULLTEXT_SKIP_SECTIONS = {"references", "author information", "competing interests",
                          "declarations", "funding", "acknowledgements", "abbreviations"}

# ---------------------------------------------------------------- 主题标签词表
HYPERTENSION_TERMS = [
    "hypertension", "hypertensive", "blood pressure", "antihypertensive",
    "hypertensive crisis", "systolic", "diastolic", "preeclampsia", "eclampsia",
]
LIPID_TERMS = [
    "lipid", "cholesterol", "statin", "statin", "dyslipidemia", "dyslipidaemia",
    "hypercholesterolemia", "triglyceride", "lipoprotein", "ldl", "hdl",
    "hyperlipidemia", "hyperlipidaemia", "ezetimibe", "pcsk9", "atorvastatin",
    "rosuvastatin", "simvastatin", "pravastatin", "pitavastatin", "bempedoic",
]

# ---------------------------------------------------------------- 默认输出
EVIDENCE_JSONL = DATA_PROCESSED / "evidence.jsonl"
EVIDENCE_DB = DATA_PROCESSED / "evidence.db"
MANIFEST_JSON = DATA_PROCESSED / "manifest.json"
STATS_JSON = ARTIFACTS / "dataset_stats.json"
STATS_MD = ARTIFACTS / "dataset_stats.md"
