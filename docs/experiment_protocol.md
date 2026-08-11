# 赛道3 对比评估实验协议（B1 交付物）

> 版本：v0.1.0（预注册草案，开工前冻结候选）
> 责任人：B1 实验负责人 ｜ 适用：赛道3（专用 AI vs 通用大模型对比评估）
> 配套文件：`evaluation/blueprints/question_blueprint.json`（题集蓝图）、
> `evaluation/experiment_config.json`（配置清单）、`evaluation/schemas/`（Run/Score schema）、
> `evaluation/preregistration/e_perturbation_rules.json`（E 劣化预注册规则）

## 0. 文档性质与冻结规则

- 本文档 + 蓝图 + 配置清单 + Run/Score schema 构成赛道3 的 **B1 冻结包**。
- 冻结流程：草案（v0.1.0）→ B1/B3/B4/B5 联合评审 → 第 1 天中午冻结 `system-v0.2`
  → 此后**只修阻断问题**，禁止为正式题调参。
- 正式题文本、gold、rubric 在系统冻结前只对 **B2（题集负责人）** 可见；B1 负责蓝图与协议，不参与正式题答案撰写。
- 本文档所有阈值均为**起始建议值**（v0.1），必须在 30 道开发题上校准后冻结；**不得用正式题回退调参**。

## 1. 科学问题与预注册假设

| 编号 | 假设 | 对比 | 判定方式 |
|---|---|---|---|
| H1 | 外部证据接入降低无依据陈述、提高关键回答点覆盖率 | B − A | TEST 集配对差值 |
| H2 | rerank/MMR 在相同候选集上带来可测排序与支持性增益 | C − B | TEST 集配对差值 |
| H3 | 完整组件包（Wiki/Skill/MCP/Agent）带来整体净收益 | D − C | 仅整体解释，**不做单组件归因** |
| H4 | 检索劣化拖累回答，且可被拒答/支持性门禁部分发现 | E − C | STRESS 集（预注册 E 规则） |
| H5（可选） | 通用搜索对照收益是否接近/超过本项目 RAG | A2 − A | 若执行，仅作次要结论 |

- 主终点在运行前冻结（§5.1），不允许运行后挑选有利指标。
- 若 H1/H2 无显著差异：如实报告题型差异、成本与失败案例，**不预设 RAG 必胜**。

## 2. 实验条件定义

| 条件 | 输入 | 检索/证据 | Rerank | Agent/工具 | 引用要求 | 用途 |
|---|---|---|---|---|---|---|
| A closed-book | 问题 + 共同任务/安全规则 | 无（不开放检索） | — | — | 不强制（不因无证据记为 0） | 基线：模型自身记忆 |
| A2 通用搜索（可选） | 同一问题 + 通用搜索工具 | 通用搜索响应（独立标识） | — | 固定搜索次数/时间预算 | 引用必须来自其搜索响应 | 次要对照 |
| B 固定 RAG | 同一问题 + 冻结 Evidence 快照 | BM25/向量 RRF top-k（无 Agent/Wiki） | 无创新 rerank | — | `[E#]` 必须来自检索白名单 | 中间基线：证据接入增量 |
| C Rerank RAG | 同一问题 + **与 B 相同候选集** | 与 B 相同 | 特征重排 + MMR | — | 同 B | 隔离 rerank/MMR 增量 |
| D 完整系统 | 同一问题 + 语料快照 | B 语料 + LLM Wiki 导航 | C 的 rerank | Wiki/Skill/MCP/Agent（固定预算） | 同 B | 组件包整体增量（探索性） |
| E 劣化 RAG | STRESS 题 + 按预注册规则劣化的候选集 | 在 **B 基线初检结果**上派生（删除 gold / 降 top-k / 注入不支持证据） | 以 C 配置为基准 | — | 同 B | 压力集：检索失败对回答的影响 |

公平性铁律（B3/B4 执行，B1 审计）：
1. A/B/C/D/E 使用**同一生成模型快照**、共同任务规则、相同 max output tokens。
2. B/C 使用**同一冻结语料、相同查询输入、相同初检候选集**；C 只改变 rerank/MMR。
3. E 的劣化候选集**不与 B/C 共享同一候选集**，按预注册规则派生。
4. 每道题配对运行，条件顺序随机；缓存与异常重试规则一致；成本/延迟/token 单独计入。
5. 内容评分**隐藏条件标签与引用**；引用评分用另一轮可见引用的界面。
6. gold 证据与人工 rubric **不放入生成 Prompt**。
7. A2 若未执行，报告中必须明确标记为缺失条件。

## 3. 题集蓝图（130 道，详见 question_blueprint.json）

| 数据包 | 题数 | 用途 | 是否进入主结论 |
|---|---|---|---|
| DEV 开发集 | 30 | K、rerank 权重、拒答阈值、查询改写选择 | 否 |
| TEST 正式集 | 60 | A/B/C/D 配对主评测（A2 可选） | **是** |
| STRESS 压力集 | 20 | C/E 对照（检索劣化、冲突、不可答、注入） | 单独报告 |
| EXTERNAL 外部基准 | 10 | 跨题目来源泛化 | 次要结论 |
| RESERVE 备用集 | 10 | 替换泄漏/重复/gold 失效 | 否 |

TEST 分层约束（B2 执行、B1 校验）：
- 四类题型各 15 道：稳定机制 / 指南治疗 / 最新研究 / 证据不足·冲突·范围外。
- 主题：高血压 30 + 血脂 30，两主题在四类题型中尽量均衡。
- 题目来源 ≤ 40% 单一来源：人工/教师 18、指南与文献问题 18、公开基准 12、LLM 候选题 12。
- 隔离：同源改写共享 `source_group_id` 且只能进同一 split；embedding 聚类查近义重复；
  DEV 与 TEST 不得共享同一 gold 段落的直接派生题。
- 最新研究题采用时间留出：`as_of_date` 晚于模型知识截止，语料按 `corpus_cutoff` 冻结。
- 每题必含：题型、难度、关键回答点、answerability、as_of_date、可接受/反对证据、扣分项。

## 4. 预注册（运行前冻结，写入配置与记录）

### 4.1 主要终点（两个）
1. `rubric_keypoint_score`：关键回答点的正确覆盖率（按每题预设关键点）。
2. `unsupported_critical_claim_rate`：未获证据支持的关键主张比例。

### 4.2 次要终点
faithfulness、citation precision、citation coverage、correctness、completeness、
answer relevance、abstention quality、Hit@5、MRR、Recall@50、nDCG@8、
延迟、input/output tokens、估算成本、judge 一致性（Cohen's κ / 加权 κ）。

### 4.3 统计方法（B5 执行、B1 审核）
- 配对差值：以“问题”为配对单位，按四类题型分层 bootstrap，报告 95% CI；**不以 chunk/引用为独立样本**。
- 显著检验：配对置换或 Wilcoxon；对 A−B、B−C、C−D 多个主对比做 **Holm 校正**。
- REPEAT 子集：TEST 内预分层抽 20 题（与 STRESS 独立），每条件额外运行 2 次，报告模型输出方差。
- 结论外推边界：只外推至本题库覆盖的高血压/血脂场景。
- 检索指标只比较 B/C/D/E；A 不记检索零分。引用指标报告宏/微平均，文献级去重后计算。

### 4.4 E 劣化预注册规则（20 道压力题，见 e_perturbation_rules.json）
- 删除 gold 证据（5 题）、降低 top-k 且排除 gold（5 题）、注入主题相关但不支持的证据（5 题）、
  无充分证据/范围外 + 提示注入 + 伪造 PMID/DOI 的恶意证据（5 题）。
- 规则必须在看到模型输出前确定，**不得事后挑选失败样本**。

## 5. 版本冻结方案

| 时点 | 冻结内容 | 责任人 |
|---|---|---|
| 第 1 天上午结束 | Question schema、DEV 题初版、Run/Score schema v0.1 | A1 / B1 |
| 第 1 天中午 | Evidence/MCP schema、样例数据 | A2 |
| 第 1 天结束 | Wiki/索引 v0.1、DEV 30 题 + qrels 首轮核验 | A3 / A1+B2 |
| 第 2 天上午 | 正式题 + rubric 末次核验；K/权重/阈值在 DEV 上定稿 | B2 / B1+B4 |
| 第 2 天中午 | **system-v0.2**：模型、Prompt、rerank 权重、索引、正式题全部冻结 | B1 主持 |
| 第 3 天 | 只修阻断问题，不再加功能 | 全组 |

每次 Run 必须记录（写入 run.schema.json 的必填字段）：
`model_snapshot`、`prompt_version`、`config_hash`、`dataset_version`、
`corpus_version`、`index_version`、`code_commit`、`provider_fingerprint`、
`agent_plan`、`tool_trace`、`retrieved_evidence`、`latency_ms`、tokens、`estimated_cost`。

## 6. Run / Score 数据契约

- JSON Schema：`evaluation/schemas/run.schema.json`、`evaluation/schemas/score.schema.json`
  （与规划 3.1 字段一致；condition ∈ {A,A2,B,C,D,E}，status ∈ {pending,running,completed,failed,aborted}）。
- 运行记录以 **JSONL** 落盘（`artifacts/runs/`），每条 Run 可一键复跑；失败/超时不静默丢弃。

## 7. 交付验收（B1 对应项）

- [ ] `experiment_protocol.md`、题集蓝图、配置清单、Run/Score schema 已冻结。
- [ ] 预注册主要终点、E 劣化规则、统计方法与 REPEAT 方案已写入本文档与配套文件。
- [ ] 至少 20 条离线 Evidence fixture + 5 开发题 + 5 压力题样例可用（`data/processed/fixtures/`）。
- [ ] 公平性控制 7 条铁律在协议中明确，B3/B4 可据此执行。
- [ ] D 条件结论只写“组件包整体增量”，B1 审核确认无单组件归因。
- [ ] 报告/图表可从原始 Run 记录重建（B6 负责一键运行，B1 审核协议一致性）。

## 8. 伦理与安全边界

- 不引入真实患者数据，不输出个体化诊疗结论；所有页面/报告标注“仅供教学研究，不用于临床诊疗”。
- E 条件的恶意证据仅存在于受控评测环境，不进入任何演示路径。
