# B4 设计审查（第一轮）— 响应《OpenEvidence_MVP_赛道1与赛道3实施规划》

> 版本：v0.1（2026-08-11）
> 审查对象：`origin/b4-work`（`8373f63 feat(b4): add offline evaluation and rerank diagnostics`）
> 审查基准：《OpenEvidence_MVP_赛道1与赛道3实施规划.md》（v0.5）§2.1/§4.2/§4.3/§4.5/§6.2/§6.3/§6.4
> 审查重点：B4 rerank 选择、劣化 RAG（E）、完整组件包（D）与 A 的一致性、评测系统设计
> 结论：框架结构（fixture/参考/混合检索器、分阶段留痕、预注册 JSON、诊断报告）总体良好；
> 但存在 5 个需要修复的设计问题（P0）和 6 个建议项（P1），本 PR 已实施 P0 中的代码修改，P1 列为后续行动。

## 1. 结论概览

| 检查项 | 现状 | 与规划差异 | 结论 |
|---|---|---|---|
| 级联 rerank（RRF→特征重排→MMR） | 已实现，权重与 §4.2.4 一致 | MMR 多样性项被 `mmr_lambda=1.0` 关闭；freshness 未区分题型；K1 分层未启用 | P0 说明 + P1 调参 |
| E 劣化规则 | 只实现 `drop_gold_v1`（删 1 条 gold） | 预注册 4 类规则（§6.3）仅 1 类，且删除语义与预注册不符 | **P0，本 PR 已修** |
| E 的 C/E 配对完整性 | gold 不在候选集时 `not_applicable` 不生成 | 20 道压力题 C/E 配对会断档（stress-003 及全部范围外题） | **P0，本 PR 已修** |
| E 劣化对生成的可见性 | 在 rrf 候选上删除 gold 后仅过滤 final context | 若 gold 未进 final context，E 输出与 C 完全相同 | **P0，本 PR 已修** |
| D 完整组件包 | runner 中 D 仅 mock plan/trace；baseline.py 中 D≡C；run_a5.py 独立 schema | §6.2 D=C+Wiki/Skill/MCP/Agent 未实现；与 A 的公平性（同模型快照/schema/成本单独计入）无法保证 | **P0 设计缺陷（需 A5 交付），本 PR 给出接口方案** |
| B3/B4 两套 run_condition | `evaluation/baseline.py`（B3，E=topk_halved 骨架）与 `evaluation/runner.py`（B4，E=drop_gold）并存 | E 在同一仓库有两套不一致实现；两套 Run schema 字段不一致 | **P0，本 PR 统一 RunRecord 契约** |
| 评测指标 | `evaluate_retrieval.py` 的 `bm25_recall_at_50==recall_at_50`（复制粘贴）；Recall@50 基于 BM25 单路而非 RRF 融合候选 | §4.3.1 Recall@50=初检候选集召回 | **P0，本 PR 已修** |
| 条件配置 | `configs/conditions.yaml` 只参与 config_hash，不参与行为 | 版本化条件配置是死配置 | **P0，本 PR 已修** |

## 2. 逐项审查

### 2.1 rerank 选择（§4.2/§4.3/§4.5）

**做得好的部分**：
- 级联链路完整：`BM25 Top-50 + Vector Top-50 → RRF(≤100) → 特征重排 → MMR`，每阶段候选、特征分和最终上下文全部落盘（`RetrievalResult` 五段留痕）。
- 权重与规划 §4.2.4 一致（semantic .30 / lexical .20 / pico .15 / evidence_level .15 / freshness .10 / source_quality .10 / redundancy −.15），`max_per_doc=2`、`max_per_source=4` 与 §4.3.2 一致。
- `scripts/ablate_rerank_components.py`、`scripts/ablate_rerank_dev.py`、`scripts/tune_rerank_dev.py` 提供 DEV 集消融/调参脚手架，含 `mmr_lambda`、`k1_rerank`、`rrf_k` 变体。

**发现的问题**：

1. **[P0-说明] `mmr_lambda=1.0` 使 MMR 退化为贪心 top-k**（config.yaml `rerank.mmr_lambda: 1.0`）。
   `mmr = lambda * final − (1−lambda) * sim`，`lambda=1.0` 时多样性项恒为 0，只剩 `max_per_source/max_per_doc` 兜底，与 §4.2.5“MMR 去冗余：按最大边际相关性选择 5~8 个片段”和“rerank 创新”定位冲突。建议在 DEV 上对 `mmr_lambda ∈ {0.55, 0.7, 0.85}` 消融（tune 脚本已具备），冻结前不要用 1.0 作为“MMR 生效”的默认值。**本 PR 不改值，仅要求调参决策留痕。**

2. **[P1] freshness 未实现“按题型加权”**（`retrieval/rerank.py::_freshness_score` 接收 `q_freshness` 参数但不使用；stable 题与 up_to_date 题衰减完全相同），与 §4.2.4“稳定机制题降低 freshness 权重，最新试验题提高 freshness 权重”不符。建议实现类型化衰减（up_to_date 题按年份衰减，stable 题用乘法因子压权）。

3. **[P1] K1 分层未启用**（`retrieval.k1_rerank: null`，特征重排直接作用全量 RRF 候选），§4.3.2 的 K1=20~30 是“调参预留”占位。对 1 万+ 语料影响不明显，但应在 DEV 上验证 `k1_rerank ∈ {30, 50, 70}` 的质量/延迟权衡后冻结。

4. **[P1] `semantic` 特征直接用 RRF 分数近似**（`feature_rerank` 中 `semantic = rrf_score`）。可解释但非真实语义分；报告中应注明“semantic≈RRF 融合分”，避免把特征重排误读为独立语义模型。

### 2.2 劣化 RAG（E）（§6.2/§6.3）

**当前实现与规划/预注册的差异（本 PR 已全部修复）**：

1. **[P0-已修] 预注册 4 类规则只实现 1 个 `drop_gold_v1`**。
   `evaluation/preregistration/e_perturbation_rules.json` 定义了 `gold_deleted / topk_reduced / unsupporting_injected / unanswerable_malicious` 四类各 5 题；代码只有 `drop_gold_v1`，且语义是“删 1 条最高排名 gold”，与预注册“删除 gold_source_ids 对应的全部证据”不符。其余 3 类完全缺失。
   → 本 PR 实现 `drop_all_gold_v1`（删全部 gold，预注册口径）、`topk_reduced`（K2 8→3、先排 gold 再截断）、`inject_unsupporting_v1`（注入 2~4 条非 gold 尾部候选，seed 确定性）、`unanswerable_malicious`（不改候选，压力由题面承载）；单题可在 `rubric.stress_rule`/`stress_rule` 字段声明规则以覆盖配置默认，支持 B2/B4 按分类分配。

2. **[P0-已修] E 在 gold 不在候选集时 `not_applicable` 且不生成回答**。
   压力题 stress-003（范围外、无 gold）及全部 `unanswerable_malicious` 类题（5 道）都会触发，导致这些题 C/E 配对缺失，§6.2“STRESS 题 C/E 配对对照”落空。
   → 本 PR：gold 删除类规则找不到 gold 时回退 `topk_reduced` 并记录原因（manifest.reason），E 始终生成回答，20 题配对不断档。

3. **[P0-已修] 劣化可能对生成不可见**。
   原实现只从 final context 过滤被删 gold；若 rerank/MMR 已把 gold 排到最终上下文之外，删除后上下文不变，E 输出与 C 完全相同，“检索污染是否拖累生成”无从观察。
   → 本 PR：E 改为在“检索阶段候选集”（B/C 同源的 RRF 融合候选）上按规则派生，返回的劣化列表直接作为 E 的生成上下文（截断到 final_k），劣化必可见（冒烟结果：drop 后原子主张 gold 命中从 2/2 变 0/2）。

4. **[P0-已修] `seed` 不参与逻辑**。
   原 `drop_gold_v1` 完全确定性、seed 仅记录。注入类规则需要随机化。
   → 本 PR：`inject_unsupporting_v1` 用 `random.Random(seed)` 选注入项，同一 (题目,规则,seed) 可复现，不同 seed 结果不同（已加测试）。

5. **[P0-需统一] B3 与 B4 的 E 是两套不一致实现**。
   `evaluation/baseline.py`（B3 实验运行器）里 E 是 `topk_halved` 骨架，并注释“B4 合入 e_perturbation_rules.json 后重写”；`evaluation/runner.py`（B4）里是 `drop_gold_v1`。同一仓库出现两套 E，正式实验用哪个取决于运行入口，属于未定状态。
   → 建议：以本 PR 的 `evaluation/stress.py` 预注册引擎为唯一实现，`baseline.py` 的 E 分支改为调用同一引擎（或删除骨架，避免双写）。

6. **[P0-需裁定] “以 C 配置为基准”与“从 B 基线初检派生”的措辞冲突**。
   实施规划 §6.2 写“E 以 C 的配置为基准”，预注册 JSON 的 derivation_rule 写“E 的劣化候选集在 B 基线初检结果上派生”。本 PR 采用“B/C 同源的检索阶段候选集（RRF 融合，与 rerank 无关）上派生”，同时满足两者——初检候选集 B/C 本来就同源，E 的派生不依赖 rerank 结果。请在冻结时把该口径写进协议，避免 B5 对候选集来源产生歧义。

### 2.3 完整组件包（D）与 A 的一致性（§6.2 公平性）

**现状**：
- `evaluation/runner.py`：D 仅给 C 的结果附加 mock `agent_plan/tool_trace` 和 `system_version`，答案与 C 完全同源（同一检索、同一 MockProvider）。
- `evaluation/baseline.py`：D 与 C 走同一分支（`use_rerank=True`），无 Wiki/Skill/MCP/Agent。
- `evaluation/run_a5.py`：是独立入口，输出 `a5-runs-*.jsonl`（A5 的 AgentRun schema），使用 A5 自带的 `MockClaimGenerator`，与 B4 的 `RunRecord`/条件矩阵、与 A/B/C/E 的生成模型都不统一。
- `docs/b4_interfaces.md` 声明的 `MockFullSystem` 在代码中不存在。

**设计问题（P0，需 A5 交付后闭环）**：
1. **D 没有真正运行“完整组件包”**，C-D 对比目前是无意义对照；`MockFullSystem` 未落地。
2. **与 A 的公平性无法保证**：§6.2 要求 A~E 使用同一生成模型快照、共同任务/安全规则、同一 claims schema；run_a5.py 用 A5 的 MockClaimGenerator，与 B3 的 `LLMClient` 生成路径不同，D 的答案格式、模型快照、claims schema 无法与 A/B/C/E 对齐。
3. **D 的额外延迟/token/成本未单独计入**（§6.2“A2/D 的额外检索或 Agent 调用次数、输入 token、延迟和成本单独计入”）；当前 D 的 mock tool_trace 无延迟/成本数据。

**建议方案（本 PR 给出接口，代码需 A5 仓库配合）**：
- 定义 `FullSystemAdapter.run(question, config) -> FullSystemResult`（`evaluation/adapters/a5_system.py::build_a5_workflow` 已具备雏形），runner 的 D 分支改为调用该适配器并转换为 `RunRecord(condition="D")`；
- D 的生成沿用与 A/B/C/E 相同的 `LLMClient` 与 claims 输出 schema（A5 的 `answer()` 改为注入同一 provider，或 D 运行器直接复用 `AnswerGenerator`）；
- `run_a5.py` 输出改为统一的 `RunRecord` JSONL（含 condition="D"、model_snapshot、tool_trace、额外 token/延迟/成本字段），与 `run_conditions.py` 的输出合并，供 B5 单一入口评分；
- `MockFullSystem` 落实现，保证在赛道一未交付时 D 链路可测。

### 2.4 评测系统设计

**做得好的部分**：
- 检索轨迹分阶段留痕（bm25/vector/rrf/rerank/final），`RetrievalResult` 契约清晰，fixture/reference/hybrid 三个检索器共用。
- 预注册 JSON、蓝图、Run/Score JSON Schema、诊断报告、离线冒烟 fixture 一应俱全；`evaluate_retrieval.py` 输出逐题诊断（`not_recalled_in_top50` / `recalled_but_not_in_final_context` / `gold_in_final_context`）便于定位检索 vs 上下文选择问题。

**发现的问题（本 PR 已修 / 需修）**：

1. **[P0-已修] `evaluate_retrieval.py` 指标口径错误**：
   - `bm25_recall_at_50`、`bm25_mrr` 是 `recall_at_50`/`mrr` 的复制粘贴别名，并非真实 BM25 单路指标；
   - 顶层 `Recall@50 / Hit@5 / MRR` 基于 `bm25_candidates` 计算，而 §4.3.1 的 Recall@50 定义是“初检候选集（BM25+Vector+RRF 融合）召回”——向量单路命中会被漏计。
   → 本 PR：顶层指标改为 RRF 融合候选口径，`bm25_*` 改为真实 BM25 单路；报告补充口径说明。该修复同时修正 `ablate_rerank_components.py`/`tune_rerank_dev.py` 的测量基准。

2. **[P0-已修] `RunRecord` 契约缺字段**：
   §3.1 Run 契约含 `replicate/seed/model/model_snapshot/provider_fingerprint/code_commit/verification_decision`；B4 的 `evaluation.schemas.RunRecord` 全部缺失，导致 B3（`core.dataclasses.Run`，字段齐全）与 B4 输出两套 schema，B5 评分/统计需要兼容两套格式。
   → 本 PR：补齐字段（带默认值，向后兼容），runner 从 config/provider 填充；`run_conditions.py` 新增 `--seed/--replicate`。

3. **[P0-已修] `configs/conditions.yaml` 是死配置**：仅被 `config_hash` 读取，条件行为全部来自 `evaluation/conditions.py` 硬编码默认值，版本化配置形同虚设。
   → 本 PR：`get_condition_config` 增加 `yaml_path` 合并逻辑（yaml 覆盖代码默认；`TO_BE_FILLED` 等占位符不覆盖），`run_conditions.py` 传入 `--config` 路径。

4. **[P1] 压力题规则归属未落库**：预注册 JSON 按“每类 5 题”分配，但题目文件没有 `stress_rule` 字段，默认全部走配置规则。建议 B2 在 STRESS 题冻结时给每道题写入 `rubric.stress_rule`（或侧车映射），并在 fixture 校验脚本里断言“四类各 5 题”。

5. **[P1] `inject_unsupporting_v1` 是工程近似**：用“非 gold 尾部候选”代理“主题相关但不支持”，真正的“不蕴含关键主张”判定需要 qrels stance / NLI（`FixtureRetriever` 有 qrel_stance 可增强）。manifest.reason 已记录近似口径，P1 增强。

6. **[P1] D 的评分入口未统一**（见 2.3）：B5 应只从一套 `RunRecord` JSONL 评分。

## 3. 本 PR 已实施的修改

| 文件 | 修改 |
|---|---|
| `evaluation/stress.py` | 重写为预注册规则引擎：`drop_all_gold_v1 / drop_gold_v1 / topk_reduced / inject_unsupporting_v1 / unanswerable_malicious`；题目级规则覆盖；gold 缺失回退 topk_reduced 保配对；seed 参与注入随机 |
| `evaluation/runner.py` | E 改为候选级派生（劣化上下文=扰动后 top-final_k，生成必可见）；RunRecord 填充 seed/replicate/model/model_snapshot/provider_fingerprint/code_commit/verification_decision；接入 conditions yaml |
| `evaluation/schemas.py` | `RunRecord` 补齐 §3.1 Run 契约字段（向后兼容默认值） |
| `evaluation/conditions.py` | `get_condition_config(condition, yaml_path)`：conditions.yaml 覆盖代码默认，占位符不覆盖 |
| `evaluation/run_conditions.py` | 传入 conditions_path；新增 `--seed/--replicate` |
| `evaluation/evaluate_retrieval.py` | 顶层 Recall@50/Hit@5/MRR 改为 RRF 融合候选口径；bm25 单路指标独立计算；报告口径说明 |
| `configs/conditions.yaml` | E 默认规则改 `drop_all_gold_v1` 并注释规则注册表；D.system_version 注明占位符语义 |
| `tests/test_b4_framework.py` | +8 个测试：RunRecord 契约字段、drop_all_gold、无 gold 回退、topk_reduced、注入确定性、unanswerable_malicious、yaml 合并/占位符、未知规则报错 |

## 4. 需要 B4/A5/B5 后续确认的行动项

1. **E 派生口径冻结**：确认“E 在 B/C 同源 RRF 候选集上派生”的表述写入实验协议（§2.2-6）。
2. **统一 E 实现**：删除/改写 `evaluation/baseline.py` 的 E 骨架，全部走 `evaluation/stress.py`。
3. **D 完整系统接入**：A5 交付后，用 `FullSystemAdapter` 替换 runner 的 mock D 分支，统一到 `RunRecord` 输出、同一生成模型与 claims schema，并单独计入 D 的额外延迟/token/成本。
4. **DEV 调参留痕**：`mmr_lambda`（建议 0.55/0.7/0.85 消融）、`k1_rerank`（30/50/70）、freshness 题型化权重；冻结 `rerank_config_version` 并写回 config.yaml。
5. **B2 压力题规则标注**：STRESS 20 题按预注册四类各 5 题写入 `rubric.stress_rule`，并加 fixture 断言。
6. **指标口径同步**：确认 B5 的 Score schema（`rerank_ndcg_8` 等）与 `evaluate_retrieval.py` 修正后的口径一致。

## 5. 复现

```bash
# 单元测试
python -m pytest tests/test_b4_framework.py

# 端到端冒烟（fixture，STRESS 上 C/D/E）
python -m evaluation.run_conditions --retriever fixture --condition C,D,E --split ALL --final-k 4 --seed 7

# 检索诊断（验证指标口径）
python -m evaluation.evaluate_retrieval --retrieval artifacts/b4/retrieval-*.jsonl --runs artifacts/b4/runs-*.jsonl
```
