# B5 分支审查报告（评审 PR）

> 审查对象：`origin/b5-evaluation`（c1f50b3）对照《OpenEvidence_MVP_赛道1与赛道3实施规划》v0.5（下称"规划"）
> 审查重点：B5 的数据指标、图表计算正确性、一致性评估、与规划设计的契合度、数据格式（§3.1 契约）合规性
> 结论：**存在 4 个 P0（阻断）问题、7 个 P1（重要）问题**；本 PR 已修复全部 P0 和大部分 P1，未修项见 §5。

---

## 0. 一句话结论

B5 的骨架（确定性指标、配对统计、bootstrap CI、置换检验、judge 偏差审计、反例、图表）设计方向正确，但当前分支**基线落后于 main（缺失 36c0c49 的 P0a/P0b 契约修复），导致两个预注册主终点在真实流水线下不可算**；同时存在多处置换/统计口径偏差和 schema 与实现双向不一致。**必须先 rebase 到 main 再合并**，本 PR 已在 b5 分支上按 main 的契约口径修复并补充回归测试。

---

## 1. P0（阻断，本 PR 已修复）

### P0-1 分支缺失 P0a/P0b 契约修复，主终点不可算（最严重）

`origin/b5-evaluation` 由 `449aa4d` 分出，**未包含 main 上的 `36c0c49`（"修复 B1/B3 契约对齐与主终点计算（响应审查 P0a/P0b）"）**。后果实测如下（用分支自带离线 fixture 跑 `evaluation/b5_report.py`）：

| 指标 | 修复前（分支原状） | 规划要求 |
|---|---|---|
| `claim_support_rate` | B/C/D/E 恒为 0.0 | 主张被证据支持的比例 |
| `unsupported_claim_rate` | B/C/D/E 恒为 1.0 | 未支持比例 |
| `citation_precision` / `citation_coverage` | 恒为 0.0 | 引用质量 |
| `unsupported_critical_claim_rate`（**主终点之一**） | 恒为 None | 关键主张未支持比例 |
| `hit_at_5` / `recall_at_50` / `rerank_ndcg_8` | 恒为 None（题集 `gold_source_ids` 为空，见 P1-8） | 检索/重排指标 |

根因有三：

1. **`generation/citation_check.py::split_claims` 被改回不写 `decision`/`verification_method`**。`Claim` dataclass 默认 `decision="pending"`，于是 B/C/D/E 所有 claims 都是 `pending`，`b5_report._compute_claim_metrics` 把 `pending` 计入 unsupported、`supported` 数为 0。这正是 main 上 P0b 修复（`decision` 按"引用编号存在性"判定 `supported/insufficient/pending`）所解决的问题。
2. **`split_claims` 一律 `criticality="important"`**，没有任何 `critical` claim，导致主终点 `unsupported_critical_claim_rate` 分母为空恒为 None。
3. **`core/dataclasses.py::Question` 删除了蓝图字段**（`split/dataset_pack/answerable/as_of_date/source_group_id/extras` 及 `key_points→rubric` 映射）。B2 正式题按 B1 蓝图格式交付（规划 §3.1/§7.2），加载后会静默丢字段：`b5_report` 的 STRESS 判定、judge 的 rubric 评分点、答题时间留痕全部失效。

**修复（本 PR）**：按 main `36c0c49` 口径恢复 `split_claims` 的 decision 路径（`n_evidence/n_search` 参数，`A`→pending、有上下文无引用→insufficient、有效引用→supported），恢复 `Question` 蓝图字段与 `key_points→rubric` 映射；离线 fixture 重生成（claims 带 `decision`/`verification_method`，run 带 `code_commit`），`tests/test_core_contracts.py` 恢复对应契约测试。

> 说明：`criticality` 仍为确定性回退的 `"important"`，`unsupported_critical_claim_rate` 只有当生成器输出结构化 `Claim[]`（criticality=critical，规划 Gate 3）或 judge/人工给出 critical 判定时才能计算。建议 B5 在正式报告中把该口径写进 limitations，并与 B1 约定：主终点的 critical 判定至少覆盖 STRESS 与关键题的人工复核路径。

### P0-2 冻结 schema 与 dataclass/运行器/fixture 三方不一致

逐字段核对 `evaluation/schemas/*.json`（B1 冻结契约）与 `core/dataclasses.py`、`evaluation/experiment.py`、`tests/fixtures/runs_offline_smoke.jsonl`：

| 字段 | run.schema.json | Run dataclass / 运行器 / fixture | 问题 |
|---|---|---|---|
| `code_commit` | **required** | 分支删除该字段（实验层不再写） | 每条 Run 违反冻结契约 |
| `status` 枚举 | `[pending..aborted]` | 运行器与 fixture 写 `"ok"`/`"error"`（dataclass 默认 `"ok"`） | 枚举不含 `ok/error` |
| `candidate_ids` | 未定义 | dataclass/fixture/`consistency.py`/`b5_report` 依赖（同源核验、Recall@50） | schema 缺字段 |
| `retrieved_evidence` | 字符串数组 | dataclass `list[dict]`、fixture 为对象、`consistency.py` 按 `e["id"]` 取 | 格式不一致 |
| `agent_plan` items | 仅 object | A 条件 fixture 写入字符串计划 | 校验失败 |

`score.schema.json` 同理：

| 字段 | score.schema.json | Score dataclass / judge.py | 问题 |
|---|---|---|---|
| `metric_version` / `rubric_version` | **required** | 分支从 dataclass 和 judge.py 删除 | judge 输出违反契约 |
| `retrieval_hit_at_k` / `rerank_ndcg` | 属性名 | 代码用 `hit_at_5` / `rerank_ndcg_8`（b5_report 靠别名兜底） | 命名不一致 |
| `unsupported_critical_claim_rate`（主终点） | 缺失 | b5_report 输出该字段 | schema 缺主终点字段 |
| `position/anonymous_label/randomization_seed/judge_family/citation_count/control_type/control_id` | 缺失 | b5_report 的 judge 偏差审计读取这些字段 | 审计字段无契约落点 |

**修复（本 PR）**：`run.schema.json` 补 `candidate_ids`、`status` 枚举加 `ok/error`、`retrieved_evidence` 恢复为对象快照（与 main 一致、可追溯）、`agent_plan` items 允许 string/object；`score.schema.json` 字段名对齐代码、补 `unsupported_critical_claim_rate` 与 judge 审计字段；`dataclasses.py` 恢复 `Run.code_commit`、`Score.metric_version/rubric_version/unsupported_critical_claim_rate/adjudication` 及审计字段；`experiment.py` 恢复 `get_git_commit`/`code_commit` 写入；新增 `tests/test_b5_report.py::test_fixture_validates_against_run_schema` 等契约回归测试（jsonschema 校验 fixture 全量通过）。

### P0-3 E-C（压力集）对比在实践上不可运行

规划 §6.2/§6.5：**E 只在 20 道 STRESS 题上运行，E-C 只在压力集上比较**，且不能与主结论混跑。当前 `b5_report`：

1. 只加载**一个** `--questions` 文件（默认 `formal12.jsonl`）；STRESS 题在另一个文件 `questions_stress`，从不会被读入。
2. `_is_stress_question` 依赖题面 JSONL 里的 `split` 字段，而 `dev8/formal12/stress_sample.jsonl` 均无 `split` 字段（B2 冻结题交付前），`stress_sample.jsonl` 只有 `rubric.perturbation`。
3. `consistency.py` 反而用"文件路径含 stress"启发式判定 split——两工具对同一事实的判定方式不一致。

结果：即使把 STRESS 题跑完，`b5_report` 的 E-C 行也恒为空（`scope="stress"` 永远无配对），报告的 "E-C was requested but no STRESS split questions found" limitation 会常态触发。

**修复（本 PR）**：新增 `--questions-stress` 参数（默认取 `config.yaml` 的 `questions_stress`），加载时把无显式 split 的压力题标记为 `split="stress"` 再合并进题集；`_load_questions_with_stress` 带测试。B2 正式题若自带 `split` 字段（蓝图格式），优先保留。

### P0-4 judge 未真正"匿名随机 + 审计留痕"

规划 §6.3.5-6.3.7：judge 需匿名随机交换 A/A2/B/C/D/E 答案顺序和标签、记录位置/长度/引用外观/模型家族/随机种子，并提供 3 类控制样本（同文异风、换位、多引用但有错引）。现状：

- `judge.py::anonymize()` 定义了但 `main()` **从未调用**；Score 行不含 `position/anonymous_label/randomization_seed/judge_family/citation_count`。
- `b5_report.judge_audit` 的 `position_bias / judge_family_bias / randomization_audit / control_sample_audit` 在真实数据下必然全部返回 `not_available`（demo 能出数只是因为它手工造了这些字段）。
- 3 类控制样本无任何生成器。

**修复（本 PR）**：`judge.py main()` 接入 `anonymize()`，每题/每 judge 用可复现种子随机展示位置，Score 落盘匿名标签、位置、种子、judge 家族、引用数；匿名映射表写入 `artifacts/b5/judge_anonymize_mapping.json`。控制样本生成器已覆盖 `style`（默认确定性同文异风改写，正式评审可用 `--style-controls llm` 走 LLM 改写）、`position_swap` 与 `wrong_citations`；`b5_report` 对缺失字段的 `not_available` 行为保留并在报告 notes 中披露。

---

## 2. P1（重要，本 PR 已修复）

### P1-1 评审一致性只有均值差，缺 kappa

规划 §6.3.6 明确"对二元标签报告 Cohen's kappa，对有序评分报告加权 kappa"。`b5_report.judge_audit.agreement` 只给 `mean_abs_diff/max_abs_diff`；`stats.py::judge_agreement` 用的是 MSE 变形（`1/(1+mse)`），都不是 kappa。

**修复（本 PR）**：新增 `_cohen_kappa` / `_linear_weighted_kappa` / `_judge_kappa`：有序 1-5 指标（relevance/correctness/completeness/faithfulness/rubric_keypoint_score）用线性加权 kappa，二元指标（值全为 0/1）用 Cohen's kappa，连续比例指标注明不适用；按"同一 judge 对在 ≥2 个 run 上的评分向量"计算（单一 run 单点无法估计 kappa，数学上必然 None）。kappa 已并入 judge audit 输出与 markdown 表。

### P1-2 置换检验剔除 0 差值，高估显著性

`paired_permutation_p` 原实现 `nonzero = [d for d in deltas if d != 0]`——平局被丢弃，等价于只对非平局做检验，显著膨胀检验功效。**修复（本 PR）**：平局保留在置换分布中（正确稀释显著性），`max_exact_n` 降到 14 控制全枚举开销；回归测试 `test_permutation_keeps_ties`（全平局 → p=1.0；含平局 p ≥ 无平局 p）。

### P1-3 E-C 反例漏掉"劣化无效果"的平局

`counterexample_rows` 只在 `E > C` 时标记 `degraded_condition_not_worse`，平局（delta==0，即检索污染无影响）同样违背预注册假设"检索污染应拖累回答"，但被漏报。**修复（本 PR）**：`delta == 0` 也标记（`test_e_c_tie_is_counterexample`）。

### P1-4 `_doc_id` 对 nct:/guideline: chunk ID 去重失效

原 `_doc_id` 对 `nct:`/`guideline:` 前缀提前 return，若将来试验/指南也按 chunk 存储（如 `nct:NCT1:chunk:0`），文档级去重会把它当成与 gold `nct:NCT1` 不同的实体，Hit@K/Recall/引文宏微平均全部失真。**修复（本 PR）**：统一先剥离 `:chunk:` 后缀（`test_doc_id_strips_chunk_for_all_prefixes`）。

### P1-5 三套统计实现并存且口径不一致

`stats.py`（普通 bootstrap + MSE 一致性）、`charts.py`（硬编码 `A-C/B-C`，其中 **A-C 不是预注册对比**，规划 §6.5 只预注册 A-B/B-C/C-D）、`b5_report.py`（分层 bootstrap + 置换检验 + Holm）并存。同一次实验三处数字可能不一致，演示图与正式报告互相打架。**修复（本 PR）**：`charts.py` 改为消费 `b5_report` 产出的 CSV；`stats.py` 保留旧导入/CLI 兼容层，但内部委托 `b5_report` 的 metric alias、配对差值、bootstrap CI 和 kappa 口径，不再作为独立统计源。

### P1-6 `abstention_quality` 二元口径需披露

当前实现：`insufficient` 题 REFUSE=1 否则 0；其余题 REFUSE=0 否则 1。`WARN`（部分拒绝/带限制回答）在两类题上都被计 0，与规划"证据不足时合理拒答、证据充分时误拒答的联合评分"的语义有出入。**本 PR 保留该 P0 确定性代理**，但要求在报告 Limitations 中披露口径（已在 `b5_report` 注释中注明）；若时间允许建议升级为 0/0.5/1 三值。

### P1-7 合并优先级：auto 确定性指标覆盖 judge 语义指标

`merge_auto_and_judge_scores` 中，只要 auto 值非空就用 auto 覆盖 judge 的 `claim_support_rate/unsupported_claim_rate/citation_precision/citation_coverage`。修复 P0-1 后 auto 值不再退化，此覆盖是"确定性优先"的一致口径（v0.1 引用存在性），但与 judge 的语义判定（verdicts）是两个概念，**必须写进报告披露**，否则读者会误以为是语义支持率。

---

## 3. P1/P2（未修项，建议后续处理）

| # | 问题 | 证据 | 建议 |
|---|---|---|---|
| 1 | 3 类控制样本无生成器（style 变体需 LLM） | 规划 §6.3.7；`judge_audit.control_sample_audit` 恒 not_available | 已实现 `style`（默认确定性同文异风改写，正式评审可用 `--style-controls llm`）、`position_swap` 与 `wrong_citations` |
| 2 | `fake_identifier_count` 是预注册 STRESS 指标（目标 0），无任何实现 | `preregistration/e_perturbation_rules.json`；`experiment_config.json` 有 `fake_identifier_tolerance=0` | Run/Score 增加结构化 `fake_identifier_count`（从 answer 文本正则 PMID/DOI/NCT + 白名单校验），b5_report 报告 |
| 3 | 检索验收指标缺 `source_diversity / context_tokens / 重复率 / 冲突率` | 规划 §4.2/§4.3.3/§4.6 | Run 已有 `tool_trace`/`retrieved_evidence`，可由 B5 增加确定性派生指标 |
| 4 | 题集 `gold_source_ids` 全空 → 检索指标全部 None | `dev8/formal12/stress_sample.jsonl` | B2 冻结正式题时必须填 gold/qrels（规划 §6.4），b5_report 的"无 gold 则省略不计"行为保留 |
| 5 | `consistency.py` 用路径启发式判 split；E 候选数对比用 `retrieved_evidence` 长度而非候选集 | `evaluation/consistency.py::_load_question_splits` | 恢复 P0a 后改用 `Question.split` 字段 |
| 6 | `b5_report` 的 STRESS 判定只认 `split=="stress"`，与 `consistency.py` 口径不同 | 同上 | 统一为题面 `split` 字段优先 + 文件路径回退 |
| 7 | `stats.py/charts.py/b5_report.py` 三套统计源 | §2 P1-5 | 已收敛到 b5_report；`stats.py` 仅保留兼容入口 |
| 8 | 分支合并前需 rebase main（36c0c49 等 5 个提交），并处理 b4 revert 提交对 fixture 的改动 | `git log main..origin/b5-evaluation` | 合并时以 main 为准重生成 fixture |

---

## 4. 本 PR 变更清单

| 文件 | 变更 |
|---|---|
| `core/dataclasses.py` | 恢复 Question 蓝图字段与 key_points 映射；Run 恢复 `code_commit`；Score 补 `metric_version/rubric_version/unsupported_critical_claim_rate/adjudication` + judge 审计字段 |
| `evaluation/schemas/run.schema.json` | 补 `candidate_ids`；`status` 枚举加 `ok/error`；`retrieved_evidence` 恢复对象快照；`agent_plan` 允许 string/object |
| `evaluation/schemas/score.schema.json` | 字段名对齐代码（`hit_at_5/recall_at_50/rerank_ndcg_8/mrr`）；补主终点与 judge 审计字段 |
| `generation/citation_check.py` | 恢复 `split_claims` 的 decision/verification_method 判定（P0b） |
| `generation/answer.py`、`evaluation/experiment.py` | 恢复 A/A2/B-E 条件感知的 claims 拆分；`code_commit` 写入 |
| `evaluation/judge.py` | 真正匿名 + 随机位置 + 审计字段落盘 + 恢复版本字段；匿名映射表导出 |
| `evaluation/b5_report.py` | STRESS 题加载（`--questions-stress`）；kappa；置换保留平局；E-C 平局反例；`_doc_id` chunk 优先；rubric_version 回退 |
| `tests/fixtures/runs_offline_smoke.jsonl` | 重生成：`code_commit` + claims `decision/verification_method`（对齐 P0b） |
| `tests/test_core_contracts.py` | 恢复 P0a（蓝图 Question）/P0b（split_claims decision）契约测试 |
| `tests/test_b5_report.py` | 新增 10 个回归测试（schema 校验、主终点、kappa、置换、STRESS 加载、反例等） |
| `README.md` | 测试数 31 → 67 |

## 5. 验证

```bash
python -m pytest tests/ -q            # 67 passed
python -m evaluation.b5_report --demo --out-dir artifacts/b5
python -m evaluation.b5_report --runs tests/fixtures/runs_offline_smoke.jsonl \
    --questions data/questions/formal12.jsonl --out-dir artifacts/b5-fixture
# fixture 全量通过 run.schema.json jsonschema 校验；B/C/D/E 的 claim 指标不再恒为 0
```
