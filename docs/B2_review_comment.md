# B2 分支 Review Comment：赛道 3 测试集（题集与 gold 治理）

> 审阅范围：`codex/track3-test-set` 分支 `0ce730d`（MIRAGE 筛选 780 题 + 自建拒答 10 题 + 评分脚本）
> 基线：`docs/OpenEvidence_MVP_赛道1与赛道3实施规划.md` v0.5（§6.3 题集设计、§7.2 B2 职责、§9 验收清单）
> 交叉参照：main 分支 B1 交付物 `evaluation/blueprints/question_blueprint.json`（130 题蓝图，本分支因分叉不可见）
> 说明：题目数据本体（`*_related.json` 等）未入库，本审阅基于 README / manifest / score.py / 语料 manifest 与 MIRAGE 数据集特性。

---

## 总体结论

**三个被评估项的结论：① 疾病类型"部分符合、需收紧"；② 答案可溯源性"大部分题目不能从现有语料回答"；③ 难度分级"完全不符合文档要求"。当前分支的内容作为"外部基准题的候选题源"有参考价值（MIRAGE 780 题的方向正确、筛选脚本思路可行），但作为赛道 3 的题集交付物不满足 MVP 要求：与 B1 的 130 道分层蓝图结构不对齐，缺少每题的题型/难度/关键回答点/answerable/as_of_date/gold/rubric 字段，且分支分叉（早于 main 上 B1 蓝图 `bfc53f6`）导致与题集蓝图、Run/Score 契约脱节。建议保留筛选与评分脚本思路，按 B2 职责重构为蓝图结构后再冻结。**

---

## 一、疾病类型是否符合 MVP 要求 —— ⚠️ 部分符合，需收紧

**符合的部分**：
- `manifest.json` 严格关键词方向正确：hypertension / blood pressure / antihypertens / lipid / cholesterol / ldl / hdl / triglyceride / statin / dyslipidemia 等，与 MVP"只聚焦高血压 + 血脂"（§1、§2.1）一致；
- 已剔除"仅命中 cardiovascular 关键词"的 90 题，说明筛选时已有范围意识。

**不符合/风险**：
1. **宽泛心血管题越界**：`strict_topic=false` 的题目仅命中 heart failure / stroke / coronary / myocardial infarct / angina 等宽泛词，而文档明确"心脑血管其他子主题作为扩展（P1），避免 3 天内数据范围失控"。当前筛选保留了这类题，等于把 P1 主题混入正式评测。
2. **子串误匹配引入其他疾病**：README 自认 `statin` 会命中 somatostatin、`lipid` 会命中 antiphospholipid/phospholipid。这些是其他疾病（生长抑素瘤、抗磷脂综合征、磷脂代谢病），既不在 MVP 范围，其证据也不在语料库中，会直接污染题目纯度。
3. **无逐题人工复核记录**：文档 §6.3 要求"子串匹配会误伤个别词……使用前请人工复核"，当前只有自动筛选、无逐题 topic 复核结果与剔除清单，无法证明正式题主题纯度。

**结论**：疾病类型大方向对，但需做"严格主题 + 人工复核"两道收紧，把宽泛心血管题与误匹配题剔除或明确标注为 P1。

---

## 二、答案能否从数据库文献中得到 —— ❌ 大部分不能

语料库现状（`data/processed/manifest.json`）：11630 条记录 / 9547 篇去重文献（PubMed 摘要 7295、Europe PMC 独有 693、ClinicalTrials 1541、人工指南 18、全文 chunk 2083），主题仅 hypertension 8480 + lipids 6534，18 份中英文高血压/血脂指南。**语料对高血压、血脂覆盖充分，但主题边界固定**。按此评估 780 题的可回答性：

| MIRAGE 子集 | 题数 | 是否可从库内文献得到答案 |
|---|---|---|
| PubMedQA / BioASQ | 16 | **理论上可**：文献型 yes/no 题，附 PMID；库内有 7947 个唯一 PMID，若 PMID 在库内则检索可定位。但**未核验**这 16 个 PMID 是否在库、未建立 gold 映射 |
| MedQA / MedMCQA / MMLU | 764 | **基本不能**：USMLE/医学综合选择题，跨药理、生理、遗传、心电图、传染病等全学科，语料只覆盖高血压/血脂；且无 PMID、无 gold 可追溯 |

关键问题：
1. **无 `gold_source_ids` 映射**：README 明确"答案来自 MIRAGE 原数据，未经本项目人工核验"。文档 §6.3 要求"候选题必须由人基于真实 PubMed/指南/试验记录建立 `gold_source_ids` 和关键评分点；LLM/外部数据集生成的 DOI、PMID、答案不能直接进入 gold"。MIRAGE 答案不能直接充当本项目 RAG 评测的 gold。
2. **语料覆盖不匹配**：764 道选择题的正确答案无法从高血压/血脂语料中检索到证据链，B/C/D 条件的检索增益无从谈起，还会制造大量"检索为空仍被闭卷模型答对"的干扰样本。
3. **训练污染混杂**：MedQA/MMLU 等公开基准已在 LLM 训练语料中，A closed-book 可凭记忆作答，会混淆 A-B 配对差值的归因；文档将其定位为 EXTERNAL（仅做确定性评分 + 抽查、不参与主对比）正是为此。

**结论**：以现有语料，780 题中真正可回答的比例很低；必须先做"可回答性审计"，把可回答子集（大概率主要是 PubMedQA/BioASQ 与少数选择题）标注出来，其余不能进入正式题。

---

## 三、难度分级是否符合文档要求 —— ❌ 不符合

- 文档 §6.3 要求每题预先写明"**题型、难度、关键回答点、answerability、as-of date、可接受证据、反对证据和扣分项**"；B1 蓝图 `question_required_fields` 也包含 `difficulty`。
- 实测当前分支：`manifest.json`、`README.md`、`score.py` 中**均无 difficulty 字段**；MIRAGE 原数据亦无难度标注；score.py 只按 `answer_letter` 判对错，不支持按难度分层报告。
- 文档本身只要求"难度"字段、**未定义难度分级量表**——这本身就是 B2 需要先冻结的空白：需要给出可操作的难度判据（例如按证据深度/题型/是否需要多源交叉），而不是拍脑袋 1/2/3。
- 连带缺失：无 `as_of_date` → 无法执行"最新研究题时间留出"（§6.3）；无 `question_type` → 无法落地四类题型各 15 道的分层。

**结论**：难度分级（以及题型、answerability、as_of_date、gold、rubric）全部缺失，与文档 §6.3 与蓝图字段要求差距大。

---

## 四、结构对齐补充（与 B1 蓝图比对）

| 蓝图要求（B1 `question_blueprint.json`） | 当前分支 | 差距 |
|---|---|---|
| 130 题 = DEV 30 + TEST 60 + STRESS 20 + EXTERNAL 10 + RESERVE 10 | 780 题无 split 标签 + 自建拒答 10 | 无分层、无 DEV/STRESS/EXTERNAL/RESERVE 入口 |
| TEST 60：四类题型各 15，高血压 30 + 血脂 30 | 无题型/主题配额控制（MedQA 600 一家独大） | 无法分层统计 |
| 单一来源 ≤ 40%（人工/指南/公开基准/LLM 各 18/18/12/12） | 来源全部为 MIRAGE（外部基准）+ 自建 10 | 来源结构未按蓝图 |
| STRESS 20 = 删 gold/降 top-k 5 + 注入不支持证据 5 + 范围外 5 + 提示注入 5 | 自建拒答 10 题仅覆盖"范围外/提示注入"一类 | STRESS 三类扰动缺失 |
| 每题必含 difficulty 等 13 个字段 | 无 | 全部缺失 |
| 分支基于 `1f15af9`，早于 main 上 B1 蓝图 `bfc53f6` | 与 B3 同样分叉，蓝图/Run-Score 契约不可见 | 需先 merge/rebase main |

---

## 五、B2 相关建议（仅 B2 职责范围：题集与 gold 治理）

> 以下建议只覆盖 B2 的题集/出题/gold/盲评职责，不涉及 B3/B4/B5 的运行器、评测或统计职责。

1. **重构为 130 题分层题库**，字段对齐 `question_blueprint.json` 的 13 个必填字段（id/split/dataset_pack/topic/difficulty/language/question/question_type/answerable/as_of_date/source_provenance/source_group_id/gold_source_ids/rubric_version）。先 merge/rebase main 拿到蓝图再动工，避免在分叉状态上冻结题集版本。

2. **冻结难度分级定义（B2 需补文档空白）**：文档只要求"难度"字段未定义量表。建议定义 3 级并给出可操作判据，例如：
   - L1 简单：单一权威来源（指南条款/明确机制）可直接回答；
   - L2 中等：需 2 篇以上证据交叉或涉及治疗比较/PICO 匹配；
   - L3 困难：需多源（指南+试验/综述）综合、存在证据冲突或需时效性判断。
   量表随 manifest 一起冻结，并在 score.py 增加按难度分层的报告输出。

3. **MIRAGE 只作为 EXTERNAL 10 道的候选题源，不充当正式题**：按许可证筛选 10 道（如 PubMedQA 许可子集优先，因其带 PMID 且最可能可回答），其余 770 道不作为 TEST/STRESS 题目。正式题 TEST 60 道须由人工/教师题 + 指南临床问题抽象（各 ~18 道）+ 少量 LLM 候选（≤12 道，gold 必须人工核验）组成，保证单一来源 ≤ 40%。

4. **gold 治理**：所有正式题的 `gold_source_ids` 必须由人基于**库内证据**建立（evidence.jsonl 的 `pmid:*` / `nct:*` / `guideline:*` 稳定 ID）；外部数据集答案不得直接进入 gold。首批试点：把 PubMedQA/BioASQ 16 题的 PMID 与语料库 7947 个 PMID 求交，能命中的才标注 `answerable=true` 并挂接证据，产出第一份可验证的 gold 样例。

5. **可回答性审计**：对全部候选题做两轮过滤——① 严格主题过滤（剔除宽泛心血管题与 somatostatin/antiphospholipid/phospholipid 误匹配题，或标记 P1）；② 库内证据可支持性过滤（每题至少 1 条可检索 gold 候选）。审计结果写入 `answerable` + 审计记录，不能只靠关键词。

6. **STRESS 题补全**：自建拒答 10 题扩展为 20 道，覆盖四类各 5 题：删除 gold/降 top-k、注入主题相关但不支持的证据、无充分证据/范围外、提示注入/伪造 PMID。拒答题的 `refusal_reason`/`expected_action` 字段设计是好的，继续沿用并补齐其余三类。

7. **盲评与偏差控制记录**：正式题冻结后记录逐题来源、题型、难度、topic 复核结果与 `source_group_id`，保证同源改写共享 ID 且只进同一 split；正式题全量一审、critical 主张/分歧题/压力题双人复核，输出 Cohen's kappa——这些记录是 B5 分层统计与盲评的输入，B2 必须留痕。

8. **评分口径对齐**：当前 score.py 只判 `answer_letter` 对错，与文档两个主终点（`rubric_keypoint_score`、`unsupported_critical_claim_rate`）不对齐。B2 交付的正式题需自带"关键回答点 + 扣分项 + rubric 版本"，使 B5 能按文档口径评分；选择题式 `answer_letter` 判分只保留给 EXTERNAL 基准题。

---

## 与其他部分的配合评估（仅列 B2 相关）

| 配合对象 | 现状 | 风险/建议 |
|---|---|---|
| B1（题集蓝图/协议） | 分支分叉，蓝图不可见 | 先 merge main；按 `question_blueprint.json` 重构，冻结题集版本与逐 split 哈希 |
| A1（开发题/范围） | 未接入 | 与 A1 对齐 DEV 30 题与来源覆盖矩阵，但独立定标 |
| B3/B4（运行器） | 当前用 dev8/formal12 占位 | 正式题 60/20/10/10 冻结后提供路径化题目文件替换占位 |
| B5（指标/盲评） | score.py 仅判字母 | 提供关键回答点/rubric 与难度/题型字段后，B5 才能算主终点与分层统计 |

---

## 结语

测试集分支的筛选思路、manifest 记录方式和拒答题字段设计是可取的起点，但**疾病类型（宽泛心血管/误匹配题越界）、答案可溯源性（764/780 无法从语料回答）、难度分级（字段与量表全部缺失）三个核心问题均不满足 MVP 要求**。按 B2 职责，建议顺序为：① merge main 拿蓝图 → ② 冻结难度量表与题型定义 → ③ 重构 130 题分层、MIRAGE 降级为 EXTERNAL 10 题候选 → ④ 人工 gold 与可回答性审计 → ⑤ STRESS 补全 20 道 → ⑥ 留痕盲评输入。达到 §9 赛道 3 验收清单中属于 B2 的条目后，再与 B1 蓝图逐项核对冻结。
