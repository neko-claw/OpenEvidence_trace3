# B3 分支 Review Comment（可直接发布）

> 审阅范围：B3 分支 `22021fc`（赛道3 B3 基线与实验运行：A/A2/B 运行器 + 重试成本日志 + B4 交叉复核审计）
> 基线：`docs/OpenEvidence_MVP_赛道1与赛道3实施规划.md` v0.5（§3.1 数据契约、§6.2 实验条件、§7.2 任务分配）
> 验证方式：31 个测试实跑全绿；`evidence.jsonl`（11630 条）离线构建 BM25+向量索引并跑通 B/C 检索、特征重排与确定性缓存；与 main 逐文件/逐条 diff。

---

## 总体结论

**核心职责（A/A2/B 运行器、重试与成本日志、B4 交叉复核审计）完成度较高，代码质量与可测试性良好，与基线 §6.2 的实验条件定义基本吻合；但存在 1 个阻塞级协调问题（分支分叉导致与 B1 交付物脱节）、2 个日志不充分问题（claims 与候选集/特征未留痕）、1 个与计划的 P0 冲突（E 条件地位），且分支上没有任何真实运行记录可被评分。建议修复后合入，不建议按当前状态直接作为正式实验运行基线。**

---

## ✅ 符合基线设计的部分

对照规划 §6.2 / §3.1 / §7.2，以下实现与基线一致：

1. **A closed-book**（`evaluation/baseline.py`）：无检索、不提供 Evidence、禁止任何 `[E#]/[S#]/URL`（出现即 WARN 并记录 error），符合 "A 不因无法访问 Evidence 被强制记为 citation coverage=0" 的公平性要求。
2. **A2 通用搜索对照**（`evaluation/a2_search.py`）：与项目 Evidence store 完全隔离；固定搜索预算（max_searches/max_results_per_search，超限抛 `SearchBudgetExceeded`）；每次搜索响应快照写入 tool_trace；引用用 `[S#]` 与 `[E#]` 严格区分；搜索成本并入 `estimated_cost`；mock（离线、标注 simulated）与 serper（真实）双 provider，符合 §6.2 A2 的预算与快照要求。
3. **B 固定 RAG**：BM25(k=50) + 向量(k=50) + RRF 融合后直取 top-k，不做 rerank/Wiki/Agent，符合 §6.2 B 的中间基线定义；B 与 C 共享同一初检候选集（仅 rerank 开关不同），`consistency.py` 有候选同源检查。
4. **Run 契约字段**（§3.1）：seed / replicate / config_hash（含 git commit）/ dataset_version / corpus_version / index_version / model_snapshot / provider_fingerprint / attempt_count / cache_hits / status / error 齐全，且每次 run 即时增量落盘 JSONL。
5. **随机条件顺序**：每题 `rng.shuffle(cond_order)`（seed 固定），符合 §6.2 "条件运行顺序随机"。
6. **失败不静默丢弃**：异常 run 写入 `status=error + error` 原文，符合 §6.6 "失败或超时不静默丢弃"。
7. **重试日志**：`LLMClient` 指数退避重试并记录实际尝试次数 → `Run.attempt_count`。
8. **检索成本/缓存日志**：EvidenceStore 确定性检索缓存 + `cache_hits` 计数，符合成本留痕要求。
9. **B3 副责（交叉复核 B4）**（`evaluation/consistency.py`）：检查 B/C/D/E 的 model/prompt/索引/语料/config 一致性、C 候选同源、E 劣化合规、A2 预算、Run 完整性，维度与 §6.2 公平性控制对应。
10. **检索质量拒答门**：B/C/D 最佳 RRF 分低于阈值（0.015）→ REFUSE 并记录原因，对应 §5.7 Gate 2 的简化版。
11. **测试**：31 个测试全部通过且全部离线（A2 mock、无 LLM 依赖），覆盖 Run 契约、A2 预算/快照、引用白名单、一致性审计、检索/重排基础函数，符合"关键契约"测试要求。

---

## ⚠️ 主要问题

### P0-1 阻塞：分支分叉，与 B1 交付物（main）完全脱节（协调问题）

B3 从 `1f15af9` 分出，**早于** main 上 B1 的交付 `bfc53f6`。当前 B3 分支缺少：

- `docs/experiment_protocol.md`（实验协议/预注册草案）
- `evaluation/schemas/run.schema.json`、`score.schema.json`（冻结契约的 JSON Schema）
- `evaluation/preregistration/e_perturbation_rules.json`（E 劣化**预注册**规则）
- `evaluation/blueprints/question_blueprint.json`、`experiment_config.json`、`make_fixtures.py`、`evaluation/README.md`
- `data/processed/fixtures/evidence_fixture.jsonl`、`sample_questions.jsonl`（20 条离线 fixture）
- `ingestion/fulltext_service.py`、`data/processed/fulltext_chunks.jsonl`（全文增强层 698 篇）

而 B3 自建了一套平行栈：`core/`（dataclass 版 Run/Score 契约）、`retrieval/`、`generation/`、`evaluation/`（baseline/experiment/a2_search/consistency/judge/metrics/stats/charts）。后果：

- **契约双轨**：main 用 JSON Schema 冻结 Run/Score，B3 用 dataclass 定义同名契约。合入时必须二选一（建议以 B1 的 schema 为准做映射，dataclass 提供 `to_dict` 兼容）。
- **E 规则失效**：B3 的 E 实现（top-k 减半）不读取 `e_perturbation_rules.json`，与预注册规则不一致（见 P0-3）。
- **fixture 缺失**：规划 §7.3 要求 B 组"用 5 条固定样例 Evidence 并行开发"，B3 无法引用 B1 的 fixture（自建了 `scripts/build_sample_data.py` 兜底，但非同一份数据）。
- 另外：B3 分支的 `data/processed/evidence.jsonl`（11630 条）与 main（10197 条）已分叉（B3 多 2438 条、少 1005 条，共享 ID 内容 hash 一致）。跨组按冻结数据文件交接的原则要求：**合并前需确定唯一语料版本**，并利用 `corpus_version` 校验正式实验的语料一致性。

**建议**：先 `git merge main`（或 rebase 到 main）解决契约与 fixture 冲突，再继续；不要在分叉状态上做正式实验。

### P0-2 日志不充分：`Run.claims` 从未填充，两个预注册主终点无法计算

规划 §6.4 明确两个主终点为 `rubric_keypoint_score` 与 `unsupported_critical_claim_rate`，且 §3.1 Run 契约含 `claims`（claim_id/text/criticality/evidence_ids/verification...）。但当前 `AnswerGenerator` 从未写 `run.claims`（`split_claims` 只在测试里用到），`citation_coverage`/`claim_support_rate`/`unsupported_claim_rate` 无法从 Run 记录自动计算。此外：

- 生成仍是自由文本 Markdown + 正则抽取 `[E#]`，没有 §6.2 要求的"所有条件使用同一 claims 输出 schema"（结构化 Claim[] 输出）。
- `verification_decision` 目前只由"非法引用/URL/检索质量门"触发，没有逐 claim 的 supported/unsupported 判定（Gate 5 未落地，可接受为 P0 简化，但需在报告披露）。

**建议**：在 `generate()` 返回后补一步：按"结论摘要/证据说明"的列表项拆出 Claim 并绑定 `[E#]`（`split_claims` 已有雏形），写入 `run.claims` 与 `run.citations`，保证 Score 阶段能算主终点；或与 A5 对齐统一的结构化输出。

### P0-3 E 条件与计划 P0 冲突（属 B4 职责，需移交对齐）

规划把 E（STRESS 20 题 C/E 对照）列为 **P0 必做**（"不得取消 20 道压力题的 C/E 对照"），但：

- `config.yaml` 注释写 "E 为 P1 劣化实验"，`evaluation.conditions` 默认 `[A,B,C,D]` 不含 E；
- `--questions` 只支持 `dev8/formal12`，**没有 STRESS 题集入口**；
- B3 的 E 实现（`baseline.py` 中 top-k 减半）不读取 B1 的 `e_perturbation_rules.json`，且只覆盖"降低 top-k"一种扰动，缺少计划 §6.3 要求的"删除 gold / 注入主题相关但不支持的证据 / 含提示注入或伪造 PMID 的恶意证据"；
- 计划 §6.2 要求 E 的劣化候选集从 **B 的基线初检结果**按预注册规则派生；B3 当前从 C 配置（use_rerank=True）的结果减半，派生基准不符。

**建议**：将 E 骨架移交 B4，由 B4 按 `e_perturbation_rules.json` 重写（分支合并后该文件才可见），并把 E 正式列为 P0 条件。

### P0-4 无真实运行记录：`data/experiments/` 不存在

分支上没有任何 A/A2/B 的 Run JSONL（需要 DEEPSEEK_API_KEY）。规划第 1 天验收要求"至少 2 道题的 A/B/C/D/E 运行记录可被评分"，§8 开工门槛要求"至少一个离线回放路径可用"。目前：

- 测试全部为离线单测，无法验证 `experiment.py` → `run_condition` → `LLMClient` → JSONL 留痕的端到端链路；
- B4/B5 无法基于现有仓库联调 C/D/E 与评分脚本。

**建议**：提交一次 `--limit 2` 的冒烟运行 JSONL（真实 key 或临时 mock LLM），并补一个"离线回放"模式（计划 §10 风险表已要求），让无 key 环境下也能验收日志完整性。

---

## 🔧 次要问题（合入前可一并处理）

1. **职责越界/与赛道 1 重叠**：B3 自建了 `retrieval/`（index/bm25/vector/rrf/rerank/mmr/query_expansion）、`generation/`（answer/prompts/citation_check）、`core/`（llm/embeddings/config/dataclasses）、`app.py`（Streamlit）——这些在计划中是 A2/A3/A4/A5/A6 的交付物。仓库未建成时自建可跑通是务实的，但**需与 A 组明确**：这些是"临时替代"还是"正式并入"？否则与 A4 的 `search()/rerank()`、A5 的 `answer()` 合入时重复且冲突。建议把 retrieval/generation 中属于赛道 1 的代码抽出为共享包，由 A 组认领并冻结接口。
2. **rerank 参数与计划 §4.2/§4.3.2 偏差（属 A4 调参范围，但代码体现）**：
   - 缺失 K1 两阶段：当前对 RRF 全部 100 条算特征再 MMR 选 8，没有"先特征重排到 20~30 再精排"的 K1 分层与配置项；
   - `q_freshness` 硬编码 `"stable"`，未使用 `Question.freshness`（计划要求稳定题降低时效权重、最新试验题提高）；
   - MMR `max_per_source=3` 硬编码，计划初始值为 `max_chunks_per_doc=2` / `max_chunks_per_source=4` 且应进配置；
   - `lexical` 特征恒为 0.5 占位、`_pico_match_score` 为词面重合简化版——P0 可接受，但需在特征日志/报告中披露，且**不得把"相关但不支持"的证据当支持**（Gate 5 未实现）。
3. **B 的初检候选集与特征分未落盘**：Run 只存最终 top-8 证据，RRF-100 初检候选集与逐候选特征分未写入 Run（§4.2"必须保存每个候选的特征分数和最终名次"）。`consistency.py` 的 C 同源检查只能比对 B/C 的 top-8 交集，无法严格核验候选集同源。建议 Run 增加 `candidate_ids`（或检索阶段单独导出候选快照）。
4. **A2 公平性细节**：mock 结果与项目证据库刻意隔离（✓），但 8 条固定页面按关键词打分，相关性过强，README 已注明不得用于声称真实搜索能力（✓）；建议报告明确 A2=mock 仅流程演示。
5. **judge.py 骨架（B5 职责）**：匿名映射用固定 seed 且按 condition 排序映射（非随机交换），无位置/长度偏差控制样本、无 kappa——作为骨架可接受，但需在 B5 阶段补全并替换为不同模型家族 judge（`config.yaml` 已注明同家族偏差风险，✓）。
6. **小瑕疵**：
   - `experiment.py` 异常分支 `attempt_count=llm.retries`（写死 3）而非实际尝试次数；
   - `--questions` 硬编码 choices（dev8/formal12），正式题集（60 TEST/20 STRESS/10 EXTERNAL）冻结后需参数化为路径；
   - README 声称"已内置 367 条真实证据库"，实际 `evidence.jsonl` 为 11630 条，建议同步修正；
   - 题目文件 `dev8/formal12` 为占位量（8/12 vs 计划 30/60），且与 B2 的题集隔离要求（source_group_id）尚不相关——占位阶段可接受，正式前由 B2 替换。

---

## 与其他部分的配合评估

| 配合对象 | 现状 | 风险/建议 |
|---|---|---|
| B1（实验协议/schema/预注册） | **脱节**：分支缺 B1 全部交付物，契约双轨、E 规则失效 | 先 merge main，统一 Run/Score 契约，按 `experiment_protocol.md` 对齐条件协议 |
| B2（题集/gold） | 运行器依赖 `dev8/formal12` 占位文件 | 参数化题目路径，正式题冻结后接入 30/60/20/10/10 分层 |
| B4（C/D/E） | B3 已实现 B/C/D 共用 `run_condition` 骨架与 E 简化版；consistency.py 可审计 B4 | E 移交 B4 按预注册规则重写；B/C/D 接口已就绪，配合良好 |
| B5（指标/judge/统计） | metrics/stats/charts/judge 已有骨架；但 `run.claims` 为空导致主终点算不出 | 补 claims 留痕后，B5 可直接消费；judge 匿名需 B5 重做 |
| 赛道 1（A2-A6） | B3 自建了赛道 1 的检索/生成/UI 栈；共享 `evidence.jsonl` 已在两分支分叉 | 明确自建栈去留；冻结唯一语料版本并校验 corpus_version |
| B6（可复现/展示） | 一键命令（README + start.sh + experiment CLI）已具备 | 补真实 runs JSONL 与离线回放后可达"一键复跑" |

---

## 结语

B3 的 A/A2/B 运行器、重试成本日志与交叉复核审计**完成度高、与基线设计吻合、测试扎实**，作为"实验运行器"质量可以接受；但它同时扮演了赛道 1 的部分实现者，并在分支分叉状态下工作，导致契约、预注册规则与共享语料三处与 main 脱节。**合入前必须：① merge main 统一契约与 fixture；② 补 claims/候选集留痕；③ E 移交 B4 并按预注册规则重写、恢复为 P0；④ 提交一份端到端 runs JSONL 样例。** 这四点补齐后，B3 部分即满足 §6.6 与 §9 赛道 3 验收清单中属于它的条目。
