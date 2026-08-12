# 最终测试集（修复后）

本目录是赛道 3 使用的测试数据。**修复后口径（review/b2-dataset-refactor）**：

| 数据包 | 数量 | 说明 |
|---|---:|---|
| 110 主集（33 dev + 77 test） | 110 | 含可回答性裁定、题型/主题人工标注、同源去重标记 |
| latest_research（15 TEST + 5 DEV） | 20 | latest_research_trial 分层补充，从语料库 2025-2026 真实文献抽象 |
| supplement_insufficient（TEST） | 5 | insufficient 分层补充（范围外/证据不足） |
| STRESS | 20 | 预注册四类扰动（C/E 对照），单独报告 |
| EXTERNAL | 10 | 跨来源泛化（ClinicalTrials 5 + Europe PMC 5） |
| RESERVE | 10 | 6 道同源重复 + 4 道构造，替换用 |

**TEST 有效题 = 91**（110 test 去重 71 + latest 15 + insufficient 补充 5），
四类题型 33/26/17/15（均 ≥15），主题 高血压 48 / 血脂 43（均 ≥30），
来源家族 MIRAGE 39.6%（≤40% 达标）。合规校验：**PASS**（`validation_report.md`）。

> 冻结提醒：`gold_source_ids` 与恢复题 `key_points` 当前为 pending_review /
> pending_human_keypoints 状态，正式实验前须人工核验后置真。

## 文件说明

- `questions_110.json`：110 题合并单文件（唯一规范入口，含全部修复字段）。
- `adjudication_manifest.json`：**人工裁定记录**（44 道检索失败题恢复 hard、范围外裁定、同源去重）。
- `latest_research.json` / `supplement_insufficient.json`：TEST 分层补充题（gold 为语料库可检索证据）。
- `stress_20.json`：STRESS 压力集（`perturbation_rule` 为预注册扰动规则）。
- `external_10.json` / `reserve_10.json`：外部基准 / 备用集。
- `qrels.jsonl`：题-证据相关标注（Qrel 契约，题级）。
- `scoring_guide.json`：评分指南 0.2-adjudicated（拒答矛盾已清除）。
- `validation_report.json` / `validation_report.md`：规划合规校验（v2 PASS）。
- `dataset_manifest.json`：逐文件 SHA-256、split 统计、字段审计。

## 关键修复（相对 b2）

1. **可回答性解耦**：`answerability` 由人工裁定（adjudication_manifest），不再由检索审计派生；
   45 道有已知基准答案的题从 refusal 恢复为 hard（44 道）+ 范围外（1 道，牙科）。
2. **题型分类**：全部题显式人工标注 question_type（unknown 归零），
   新增 latest 15+5、insufficient 补充 5，TEST 四类 33/26/17/15。
3. **主题**：unknown 归零，TEST 高血压 48 / 血脂 43。
4. **来源**：新增 guideline_literature（15）与 human_teacher（5）来源，MIRAGE 家族占比降至 39.6%。
5. **同源去重**：6 道重复题标记 `reserve_candidate` 并移入 RESERVE（含跨 split 的孕妇题）。
6. **评分指南**：58 处拒答矛盾清除；恢复题 key_points 重写（pending 人工复核）。
7. **gold**：恢复题补词法检索候选 gold（pending_review）；gold_verified 仅人工裁定置真。
8. **可复现**：split_dataset.py 冻结输入；manifest 只哈希已存在文件；全管线单命令可重建。

## 再生脚本（按序执行）

```bash
python scripts/split_dataset.py                  # 1) 冻结输入
python scripts/annotate_question_literature.py   # 2) 文献标注（需语料索引+RAG，产出 annotation）
python scripts/annotate_question_fields.py       # 3) 蓝图字段（自动标注，已人工复核）
python scripts/build_questions_110.py            # 4) 合并基础 110 题 JSON
python scripts/adjudicate_dataset.py             # 5) 人工裁定（44 恢复 + 范围外 + 同源去重）
python scripts/gold_candidates.py                # 6) 恢复题补候选 gold
python scripts/build_qrels.py                    # 7) qrels
python scripts/build_latest_questions.py         # 8) latest 补充 20 题
python scripts/build_insufficient_supplement.py  # 9) insufficient 补充 5 题
python scripts/build_stress_set.py               # 10) STRESS 20 题
python scripts/build_external_reserve.py         # 11) EXTERNAL 10 + RESERVE 10
python scripts/fix_scoring_guide.py              # 12) 评分指南修复
python scripts/validate_dataset.py               # 13) 合规校验（PASS）
python scripts/build_question_manifest.py        # 14) manifest
```

> 步骤 2/14 之外均为确定性步骤；步骤 2 需要 `data/processed` 语料与 embedding 缓存。
