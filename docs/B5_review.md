# B5 分支审查报告（b5-evaluation → main 合并审查）

> 审查对象：`origin/b5-evaluation`（c1f50b3，新增 `evaluation/b5_report.py` 共 1481 行）
> 对照文档：《OpenEvidence_MVP_赛道1与赛道3实施规划》v0.5（下称"规划"）§3.1 数据契约 / §6.4 指标 / §6.5 分析输出 / §7.2 B5 职责
> 审查方式：拉取分支后在独立 worktree 中复跑 demo 与离线 fixture，逐字段核对冻结 schema
> 结论：**方向正确但不可合并**——存在 2 个阻断级问题（基线落后 + 主终点不可算）、2 个高优先级问题（STRESS 不可运行 + judge 审计未落地），及一批契约/统计口径偏差。本 PR 已在 **main 最新基线** 上补齐 `b5_report.py` 并修复全部 P0/P1。

---

## 0. 一句话结论

B5 报告脚本的骨架设计（确定性指标、配对统计、分层 bootstrap CI、置换检验、judge 偏差审计、反例、图表）与规划 §6.4/§6.5/§7.2 的方向一致，但 **分支基于过时基线（449aa4d），缺少 main 上的契约修复（36c0c49 P0a/P0b、B4 合并、3ce3edc 主终点字段）**，导致：两个预注册主终点在真实流水线下不可算、E-C 压力集对比不可运行、judge 匿名随机审计未落地；且冻结 schema 与实现存在双向不一致。**必须先 rebase 到 main 再合并**，本 PR 即按 main 契约口径交付修复后的 `b5_report.py` 及回归测试。

## 1. 与 B5 设计（规划 §6.4/§6.5/§7.2）的符合性

| 规划要求 | 分支实现 | 结论 |
|---|---|---|
| 确定性指标（检索/引用/主张） | `compute_automatic_scores` + `_compute_claim_metrics` | ✅ 结构齐全 |
| 配对差值 + 按题型分层 bootstrap CI | `paired_delta_rows` + `_bootstrap_ci_stratified` | ✅ 口径正确 |
| 显著性 + 多重比较校正 | 配对符号翻转置换检验 + Holm（A-B/B-C/C-D） | ⚠️ 置换剔除平局，高估显著性（P1） |
| 评审一致性 | `judge_audit.agreement` 仅 mean_abs_diff | ❌ 缺 Cohen's kappa / 加权 kappa（P1，规划 §6.3.6） |
| 位置/长度/家族偏差审计 + 3 类控制样本 | `position_bias/length_bias/family_bias/control_sample_audit` 结构存在 | ⚠️ 字段无契约落点且 judge 不写入，真实数据恒 not_available（P0-4） |
| 主终点 rubric_keypoint_score | `METRIC_ALIASES` 映射到 judge 的 `correctness`（1-5 分） | ❌ 口径混淆：keypoint 覆盖率 ≠ correctness（P0-2） |
| 主终点 unsupported_critical_claim_rate | 依赖 claim.criticality=="critical" | ❌ 生成器恒 important，分母为空（P0-2） |
| E-C 仅压力集 | `STRESS_COMPARISONS` + `scope="stress"` | ❌ 题面无 split 字段、压力题文件不加载，恒为空（P0-3） |
| 反例（RAG 获益/检索拖累） | `counterexample_rows` | ⚠️ E-C 平局漏报（P1） |
| 图表（条件均值/配对差值/逐题差值/成本） | `write_charts` SVG | ✅ 可重建 |
| 成本/延迟/token | `cost_latency_rows` | ✅ |

## 2. 与数据契约（规划 §3.1 + 冻结 schema）的符合性

| # | 契约项 | 分支现状 | 判定 |
|---|---|---|---|
| C-1 | `run.schema.json` 必填 `code_commit` | 分支 dataclass/运行器不写 | ❌ 违反冻结契约（main 已修） |
| C-2 | `status` 枚举 | schema 无 `ok/error`，运行器实际写 `ok/error` | ❌ schema 与实现不一致（main 已修） |
| C-3 | `candidate_ids`（RRF 初检候选） | schema 未定义，但 b5_report/Recall@50 依赖 | ❌ schema 缺字段（main 已修） |
| C-4 | `retrieved_evidence` | schema 定义 string 数组，dataclass/fixture 为对象快照 | ❌ 格式不一致（main 已修）；B4 运行器另写 `evidence_id` 键，本 PR 已兼容 |
| C-5 | `score.schema.json` 主终点 | 缺 `unsupported_critical_claim_rate`（规划 §6.4 主终点之一） | ❌（main 已修） |
| C-6 | `score.schema.json` 检索字段名 | `retrieval_hit_at_k/rerank_ndcg` vs 代码 `hit_at_5/rerank_ndcg_8` | ⚠️ 靠别名兜底，命名不统一（main 已双向对齐） |
| C-7 | judge 审计字段（position/anonymous_label/randomization_seed/judge_family/citation_count/control_type/control_id） | schema 与 dataclass 均无；b5_report 审计读取这些字段 | ❌ **本 PR 修复**（见 §5-2） |
| C-8 | `metric_version`/`rubric_version` 必填 | 分支删除 | ❌（main 已修） |

## 3. 验证证据（复跑实测）

在 `b5-evaluation`（c1f50b3）上复跑：

```bash
python -m evaluation.b5_report --runs tests/fixtures/runs_offline_smoke.jsonl \
    --questions data/questions/formal12.jsonl --out-dir artifacts/b5-fixture
```

| 指标 | 分支原状实测 | 规划要求 | 根因 |
|---|---|---|---|
| `claim_support_rate` | B/C/D/E 恒 0.0 | 主张被证据支持比例 | `split_claims` 不写 decision，默认 pending |
| `unsupported_claim_rate` | B/C/D/E 恒 1.0 | 未支持比例 | 同上 |
| `unsupported_critical_claim_rate`（主终点） | 恒 None | 关键主张未支持比例 | criticality 恒 important，分母空 |
| `hit_at_5/recall_at_50/mrr/rerank_ndcg_8` | 恒 None | 检索/重排指标 | 题集 `gold_source_ids` 为空（B2 待交付，可接受但需披露） |
| E-C 压力集对比 | 恒空 | 压力集必做 | 题面无 split 字段 + 压力题文件不加载 |
| judge 偏差审计 | 全部 not_available | §6.3.5-6.3.7 | `judge.py::anonymize()` 定义但 main() 从不调用，字段不落盘 |

分支同时缺失 main 的 B4 运行器（`run_conditions.py`/`stress.py`/`adapters/`），无法消费当前流水线产出的 C/D/E 运行记录。

## 4. 问题清单与修改建议

### P0（阻断）

- **P0-1 基线落后**：分支基于 449aa4d，缺 36c0c49（P0a/P0b 契约修复）、B4 合并（f24f664）、3ce3edc（主终点字段/nDCG@8）。→ 建议 rebase 到 main 再合并（本 PR 以 main 为基）。
- **P0-2 两个预注册主终点不可算**：`split_claims` 不写 decision；criticality 恒 important；`rubric_keypoint_score` 别名到 correctness。→ 建议按 main 36c0c49 口径恢复 decision 判定；critical 口径写进 limitations 并与 B1 约定；主终点用独立字段而非别名。
- **P0-3 E-C 压力集对比不可运行**：只加载一个 questions 文件、题面无 split 字段。→ 建议新增 `--questions-stress` 合并加载并把压力题标记 `split="stress"`（本 PR 已实现）。
- **P0-4 judge 匿名随机审计未落地**：`anonymize()` 未接入、审计字段无契约落点。→ 建议 judge main() 接入匿名+随机位置+审计字段落盘，schema/dataclass 补字段（本 PR 已实现）。

### P1（重要）

- **P1-1 评审一致性缺 kappa**（§6.3.6）：→ 本 PR 新增 `_cohen_kappa`/`_linear_weighted_kappa`（二元用 Cohen's，有序 1-5 用线性加权，连续比例注明不适用）。
- **P1-2 置换检验剔除 0 差值**：高估显著性。→ 本 PR 保留平局，`max_exact_n` 降到 14。
- **P1-3 `_doc_id` 对 nct:/guideline: chunk ID 去重失效**：→ 本 PR 统一先剥离 `:chunk:`。
- **P1-4 E-C 反例漏报平局**：劣化无效果（delta==0）同样违背预注册假设。→ 本 PR 已标记。
- **P1-5 三套统计源并存**（`stats.py`/`charts.py`/`b5_report.py` 口径不一）：建议以 `b5_report.py` 为唯一统计源，`charts.py` 改为消费其 CSV；`charts.py` 中硬编码的 A-C 对比不是预注册对比（§6.5 只预注册 A-B/B-C/C-D）。
- **P1-6 `abstention_quality` 二元口径**：WARN 被计 0，与"联合评分"语义有出入。→ 保留确定性代理，报告披露；可选升级 0/0.5/1。
- **P1-7 auto 覆盖 judge 语义指标**：`merge_auto_and_judge_scores` 用确定性 auto 值覆盖 judge 的 claim/citation 语义分。→ 口径需在报告披露（v0.1 引用存在性），不可宣称是语义支持率。

### P2（后续）

1. 3 类控制样本无生成器：`position_swap`（确定性）与 `wrong_citations`（注入伪造 PMID）可先实现，`style` 变体标 P1。
2. `fake_identifier_count`（STRESS 预注册指标，目标 0）无实现：从 answer 正则 PMID/DOI/NCT + 白名单校验。
3. 检索验收指标缺 `source_diversity/context_tokens/重复率/冲突率`（规划 §4.2/§4.3.3）。
4. 题集 `gold_source_ids` 全空（dev8/formal12/stress）：B2 冻结正式题时必须填 gold/qrels；b5_report 的"无 gold 则省略不计"行为保留并披露。
5. REPEAT 子集方差未报告（§6.5 要求报告模型输出方差）：`aggregate_run_scores` 按 run_id 聚合，需按 question+condition 汇总 replicate 方差。

## 5. 本 PR 变更清单（base = main@3ce3edc）

| 文件 | 变更 |
|---|---|
| `evaluation/b5_report.py` | **新增**：B5 报告脚本（确定性指标/配对统计/CI/置换+Holm/引文宏微平均/judge 审计/反例/图表）；含 P0-3（`--questions-stress` 合并加载）、P1-1（kappa）、P1-2（置换保留平局）、P1-3（`_doc_id` chunk 优先）、P1-4（E-C 平局反例）；`_as_evidence_id` 兼容 B4 运行器的 `evidence_id` 键与 A5 快照的 `id` 键 |
| `tests/test_b5_report.py` | **新增**：10 项回归测试（离线，不依赖 LLM/API）——fixture 满足 run.schema.jsonschema、主终点可算、STRESS 加载、kappa、置换平局、E-C 反例、Score 审计字段契约 |
| `core/dataclasses.py` | Score 补 judge 审计字段（position/anonymous_label/randomization_seed/judge_family/citation_count/displayed_citation_count/control_type/control_id，均可选、向后兼容） |
| `evaluation/schemas/score.schema.json` | 补上述审计字段（可选属性，required 不变） |
| `evaluation/judge.py` | main() 接入 `anonymize()`；每题/每 judge 可复现随机位置；审计字段落盘；匿名映射表导出到 `artifacts/b5/judge_anonymize_mapping.json` |
| `docs/B5_review.md` | 本审查报告 |

> 说明：main 已含 36c0c49/3ce3edc 的 P0a/P0b 契约修复（Question 蓝图字段、split_claims decision、Score 主终点字段、run/score schema 对齐），本 PR 不再重复这些 diff，只补齐 b5 交付物本身缺失的部分。

## 6. 验证

```bash
python -m pytest tests/ -q                  # 99 passed（含新增 10 项）
python -m evaluation.b5_report --demo --out-dir artifacts/b5
python -m evaluation.b5_report --runs tests/fixtures/runs_offline_smoke.jsonl \
    --questions data/questions/formal12.jsonl --out-dir artifacts/b5-fixture
# 实测：B/C/D/E claim_support_rate=1.0、citation 指标可算（修复前恒 0/None）；
# E-C 仅压力集、kappa/置换/反例均有单测覆盖
```

## 7. 后续动作（不在本 PR）

- B2 冻结正式题时补 `split`/`gold_source_ids`/`topic`/`question_type` 分层字段（规划 §6.3）。
- `stats.py`/`charts.py` 收敛到 `b5_report.py` 输出（P1-5）。
- 控制样本生成器与 `fake_identifier_count`（P2）。
- REPEAT 子集方差报告（§6.5）。
