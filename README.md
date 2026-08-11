# OpenEvidence 风格证据智能助手 MVP —— 第一部分：数据集采集

> 主题范围：**高血压（hypertension）+ 血脂异常（dyslipidemia）**，与实施规划一致。
> 状态：✅ 已完成（v0.1.0）。仅供教学研究，不用于临床诊疗。

## 1. 本部分交付物

| 交付物 | 路径 | 说明 |
|---|---|---|
| 统一证据集（主集） | `data/processed/evidence.jsonl` | 10,197 条题录/摘要 + 试验 + 指南（用于检索召回） |
| 全文增强层 | `data/processed/fulltext_chunks.jsonl` | **12,182 条 Europe PMC OA 全文分块（698 篇）**，生成/验证时按需加载 |
| 证据数据库 | `data/processed/evidence.db` | SQLite 索引（主集+全文 chunk 同表，`record_kind` 区分） |
| 数据集清单 | `data/processed/manifest.json` | DatasetManifest（版本、来源、去重策略、哈希） |
| 统计报告 | `artifacts/dataset_stats.md` / `.json` | 全量统计 |
| 采集代码 | `ingestion/` | 多源连接器 + 标准化 + 建库（可一键重建） |
| 按需全文服务 | `ingestion/fulltext_service.py` | 按 PMID/PMCID 拉取 OA 全文并分块（供 RAG/MCP 用） |
| 原始缓存 | `data/raw/` | 各源原始 API 响应（不提交 git，可重建） |

## 2. 数据规模（2026-08-11 采集）

- **文献/证据篇数：10,197**（≥ 2000 目标，超额 5 倍）
  - PubMed 摘要：**7,947**（唯一 PMID 8,597）
  - Europe PMC 独有摘要：691
  - ClinicalTrials.gov 干预性试验：**1,541**（NCT 去重）
  - 人工确认指南：**18**（14 条已用 PubMed 真实记录回填 PMID/DOI）
- **全文增强层**：Europe PMC OA **全文 698 篇 / 12,182 个分块**，其中 667 篇与 PubMed 摘要双覆盖
  （meta-analysis 124 / rct 53 / systematic-review 19 篇带全文，是生成与验证的关键支撑）
- 证据等级分布：guideline 228 / systematic-review 429 / meta-analysis 929 / rct 598 / review 1,194 / clinical-trial 1,564 / other 5,255
- 主题覆盖：hypertension 8,480 条、lipids 6,534 条（可重叠）
- 时间跨度：1995 – 2026，重点覆盖 2020 后最新研究，同时包含经典里程碑证据
  （SPRINT、DASH、ALLHAT、JUPITER、HYVET、CTT meta 分析、BPLTTC、FOURIER、IMPROVE-IT、孟德尔随机化研究等）

## 3. 数据源与采集方法

按实施规划 3.3 的来源路由矩阵，P0 四类证据：

| 来源 | API | 采集方式 | 采集量 |
|---|---|---|---|
| PubMed | E-utilities（esearch/efetch） | 35 组检索式（指南/系统综述/Meta/RCT/细分主题/经典证据），按 PMID 去重后批量 efetch 摘要 | 7,947 条摘要 |
| ClinicalTrials.gov | Data API v2 | `query.cond`（hypertension / dyslipidemia OR hyperlipidemia OR hypercholesterolemia OR hypertriglyceridemia），`filter.advanced=AREA[StudyType]INTERVENTIONAL` | 1,541 项试验 |
| Europe PMC | REST API | OA 系统综述/指南/试验检索（去重）+ 全文 XML 下载与分块 | 691 摘要 + 2,083 chunk |
| 指南（人工确认） | — | 人工确认权威指南清单 + 用 PubMed 检索回填元数据（见 §6） | 18 条 |

### 检索式覆盖的题型（对应实施规划 3.3 路由矩阵）

- 稳定机制/风险因素：生活方式（DASH、钠盐、运动）、血压测量、老年/妊娠/糖尿病亚组
- 指南与治疗建议：中美欧指南检索（ACC/AHA、ESC/ESH、KDIGO、WHO、NICE、中国指南）
- 最新研究/临床试验：2020-2026 RCT（`sort=pub_date`）、PCSK9、ezetimibe/bempedoic、omega-3、Lp(a)
- 疗效与安全性比较：降压药、他汀、降脂药相关系统综述/Meta 分析
- 经典证据补足：SPRINT、DASH、ALLHAT、JUPITER、CTT/BPLTTC 协作组 Meta 分析等

## 4. Evidence 数据契约与分层存储（规划 3.1 / 4.1）

**为什么分层？** 检索召回用摘要（快、全），全文只在生成/验证时按需加载，避免把全部正文塞进索引（规划 12.3）。

- `evidence.jsonl`（主集）：`record_kind = abstract | trial | guideline`
- `fulltext_chunks.jsonl`（增强层）：`record_kind = fulltext_chunk`，`pmcid` 关联同文摘要
- `evidence.db`：两文件同表（`evidence`），`record_kind` 区分，全文层可随时按 `pmcid` 定位
- 按需全文：`python -m ingestion.fulltext_service --pmid 39210715`（Europe PMC OA 子集；
  非 OA 文献返回明确提示，引用校验走 PMID/DOI 层）

每条记录字段：

```jsonc
{
  "id": "pmid:39210715 | nct:NCT01247090 | epmc:PMC13209865:chunk:000 | guideline:esc-2024",
  "record_kind": "abstract | trial | guideline | fulltext_chunk",
  "source_type": "pubmed | clinicaltrial | europepmc | guideline",
  "title": "...",
  "abstract_or_chunk": "摘要 / 试验简介 / 指南说明 / 全文分块文本",
  "authors": ["..."],
  "published_at": "2024-09-30", "year": 2024,
  "url": "可访问链接",
  "pmid": "...", "doi": "...", "nct_id": "...", "pmcid": "...",
  "guideline_name": "人工确认指南名",
  "page": null,
  "evidence_level": "guideline | systematic-review | meta-analysis | rct | clinical-trial | review | other",
  "population": "...", "intervention": "...", "comparator": "...", "outcome": "...",
  "journal": "...",
  "publication_types": ["..."], "mesh_terms": ["..."], "keywords": ["..."],
  "topics": ["hypertension", "lipids"],
  "content_hash": "sha256(title+abstract)",
  "fetched_at": "ISO 时间戳",
  "extras": { "试验状态/分期/入组数等来源特有字段" }
}
```

> 说明：PICO 字段已为试验填充（人群=入组条件，干预=干预名，结局=主要结局指标）；
> 文献摘要的 PICO 解析属于后续 A3 流水线任务，本部分保留空值。

## 5. 去重与溯源

- **跨源去重**：PubMed 与 Europe PMC 以 **PMID** 为稳定键；试验以 **NCT ID**；指南以人工 key。
- **content_hash**：sha256(title + abstract)，供后续增量更新与重复检测。
- **指南编号不人工编造**：指南的 PMID/DOI 全部来自 PubMed 真实检索结果，经
  `verify_terms`（标题必须包含）+ `exclude_terms`（排除评论/勘误/译文）+ 年份/期刊约束
  三重验证后才回填（见 `ingestion/guidelines.py`）；检索不到可靠记录的（NICE 网页版、
  妊娠期指南等）保留为人工确认的元数据记录（`enriched=False`），不强行回填。

## 6. 人工确认指南清单（18 条）

| 指南 | 年份 | 回填 PMID |
|---|---|---|
| 中国高血压防治指南 2018 修订版 | 2018 | 31080465 |
| 中国高血压防治指南 2024 修订版 | 2024 | 39653517 |
| 中国血脂管理指南 2023 | 2023 | 37711173 |
| 中国血脂管理指南（基层版 2024） | 2024 | 38548600 |
| 中国老年高血压管理指南 2019 / 2023 | 2019 / 2023 | 30923539 / 38973827 |
| 2017 ACC/AHA 高血压指南 | 2018 | 29133356 |
| 2023 ESH 高血压指南 | 2023 | 37345492 |
| 2024 ESC 高血压指南 | 2024 | 39210715 |
| 2018 AHA/ACC 血脂指南 | 2019 | 30586774 |
| 2019 ESC/EAS 血脂指南 | 2019 | 31591002 |
| 2021 ESC 心血管病预防指南 | 2021 | 34458905 |
| KDIGO 2021 CKD 血压指南 | 2021 | 33637192 |
| WHO 成人高血压药物治疗指南 | 2021 | 36791691（中文翻译条目） |
| 妊娠期高血压疾病诊治指南 2020 / 高血压合理用药指南第2版 / NICE NG136 / NICE CG181 | — | 未回填（元数据记录） |

## 7. 如何重建

```bash
# 需要 Python 3.8+，依赖 requests（可选 uv）
cd OpenEvidence
python -m ingestion.run_all          # 全流程（带缓存，断点续传）
python -m ingestion.run_all --force  # 忽略缓存全量重抓
```

原始 API 缓存写入 `data/raw/`（已 gitignore）；`data/processed/` 与 `artifacts/` 可重建。

## 8. 已知局限

- **全文覆盖**：仅 Europe PMC OA 子集（698 篇，多为系统综述/试验）；ESC/ACC/AHA 等指南全文在出版商
  网站，检索用摘要+ID 溯源，全文补全属 P1（指南 PDF 解析 / Crossref/OpenAlex 元数据补全）。
- content_hash 存在少量跨 PMID 重复（同一指南的多期刊变体、个别重复索引的预印本、极少数字段重复的全文 chunk）：
  这正是 `content_hash` 字段的用途，下游可按需合并；正式评测的检索层可按 ID 去重。
- 中文文献：PubMed 收录的中文指南以英文题录为主；中文全文 PDF 解析属 P1（按规划降级）。
- 指南全文：本部分保存书目元数据 + 已验证 PMID/DOI/URL；指南 PDF 解析与分块在 P1 进行。
- 时效：`corpus_cutoff=2026-08-11`；正式评测前如需要可增量更新（content_hash 支持）。
- 伦理边界：不包含真实患者数据；所有页面/报告需标注“仅供教学研究，不用于临床诊疗”。

## 9. 目录结构（本部分相关）

```text
OpenEvidence/
├── ingestion/               # 数据集采集（第一部分）
│   ├── config.py          # 检索式、限速、路径
│   ├── http_utils.py      # 限速/重试请求
│   ├── sources/           # PubMed / ClinicalTrials / Europe PMC 连接器
│   ├── guidelines.py      # 人工确认指南 + 验证式回填
│   ├── normalize.py       # Evidence 标准化
│   ├── build_db.py        # SQLite + Manifest + 统计
│   ├── fulltext_service.py# 按需全文拉取（供 RAG/MCP）
│   └── run_all.py         # 一键执行
├── evaluation/               # 赛道3 对比评估（B1 交付）
│   ├── blueprints/question_blueprint.json   # 130 题蓝图
│   ├── schemas/run.schema.json              # Run 记录契约
│   ├── schemas/score.schema.json            # Score 评分契约
│   ├── experiment_config.json               # 配置清单（K/权重/阈值/预算）
│   ├── preregistration/e_perturbation_rules.json  # E 劣化预注册规则
│   └── make_fixtures.py                     # 离线 fixture 生成
├── docs/
│   ├── experiment_protocol.md               # 赛道3 实验协议（B1 核心交付）
│   └── ...（需求/规划文档）
├── data/
│   ├── raw/               # 原始 API 缓存（gitignore）
│   └── processed/         # evidence.jsonl / fulltext_chunks.jsonl / evidence.db / manifest.json
│       └── fixtures/      # 离线 Evidence fixture + 样例题
├── artifacts/             # dataset_stats.md / .json
├── pyproject.toml
└── README.md
```
