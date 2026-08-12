# OpenEvidence 赛道 3：专用 RAG vs 通用大模型对比评估

> 3 天暑期实践项目 · 赛道 3 实现
> 对比**纯通用大模型**与**带领域知识库的 RAG 系统**在同一批医学问题上的表现
> ⚠️ 仅供教学研究，不用于临床诊疗；不处理真实患者数据

本项目已内置 **10183 条多源证据库**（PubMed 7,933 + Europe PMC 独有 691 + ClinicalTrials 1,541 + 指南 18，由 `ingestion/` 数据管线采集并带 `manifest.json`），**不用采集数据即可直接运行**。

---

# 三步快速上手

## 第一步：部署环境（约 10 分钟）

### 1.1 前置要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows（WSL2）/ Linux / macOS |
| Python | 3.10 ~ 3.12 |
| 磁盘 | 至少 3GB（含模型缓存） |
| 网络 | 首次运行需联网（下载模型 + 调用 API） |

### 1.2 创建 Python 环境（二选一）

**方式 A：conda（推荐）**

```bash
conda create -n oe python=3.10 -y
conda activate oe
```

**方式 B：venv（无 conda 时）**

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 1.3 安装依赖

```bash
cd OpenEvidence
pip install -r requirements.txt
```

> `requirements.txt` 包含：httpx、PyYAML、rank-bm25、numpy、pandas、scipy、matplotlib、pytest、sentence-transformers、streamlit。
> 若 `sentence-transformers` 安装慢，可换国内镜像：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt`

### 1.4 验证环境

```bash
python -m pytest tests/ -q        # 期望输出: 104 passed
```

---

## 第二步：配置 API key（约 2 分钟）

### 2.1 需要一个什么 key

| 用途 | Provider | 模型 | 环境变量 | 必需 |
|---|---|---|---|---|
| 生成模型（A/B/C/D/E） | DeepSeek | `deepseek-chat` | `DEEPSEEK_API_KEY` | ✅ |
| judge 盲评（独立家族） | 阿里云百炼 DashScope | `qwen3.8-max` | `DASHSCOPE_API_KEY` | ✅ |
| 嵌入模型 | 阿里云百炼 DashScope | `qwen3.7-text-embedding` | `DASHSCOPE_API_KEY`（兼容 `EMBEDDING_API_KEY`） | ✅ |

- 生成与 judge 使用**不同模型家族**（deepseek 生成 / qwen 评审），降低 LLM judge 同源偏差（规划 §6.3）。
- judge provider 在 `config.yaml` 的 `judge:` 段独立配置；嵌入在 `embedding:` 段（`backend: api`）。
- 嵌入也可用本地 BGE（`backend: local`，需 `pip install sentence-transformers`）。

### 2.2 写入项目 `.env`

```bash
cp .env.example .env      # 复制模板
nano .env                 # 或 vim / code 编辑
```

编辑后第 2 行填入你的 key：

```text
DEEPSEEK_API_KEY=sk-你的key      ← 等号后直接填，不要空格、不要引号
```

> ⚠️ `.env` 已被 `.gitignore` 排除，不会进入版本库。不要把 key 发给别人或贴到代码里。

### 2.3 验证 key 是否生效

```bash
python -c "
from core.env import load_dotenv; load_dotenv()
from core.config import load_config
from core.llm import LLMClient
LLMClient(load_config()['llm'])          # 不报错即 key 有效
print('✅ API key 配置成功')
"
```

---

## 第三步：启动系统（约 1 分钟）

### 3.1 网页端（推荐日常使用）

```bash
python -m streamlit run app.py
```

浏览器打开 **http://localhost:8501**，四个页面：

| 页面 | 功能 |
|---|---|
| 🎯 单题问答 | 输入医学问题，选条件 A/B/C/D 运行，看回答/引用/来源/轨迹 |
| ⚡ 批量实验 | 选择题集 + 条件一键跑，实时进度 + 结果表 |
| 📊 评测结果 | 均值对比、配对差值图、按题型分组、原始评分 |
| 🗂 题集与证据库 | 浏览题集与 10183 条证据，实时检索 |

> WSL2 用户：Windows 浏览器直接访问 `http://localhost:8501`（端口自动转发）。

### 3.2 命令行（实验/评测流程）

```bash
bash scripts/start.sh smoke      # 冒烟：1 道开发题 × 4 条件（验证全链路）
bash scripts/start.sh formal     # 正式实验：12 道题 × 4 条件（约 10 分钟）

# 正式主集（B2 冻结版：test_set/questions.jsonl，33 DEV + 77 TEST，题型 19/19/19/20）
python -m evaluation.experiment --questions testset --conditions A B C D
python -m evaluation.experiment --questions testset --limit 20 --conditions B C   # 分层抽样子集

# 含 A2 通用搜索对照（可选条件，默认离线 mock；配 SERPER_API_KEY 可真实搜索）
python -m evaluation.experiment --questions dev8 --limit 2 --include-a2
python -m evaluation.experiment --conditions A A2 B C D

# STRESS 压力题 C/E 对照（E 为 P0 必做；正式 20 题 = test_set/stress_20.jsonl，4 类预注册扰动各 5）
python -m evaluation.experiment --questions stress --conditions C E

# 离线回放（无 API key 的链路验收，实施规划 §10 风险降级；输出标注 offline-mock，不作正式结论）
python -m evaluation.experiment --offline --limit 2

# 题集重建与合规校验（B2 交付，只按真实运行口径判 PASS）
python scripts/rebuild_test_set.py
python scripts/validate_dataset.py
```

**完整评测闭环**（实验后执行）：

```bash
# ① B3 副责：交叉复核 B4 输入一致性 + A2 搜索预算审计（正式主集 + 正式压力集）
python -m evaluation.consistency --runs data/experiments/runs/runs_<时间戳>.jsonl \
    --questions test_set/questions.jsonl --questions-stress test_set/stress_20.jsonl
# ② judge 盲评（匿名 + 双 judge；正式主集）
python -m evaluation.judge --runs data/experiments/runs/runs_<时间戳>.jsonl --questions test_set/questions.jsonl --judges judge1 judge2
# ③ 统计（配对差值 + bootstrap 置信区间 + 按题型分组）
python -m evaluation.stats --scores data/experiments/scores/scores_<时间戳>.jsonl
# ④ 图表（配对差值图 + 箱线图 → artifacts/）
python -m evaluation.charts --scores data/experiments/scores/scores_<时间戳>.jsonl
# ⑤ B5 综合报告（确定性指标 + 配对统计 + judge 审计 + 反例）
python -m evaluation.b5_report --runs data/experiments/runs/runs_<时间戳>.jsonl \
    --questions test_set/questions.jsonl --questions-stress test_set/stress_20.jsonl
```

**B4 离线检索/劣化评测链路**（fixture 断网可跑；`--retriever` 可选 `fixture` / `reference-rerank` / `hybrid-rerank`）：

```bash
# C/D/E 统一运行入口（fixture，STRESS 上 C/E 配对；--seed 确定性复现劣化）
python -m evaluation.run_conditions --retriever fixture --condition C,D,E --split ALL --final-k 4 --seed 7
# 真实检索栈：BM25 + 向量 + RRF + 特征重排 + MMR（embedding backend: fallback|local|api）
python -m evaluation.run_conditions --retriever hybrid-rerank --embedding-backend fallback --condition C,E --split STRESS
# 检索诊断：Recall@50 / Hit@5 / MRR / nDCG@8 / 分阶段消融 / 失败分类
python -m evaluation.evaluate_retrieval --retrieval artifacts/b4/retrieval-*.jsonl --runs artifacts/b4/runs-*.jsonl --qrels data/fixtures/qrels.jsonl --output-dir artifacts/b4
# STRESS 题集契约校验（正式模式要求 20 题、四类规则各 5 题；fixture-smoke 为当前样例）
python scripts/validate_stress_fixture.py --fixture-smoke
# D 接入赛道一 A5 完整系统（输出统一 RunRecord JSONL）
python -m evaluation.run_a5 --a5-root <赛道一仓库路径> --demo
```

输出：`artifacts/b4/runs-*.jsonl`（Run 契约）、`retrieval-*.jsonl`（分阶段候选与特征分）、`stress-*.jsonl`（E 扰动 manifest：规则/seed/删除注入项/扰动前后候选集）。

### 3.3 五个实验条件说明

| 条件 | 含义 | 目的 | 主责 |
|---|---|---|---|
| A | 纯 LLM（无检索） | 基线 | B3 |
| A2 | 通用搜索对照（不用项目证据库，固定搜索预算 + 响应快照） | 外部检索能力次要对照（可选） | B3 |
| B | BM25 + 向量 + RRF 直接取 top-k（无 rerank） | 看"有没有 RAG" | B3 |
| C | B + 特征重排 + MMR | 看"rerank 增益" | B4 |
| D | 完整系统（工具轨迹） | 看"完整编排成本" | B4 |
| E | 劣化 RAG（预注册规则派生候选集） | STRESS 题 C/E 配对：看"检索失败是否拖累回答/能否拒答" | B4 |

A/A2/B/C/D 使用**同一模型、同一温度、同一输出上限**，公平对比。
A2 引用用 [S#] 单独标识（与项目证据 [E#] 区分），mock 模式结果标注"离线模拟"，
不用于声称真实通用搜索能力。

---

# 数据说明

- **已内置**：`data/processed/evidence.jsonl`（10183 条多源证据：PubMed 7,933 + Europe PMC 独有 691 + ClinicalTrials 1,541 + 指南 18，每条带 PMID/NCT/DOI/URL 可追溯；对应 `manifest.json` 记录 dataset_version 与来源许可证；字段 `abstract_or_chunk` 已兼容，加载时自动映射为 `text`）
- **重新采集**（可选，需网络）：

  ```bash
  python scripts/build_kb.py --retmax 25   # 25 个主题查询 → 过滤 → 去重 → 标注 → 入库
  ```

- **浏览数据**：`python scripts/view_evidence.py list --level guideline`
- **中文查询扩展**已内置（`retrieval/query_expansion.py`，60+ 医学术语中英映射）

# 常见问题

| 现象 | 解决 |
|---|---|
| 提示缺少 DEEPSEEK_API_KEY | 见"第二步"，检查 `.env` 第 2 行格式 |
| `embedding.backend=local` 报错 | `pip install sentence-transformers`（首次运行会下载约 100MB 模型） |
| 网页端打不开 | `curl localhost:8501` 检查；确认端口未被占用 |
| 实验全 REFUSE | `config.yaml` 里调大 `retrieval.retrieval_quality_threshold` 的阈值（往小调） |
| 图表中文变方块 | 安装中文字体（Linux: `sudo apt install fonts-noto-cjk`） |
| 想换生成模型 | 改 `config.yaml` 的 `llm.model` / `llm.base_url` |
| 结果无法复现 | 每次 Run 记录 `index_version` + `prompt_version`，见 `data/experiments/runs/` |

# 目录结构

```text
app.py                  网页前端（Streamlit）
config.yaml             全局配置（模型/权重/阈值，版本化）
core/                   数据契约、LLM 客户端、Embedding、.env 加载
ingestion/              PubMed / ClinicalTrials 采集 + 相关性过滤
retrieval/              BM25 + 向量 + RRF + 特征重排 + MMR + 查询扩展
generation/             Prompt / 生成 / 引用白名单 / 拒答
evaluation/             实验 / judge / 指标 / 统计 / 图表
data/processed/evidence.jsonl   10183 条多源证据库（已内置，含 manifest.json）
data/questions/         演示样例题集（dev8/formal12/stress_sample，不进正式指标）
test_set/               正式题集（questions.jsonl 主集 + stress_20.jsonl 压力集 + 评分指南 + qrels）
scripts/rebuild_test_set.py   题集重建（可复现）
scripts/validate_dataset.py   合规校验（真实运行口径 PASS）
scripts/                start.sh 一键启动 / build_kb 重建库 / view_evidence 浏览
tests/                  104 个契约测试（含 B5 报告回归）
```

# 免责声明

本项目为教学研究用 MVP：不提供个体化诊疗建议，不处理真实患者数据，输出不构成医学诊断或治疗依据。医学结论请以最新指南与原始文献为准。

---

# 附录：赛道1 数据集采集（B1 交付物）

## OpenEvidence 风格证据智能助手 MVP —— 第一部分：数据集采集

> 主题范围：**高血压（hypertension）+ 血脂异常（dyslipidemia）**，与实施规划一致。
> 状态：✅ 已完成（v0.2.0：跨源去重 + 空摘要标记 + XML 清洗 + 小节感知分块）。仅供教学研究，不用于临床诊疗。

### 1. 本部分交付物

| 交付物 | 路径 | 说明 |
|---|---|---|
| 统一证据集（主集） | `data/processed/evidence.jsonl` | 10,183 条题录/摘要 + 试验 + 指南（用于检索召回） |
| 全文增强层 | `data/processed/fulltext_chunks.jsonl` | **12,023 条 Europe PMC OA 全文分块（696 篇，小节感知 + 句子边界 + 重叠）**，生成/验证时按需加载 |
| 证据数据库 | `data/processed/evidence.db` | SQLite 索引（主集+全文 chunk 同表，`record_kind` 区分） |
| 数据集清单 | `data/processed/manifest.json` | DatasetManifest（版本、来源、去重策略、哈希、分块策略、处理统计） |
| 统计报告 | `artifacts/dataset_stats.md` / `.json` | 全量统计 |
| 采集代码 | `ingestion/` | 多源连接器 + 标准化 + 建库（可一键重建） |
| 按需全文服务 | `ingestion/fulltext_service.py` | 按 PMID/PMCID 拉取 OA 全文并分块（供 RAG/MCP 用） |
| 原始缓存 | `data/raw/` | 各源原始 API 响应（不提交 git，可重建） |

### 2. 数据规模（2026-08-11 采集）

- **文献/证据篇数：10,183**（≥ 2000 目标，超额 5 倍）
  - PubMed 摘要：**7,933**（唯一 PMID 8,583）
  - Europe PMC 独有摘要：691
  - ClinicalTrials.gov 干预性试验：**1,541**（NCT 去重）
  - 人工确认指南：**18**（14 条已用 PubMed 真实记录回填 PMID/DOI）
- **全文增强层**：Europe PMC OA **全文 696 篇 / 12,023 个分块**，其中 667 篇与 PubMed 摘要双覆盖
  （meta-analysis / rct / systematic-review 带全文，是生成与验证的关键支撑）
- 证据等级分布：guideline 221 / systematic-review 429 / meta-analysis 929 / rct 598 / review 1,192 / clinical-trial 1,565 / other 16,856
- 主题覆盖：hypertension 14,669 条、lipids 9,487 条（可重叠）
- 时间跨度：1995 – 2026，重点覆盖 2020 后最新研究，同时包含经典里程碑证据
  （SPRINT、DASH、ALLHAT、JUPITER、HYVET、CTT meta 分析、BPLTTC、FOURIER、IMPROVE-IT、孟德尔随机化研究等）

### 3. 数据源与采集方法

按实施规划 3.3 的来源路由矩阵，P0 四类证据：

| 来源 | API | 采集方式 | 采集量 |
|---|---|---|---|
| PubMed | E-utilities（esearch/efetch） | 35 组检索式（指南/系统综述/Meta/RCT/细分主题/经典证据），按 PMID 去重后批量 efetch 摘要 | 7,933 条摘要 |
| ClinicalTrials.gov | Data API v2 | `query.cond`（hypertension / dyslipidemia OR hyperlipidemia OR hypercholesterolemia OR hypertriglyceridemia），`filter.advanced=AREA[StudyType]INTERVENTIONAL` | 1,541 项试验 |
| Europe PMC | REST API | OA 系统综述/指南/试验检索（与 PubMed 按 PMID 去重）+ 全文 XML 下载与分块 | 691 摘要 + 12,023 chunk |
| 指南（人工确认） | — | 人工确认权威指南清单 + 用 PubMed 检索回填元数据（见 §6） | 18 条 |

#### 检索式覆盖的题型（对应实施规划 3.3 路由矩阵）

- 稳定机制/风险因素：生活方式（DASH、钠盐、运动）、血压测量、老年/妊娠/糖尿病亚组
- 指南与治疗建议：中美欧指南检索（ACC/AHA、ESC/ESH、KDIGO、WHO、NICE、中国指南）
- 最新研究/临床试验：2020-2026 RCT（`sort=pub_date`）、PCSK9、ezetimibe/bempedoic、omega-3、Lp(a)
- 疗效与安全性比较：降压药、他汀、降脂药相关系统综述/Meta 分析
- 经典证据补足：SPRINT、DASH、ALLHAT、JUPITER、CTT/BPLTTC 协作组 Meta 分析等

### 4. Evidence 数据契约与分层存储（规划 3.1 / 4.1）

**为什么分层？** 检索召回用摘要（快、全），全文只在生成/验证时按需加载，避免把全部正文塞进索引（规划 12.3）。

- `evidence.jsonl`（主集）：`record_kind = abstract | trial | guideline`（同 PMID 跨源已合并，无重复）
- `fulltext_chunks.jsonl`（增强层）：`record_kind = fulltext_chunk`，`pmcid` 关联同文摘要；
  每个 chunk 的 `extras.section / char_start / char_end` 记录所属小节与字符区间，供证据 span 定位
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

#### 分块策略（v0.2.0 改进）

- **小节感知**：每个 chunk 严格属于单一章节（正文 `<sec>` 层级），绝不把不同章节切到同一块；
  章节标题编号规范化（`1. Introduction` → `Introduction`），参考文献/致谢/数据可用性等噪声小节跳过。
- **句子边界 + 重叠**：按句末标点切分，块长 ≤ 4000 字符；同小节相邻块重叠约 150 字符，避免硬切丢上下文。
- **XML 清洗**：数学公式替换为 `[MATH]` 占位符；交叉引用 `<xref>` 与残留 `[1]`/`[9,10,11]` 引用编号剥离，
  防止 LLM 误当成项目引用 `[E#]`；表格按 单元格用 `|`、行用 `||` 分隔。
- **span 元数据**：`extras.section / char_start / char_end`，支撑 §5.7 Gate 5 的 evidence span 定位。

### 5. 去重与溯源

- **跨源去重**：PubMed 与 Europe PMC 以 **PMID** 为稳定键；试验以 **NCT ID**；指南以人工 key。
- **同 PMID 跨源合并**（v0.2.0）：同一文献同时以 guideline + pubmed / pubmed + europepmc 出现时，
  合并为一条规范记录（优先级 指南 > PubMed > Europe PMC），保留规范 id，被合并 id 记录于
  `extras.dedup_merged_ids`；全文 chunk 层不参与合并（是证据片段而非重复文献）。
- **content_hash**：sha256(title + abstract)，供后续增量更新与重复检测。
- **空摘要标记**：PubMed/Europe PMC 无摘要记录以标题回退并标记 `extras.content_status=title_only`，
  避免空文本进检索索引；过短全文 chunk（< 50 字符）直接丢弃（计数见 manifest）。
- **指南编号不人工编造**：指南的 PMID/DOI 全部来自 PubMed 真实检索结果，经
  `verify_terms`（标题必须包含）+ `exclude_terms`（排除评论/勘误/译文）+ 年份/期刊约束
  三重验证后才回填（见 `ingestion/guidelines.py`）；检索不到可靠记录的（NICE 网页版、
  妊娠期指南等）保留为人工确认的元数据记录（`enriched=False`），不强行回填。

### 6. 人工确认指南清单（18 条）

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

### 7. 如何重建

```bash
## 需要 Python 3.8+，依赖 requests（可选 uv）
cd OpenEvidence
python -m ingestion.run_all          # 全流程（带缓存，断点续传）
python -m ingestion.run_all --force  # 忽略缓存全量重抓
```

原始 API 缓存写入 `data/raw/`（已 gitignore）；`data/processed/` 与 `artifacts/` 可重建。

### 8. 已知局限

- **全文覆盖**：仅 Europe PMC OA 子集（696 篇，多为系统综述/试验）；ESC/ACC/AHA 等指南全文在出版商
  网站，检索用摘要+ID 溯源，全文补全属 P1（指南 PDF 解析 / Crossref/OpenAlex 元数据补全）。
- **指南正文**：多数权威指南的 PubMed 条目本身无摘要（如 ACC/AHA 2017、ESC 2024），
  本部分保存书目元数据 + 已验证 PMID/DOI/URL；指南 PDF 解析与分块在 P1 进行，报告需披露。
- **中文文献**：PubMed 收录的中文指南以英文题录为主；中文全文 PDF 解析属 P1（按规划降级）。
- **时效**：`corpus_cutoff=2026-08-11`；正式评测前如需要可增量更新（content_hash 支持）。
- **伦理边界**：不包含真实患者数据；所有页面/报告需标注“仅供教学研究，不用于临床诊疗”。

### 9. 目录结构（本部分相关）

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
