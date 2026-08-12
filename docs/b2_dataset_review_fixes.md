# B2 数据集重构修复记录（响应冻结前审阅）

> 审阅结论来源：B2 数据集冻结前复核（7 个 P0/P1 问题）＋ `docs/b2_dataset_review.md` 前一轮审阅。
> 本分支（b2-final）在**当前 main**（含 B4/B5 全部代码）基础上重做 B2 交付，修复审阅指出的全部 P0 与可落地的 P1。
> 重建入口：`python scripts/rebuild_test_set.py` → `python scripts/validate_dataset.py`（PASS 口径 = 运行时唯一主集）。

---

## 1. 修复对照表

| # | 审阅问题 | 严重度 | 修复 | 验收 |
|---|---|---|---|---|
| 1 | 选择题选项在运行时丢失（69/77 有 options，但 Question 契约与 Prompt 不渲染） | P0 | `core/dataclasses.py` Question 新增 `options: list[str]` 与 `expected_action`；`generation/prompts.py` A/A2/B/C/D/judge 全部渲染选项（固定字母顺序）；`evaluation/questions.py` 归一化 dict/list 两种 options 格式 | 实测：MCQ 的 Prompt 含 “选项（请按字母选择或引用）：A. … B. …”；validator 检查“有答案但缺选项 = 0” |
| 2 | 验证器统计 91 道“有效 TEST”，实际运行时只加载 77 道 → PASS 是误报 | P0 | `scripts/validate_dataset.py` v3 只按运行时唯一主集 `test_set/questions.jsonl`（77 TEST + 33 DEV）判定；latest/supp 补充题并入主文件，不再另计 | validator PASS 的题型/主题/来源占比 = 真实运行口径 |
| 3 | 评分指南 150 行仅 144 个唯一 ID（6 个重复）；REF-007 空评分点；94 道只有泛化评分点 | P0 | `rebuild_test_set.py` 重建 `scoring_guide.json`：ID 唯一（164 条）、空评分点=0、REF-007 补冲突综合题 rubric、新题（authored/supp）自动生成评分点、权重归一化；question↔guide 一对一 | validator 检查重复 ID=0、空评分点=0、无指南题=0 |
| 4 | `gold_verified=true` 来自自动流程，不构成医学金标准 | P0 | 全部题 `gold_verified=False` + `gold_verification_status=pending_review`；validator 拒绝任何自动 `gold_verified=true` | validator：gold_verified=True 的题 = 0 |
| 5 | 题型/可回答性/系统动作/检索难度混在一起（检索失败被当成不可回答） | P1 | 输出 `question_type`（题型）、`answerability`（可回答性）、`expected_action`（ANSWER/WARN/REFUSE）三字段解耦；`REF-007` 设 WARN；validator 校验 REFUSE↔answerability=false 一致 | validator：动作/可回答性不一致 = 0 |
| 6 | 题库对 RAG/rerank 区分能力不足（最新研究仅 2/77；69/77 是公开选择题） | P1 | TEST 重建为 **19/19/19/20**（稳定机制/指南治疗/最新研究/证据不足·冲突·范围外），主题 **39 高血压 + 38 血脂**；最新研究 19 道（15 道自 latest_research + 4 道新出题，gold 全部在语料库）；来源家族全部 ≤40%（MIRAGE 家族 33.8%）；`as_of_date`/`corpus_cutoff` 时间留出保留 | validator：四类 ≥15（当前 19/19/19/20）、主题 ≥30（当前 39/38）、MIRAGE ≤40% |
| 7 | 正式 STRESS 集与预注册 E 扰动未接入运行时 | P0 | `config.yaml` `questions_stress` → `test_set/stress_20.jsonl`（重建时生成）；`experiment.py` `stress` 别名指向正式压力集；`evaluation/baseline.py` E 路径按 `perturb_type` 映射规则（retrieval_damage→delete_gold_v1、injected_unsupported→inject_polluted_v1、no_evidence_outscope→out_of_scope、malicious_injection_fake_id→malicious_fake_id）并传入 `polluted_evidence_ids`；`evaluation/stress.py` 支持新规则别名 + 合成注入条目（库外污染 ID 替换为语料库内同主题证据） | 实测 20 道 STRESS C/E 配对跑通：删除 gold、注入污染证据（I01 注入 3 条库内记录且进入上下文）、范围外/恶意题不改候选集 |

## 2. 数据口径变化

| 项 | 之前（旧分支） | 现在（本分支） |
|---|---|---|
| 运行时主集 | `test_set/questions_110.json`（77 TEST 与补充包分离，validator 却算 91） | `test_set/questions.jsonl`（33 DEV + 77 TEST 合一，validator 只算 77） |
| TEST 题型 | 36/29/2/10 | **19/19/19/20** |
| TEST 主题 | 46/31 | **39 高血压 / 38 血脂** |
| 最新研究题 | 2（旧 PubMedQA，gold 不在库） | 19（15 自 latest_research + 4 新出题，gold 全部在库） |
| 来源家族 | MIRAGE 49.4%（超 40% 上限） | MIRAGE 33.8%，全部 ≤40% |
| options | 运行时丢失 | Question 契约保留 + Prompt 渲染 |
| gold 状态 | `gold_verified=true`（自动推导） | 全部 `pending_review`（诚实标注，冻结前须人工核验） |
| gold 在库率 | q110 中 52/129 不在语料库（wikipedia 为主） | 100% 在库（wikipedia gold 由库内证据替换并标注） |
| STRESS | 样例 5 道，未接运行时 | 正式 20 道（4 类扰动各 5），`stress_20.jsonl` 带规则映射，C/E 配对实测通过 |

## 3. 新出题（LLM 候选，gold 为库内真实文献，须人工核验）

- **最新研究 TEST（4）**：LATEST-21（NPR-1 激动剂 XXB750，pmid:41563174）、LATEST-22（Baxdrostat Bax24，pmid:41794437）、LATEST-23（口服 PCSK9 抑制剂 enlicitide，pmid:42017875）、LATEST-24（强化 LDL 靶向 ASCVD，pmid:41910315）
- **最新研究 DEV（2）**：LATEST-25（单片低剂量三联 vs 标准单药，pmid:41670573）、LATEST-26（匹伐他汀+依折麦布 meta，pmid:42178931）
- **不足/拒答 TEST（5）**：SUP-REF-06~09（REFUSE）、SUP-REF-10（WARN，135/85 mmHg 指南阈值比较，gold=acc-aha-2017/esc-2024）
- **不足/拒答 DEV（4）**：SUP-REF-D01/D03/D04（REFUSE）、SUP-REF-D02（WARN，老年血压波动，gold=cn-elderly-hyp-2019）

## 4. 已知限制（冻结前必须完成）

1. **gold 与 rubric 仍是 pending_review**：全部由自动管线 + LLM 起草，未做医学人工核验。正式实验前须由医学人员逐题核验 gold_source_ids、answer_text、关键评分点。
2. **69 道公开 MCQ 的开放化**：P0-1 已保证选项在生成/judge Prompt 可见（选择题可用）；把公开选择题改写为开放证据问答属 P1（审阅建议保留）。
3. **区分度实证**：本次未在完整 77 题上跑全量 A/B/C/D（成本限制）；建议正式实验前用 DEV 33 题预跑多条件，剔除全对/全错/无方差题（审阅第 5 步）。
4. **STRESS 中 retrieval_damage 题 gold 部分为库外 wikipedia**：E 已按预注册回退 topk_reduced 保 C/E 配对（manifest 记录原因）；如需纯删除 gold 语义，须将相关 gold 替换为库内证据。
5. **评分指南深度**：MCQ 类仍以“识别正确选项/正确拒答”为主评分点；多关键点 rubric 覆盖最新研究与新增拒答/冲突题（20 余道），其余按审阅意见保持可解释的简单 rubric。

## 5. 复现命令

```bash
python scripts/rebuild_test_set.py     # 重建 questions.jsonl / stress_20.jsonl / scoring_guide.json / qrels.jsonl / dataset_manifest.json
python scripts/validate_dataset.py     # v3 合规校验（PASS = 真实运行口径）
python -m pytest tests/ -q             # 104 passed

# 运行入口（正式主集 / 正式压力集）
python -m evaluation.experiment --questions testset --conditions A B C D
python -m evaluation.experiment --questions stress --conditions C E
```

---

## 6. 后续修复（嵌入/评审/门禁/全文层，2026-08-12 第二轮）

| 项 | 内容 | 验证 |
|---|---|---|
| 嵌入模型 | 阿里云百炼 **qwen3.7-text-embedding**（1024 维，`embedding.backend=api`，batch=20 上限，重试+退避） | 22,206 文档索引构建完成（含全文层），检索命中最新研究题 gold |
| judge 独立家族 | **qwen3.8-max**（DashScope）作 judge，与生成模型 deepseek 不同家族（`config.judge` 段独立 provider） | 实测双 judge 评分出现真实分歧（faith 3 vs 4） |
| 拒答语义门禁 | `generation/citation_check.detect_refusal`：回答主体出现"无法回答/证据不足/现有证据不支持"等标记 → 无引用判 REFUSE，有引用判 WARN | STRESS 范围外题 C/E 均正确 WARN（不再误报 PASS） |
| A2 离线 mock 修复 | prompt 示例改为 `[S#]`/`[E#]` 占位符（不再含字面 `[S2]`），OfflineLLM 不再生成越界引用 | A2 离线 run 只引用实际结果编号，无越界 WARN |
| claims 结构化增强 | `split_claims` 增加 criticality 规则判定（高风险/安全/剂量表述→critical）+ evidence_ids 映射为真实证据 ID | `unsupported_critical_claim_rate` 主终点不再恒为 None；107 tests |
| 全文层接入检索 | `retrieval.include_fulltext=true`：12,023 个 Europe PMC OA 分块进入 BM25/向量索引（共 22,206 文档） | 索引版本更新，全文 gold 可检索 |
| STRESS gold 库内化 | retrieval_damage 题 gold 由语料库内同主题证据替换（删除 gold 扰动真正生效） | validate PASS，qrels 含 STRESS 26 条 |
| .env 统一加载 | `load_config()` 自动注入 .env（嵌入/judge 各后端不再依赖调用方） | 各 CLI 入口直接可用 |
| 索引断点续跑 | `scripts/build_index_checkpoint.py`：分批嵌入+增量检查点，网络中断可续跑 | 全程 ~30 分钟完成 22,206 条 |

## 7. rerank 分析方式（实测，DEV 33 题含 gold 25 题）

**方案**：可解释特征加权重排（`S_feature = w1·semantic + w2·lexical + w3·pico + w4·level + w5·freshness + w6·source − w7·redundancy`）+ MMR 去冗余，四层分离记录（bm25/vector/rrf/rerank 候选 + 特征分），消融用 `scripts/ablate_rerank_components.py`。

**消融实证**（`final-k=8`，DEV 25 题有 gold）：

| 变体 | Recall@50 | 最终上下文 gold 命中 | 最终召回 |
|---|---:|---:|---:|
| R0 rrf_only | 0.613 | **0.32** | 0.21 |
| R1 default（特征+MMR） | 0.613 | **0.56** (+75%) | 0.40 |
| R1 + lexical_rescue | 0.613 | **0.60** (+88%) | 0.44 |
| R1 + rank_guard_no_authority | 0.613 | 0.60 | 0.41 |

结论：rerank 不改变初检召回（Recall@50 恒定 0.613，由 BM25/向量决定），但显著提高 gold 进入最终上下文的比例（0.32→0.56）。P1 可选 Cross-Encoder/BGE 在 R1 基础上对前 30 条精排（`rerank_config_version` 记录，只调 DEV 不调 TEST）。
