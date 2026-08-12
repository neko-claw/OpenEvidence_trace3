# 题集规划合规校验报告（v3，真实运行口径）

> 校验对象：test_set/questions.jsonl（33 DEV + 77 TEST，运行时唯一主集）+ test_set/stress_20.jsonl
> v2 曾把 latest_research/supplement_insufficient 计入主集（91 道）导致口径不一致；v3 只按运行时入口判定。

## 结论

- **PASS**：口径=运行时唯一主集 questions.jsonl（77 TEST + 33 DEV）+ stress_20.jsonl；gold 仍为 pending_review，冻结前须医学人工核验；TEST 题型当前 19/19/19/20、主题 39/38（高于规划下限 15/30）

## 0. 数据包

| 包 | 数量 |
|---|---:|
| DEV | 33 |
| TEST（运行时主集） | 77 |
| STRESS | 20 |
| 说明 | 运行时唯一主集 = questions.jsonl（DEV+TEST）；补充包（latest/supp/external/reserve）仅留档，不参与主集配额 |

## 1. TEST 四类题型（下限 15，目标 19/19/19/20）

| 题型 | 当前 | 下限 | 目标 |
|---|---:|---:|---:|
| stable_knowledge_mechanism | 19 | 15 | 19 |
| guideline_treatment | 19 | 15 | 19 |
| latest_research_trial | 19 | 15 | 19 |
| insufficient_conflict_out_of_scope | 20 | 15 | 19 |
| unknown_or_missing | 0 | - | 0 |

## 2. TEST 主题（下限 30，目标 39/38）

| 主题 | 当前 | 下限 | 目标 |
|---|---:|---:|---:|
| hypertension | 39 | 30 | 39 |
| dyslipidemia | 38 | 30 | 38 |

## 3. 来源家族占比（<=40%）

| 家族 | 数量 | 占比 | 达标 |
|---|---:|---:|---|
| MIRAGE_family | 26 | 33.8% | ✅ |
| GUIDELINE_LITERATURE_ABSTRACT | 15 | 19.5% | ✅ |
| MedQA_USMLE_family | 9 | 11.7% | ✅ |
| ORIGINAL_REFUSAL | 8 | 10.4% | ✅ |
| HUMAN_TEACHER_REFUSAL | 5 | 6.5% | ✅ |
| HUMAN_TEACHER | 5 | 6.5% | ✅ |
| MedExpQA_family | 5 | 6.5% | ✅ |
| LLM_CANDIDATE | 4 | 5.2% | ✅ |

## 4. 选项覆盖（P0-1）

- TEST 有选项题 40/77；有答案但缺选项：无

## 5. gold 核验状态（P0-4）

- 可回答题 59；gold_verified=True 的题：无（诚实标注 pending_review）；缺 gold：无

## 6. gold 与语料库一致性

- 缺失 0 条（全部在库）

## 7. 评分指南（P0-3）

- 唯一条目 164；重复 ID：无；空评分点：无；无指南题：无

## 8. DEV/TEST 隔离

- 跨 split 重复：无

## 9. STRESS 预注册（P0-7）

- 共 20 道，扰动分布：{'retrieval_damage': 5, 'injected_unsupported': 5, 'no_evidence_outscope': 5, 'malicious_injection_fake_id': 5}；缺规则：无

## 10. 动作/可回答性一致性

- 不一致：无

## 失败清单

- （无）

