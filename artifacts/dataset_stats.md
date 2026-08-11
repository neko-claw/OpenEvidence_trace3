# 数据集统计报告

生成时间：2026-08-11T05:45:26+00:00

## 总量
- 证据记录总数：**21790**
- **文献/证据篇数（去重口径）：10183**
  - PubMed 摘要：7933
  - Europe PMC 独有摘要：691
  - ClinicalTrials.gov 试验：1541
  - 人工确认指南：18
- 唯一 PMID 数：8583
- 全文增强层（Europe PMC OA）：696 篇 / 11607 个 chunk
  （存于 data/processed/fulltext_chunks.jsonl，生成/验证时按需加载）

## 数据处理（改进后口径）
- 跨源同 PMID 合并删除记录数：14
- 无摘要回退为标题（title_only）：391
- 过短 chunk 丢弃：105
- XML 解析失败（隔离）：[]

## 按记录类型
{
  "abstract": 8624,
  "trial": 1541,
  "guideline": 18,
  "fulltext_chunk": 11607
}

## 按来源
{
  "pubmed": 7933,
  "clinicaltrial": 1541,
  "europepmc": 12298,
  "guideline": 18
}

## 按证据等级
{
  "other": 16856,
  "meta-analysis": 929,
  "review": 1192,
  "systematic-review": 429,
  "guideline": 221,
  "rct": 598,
  "clinical-trial": 1565
}

## 按主题
{
  "hypertension": 14669,
  "lipids": 9487
}

## 按年份（Top 15）
{
  "2026": 11028,
  "2025": 7378,
  "2024": 1025,
  "2020": 225,
  "2019": 216,
  "2018": 209,
  "2023": 208,
  "2021": 188,
  "2022": 186,
  "2017": 112,
  "2016": 110,
  "2014": 90,
  "2015": 88,
  "2012": 78,
  "2011": 76
}

## 期刊 Top 20
{
  "Nutrients": 149,
  "Cureus": 139,
  "Journal of hypertension": 112,
  "PloS one": 104,
  "Medicine": 100,
  "Hypertension (Dallas, Tex. : 1979)": 99,
  "Frontiers in endocrinology": 97,
  "Journal of clinical lipidology": 89,
  "Hypertension research : official journal of the Japanese Society of Hypertension": 87,
  "Journal of the American Heart Association": 82,
  "Scientific reports": 75,
  "Journal of clinical hypertension (Greenwich, Conn.)": 72,
  "Journal of clinical medicine": 61,
  "Nutrition, metabolism, and cardiovascular diseases : NMCD": 59,
  "BMJ open": 58,
  "Frontiers in cardiovascular medicine": 57,
  "Atherosclerosis": 56,
  "BMC cardiovascular disorders": 56,
  "Frontiers in nutrition": 54,
  "International journal of molecular sciences": 53
}

## 试验按状态
{
  "COMPLETED": 1017,
  "UNKNOWN": 183,
  "RECRUITING": 95,
  "TERMINATED": 93,
  "NOT_YET_RECRUITING": 52,
  "ACTIVE_NOT_RECRUITING": 45,
  "WITHDRAWN": 40,
  "ENROLLING_BY_INVITATION": 14,
  "SUSPENDED": 2
}

## 试验按分期
{
  "NA": 672,
  "PHASE3": 271,
  "PHASE4": 212,
  "PHASE2": 153,
  "PHASE1": 148,
  "PHASE2,PHASE3": 41,
  "PHASE1,PHASE2": 27,
  "EARLY_PHASE1": 17
}

## 指南回填（PubMed 真实元数据）
{
  "True": 14,
  "False": 4
}
