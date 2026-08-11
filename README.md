# OpenEvidence 赛道 3：专用 RAG vs 通用大模型对比评估

> 3 天暑期实践项目 · 赛道 3 实现
> 对比**纯通用大模型**与**带领域知识库的 RAG 系统**在同一批医学问题上的表现
> ⚠️ 仅供教学研究，不用于临床诊疗；不处理真实患者数据

本项目已内置 **11630 条多源证据库**（PubMed 7295 + Europe PMC 2776 + ClinicalTrials 1541 + 指南 18，由 `ingestion/` 数据管线采集并带 `manifest.json`），**不用采集数据即可直接运行**。

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
python -m pytest tests/ -q        # 期望输出: 31 passed
```

---

## 第二步：配置 API key（约 2 分钟）

### 2.1 需要一个什么 key

生成模型和评测（judge）共用 **DeepSeek API key**：

1. 注册 DeepSeek 开放平台：https://platform.deepseek.com
2. 充值少量余额（约 ¥10 足够跑完整实验）
3. 创建 API key（形如 `sk-xxxxxxxx`）

> 也可以换成任何 OpenAI 兼容接口（如硅基流动/通义/月之暗面），只需改 `config.yaml` 里的 `llm.base_url` 和 `llm.model`。

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
| 🗂 题集与证据库 | 浏览题集与 11630 条证据，实时检索 |

> WSL2 用户：Windows 浏览器直接访问 `http://localhost:8501`（端口自动转发）。

### 3.2 命令行（实验/评测流程）

```bash
bash scripts/start.sh smoke      # 冒烟：1 道开发题 × 4 条件（验证全链路）
bash scripts/start.sh formal     # 正式实验：12 道题 × 4 条件（约 10 分钟）

# 含 A2 通用搜索对照（可选条件，默认离线 mock；配 SERPER_API_KEY 可真实搜索）
python -m evaluation.experiment --questions dev8 --limit 2 --include-a2
python -m evaluation.experiment --conditions A A2 B C D

# STRESS 压力题 C/E 对照（E 为 P0 必做，实施规划 §2.1；正式 20 题由 B2 冻结后替换 stress_sample）
python -m evaluation.experiment --questions stress --conditions C E

# 离线回放（无 API key 的链路验收，实施规划 §10 风险降级；输出标注 offline-mock，不作正式结论）
python -m evaluation.experiment --offline --limit 2
```

**完整评测闭环**（实验后执行）：

```bash
# ① B3 副责：交叉复核 B4 输入一致性 + A2 搜索预算审计
python -m evaluation.consistency --runs data/experiments/runs/runs_<时间戳>.jsonl --questions data/questions/formal12.jsonl
# ② judge 盲评（匿名 + 双 judge）
python -m evaluation.judge --runs data/experiments/runs/runs_<时间戳>.jsonl --judges judge1 judge2
# ③ 统计（配对差值 + bootstrap 置信区间 + 按题型分组）
python -m evaluation.stats --scores data/experiments/scores/scores_<时间戳>.jsonl
# ④ 图表（配对差值图 + 箱线图 → artifacts/）
python -m evaluation.charts --scores data/experiments/scores/scores_<时间戳>.jsonl
```

### 3.3 五个实验条件说明

| 条件 | 含义 | 目的 | 主责 |
|---|---|---|---|
| A | 纯 LLM（无检索） | 基线 | B3 |
| A2 | 通用搜索对照（不用项目证据库，固定搜索预算 + 响应快照） | 外部检索能力次要对照（可选） | B3 |
| B | BM25 + 向量 + RRF 直接取 top-k（无 rerank） | 看"有没有 RAG" | B3 |
| C | B + 特征重排 + MMR | 看"rerank 增益" | B4 |
| D | 完整系统（工具轨迹） | 看"完整编排成本" | B4 |

A/A2/B/C/D 使用**同一模型、同一温度、同一输出上限**，公平对比。
A2 引用用 [S#] 单独标识（与项目证据 [E#] 区分），mock 模式结果标注"离线模拟"，
不用于声称真实通用搜索能力。

---

# 数据说明

- **已内置**：`data/processed/evidence.jsonl`（11630 条多源证据：PubMed 7295 + Europe PMC 2776 + ClinicalTrials 1541 + 指南 18，每条带 PMID/NCT/DOI/URL 可追溯；对应 `manifest.json` 记录 dataset_version 与来源许可证；字段 `abstract_or_chunk` 已兼容，加载时自动映射为 `text`）
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
data/processed/evidence.jsonl   11630 条多源证据库（已内置，含 manifest.json）
data/questions/         题集（formal12 正式 / dev8 开发 / stress_sample 压力样例）
scripts/                start.sh 一键启动 / build_kb 重建库 / view_evidence 浏览
tests/                  31 个契约测试
```

# 免责声明

本项目为教学研究用 MVP：不提供个体化诊疗建议，不处理真实患者数据，输出不构成医学诊断或治疗依据。医学结论请以最新指南与原始文献为准。
