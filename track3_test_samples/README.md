# 赛道 3 测试样例（从 MIRAGE 筛选）

本文件夹从 `MIRAGE/benchmark.json` 中按主题关键词筛出与高血压、血脂相关的题目（已剔除仅命中心血管关键词的题目），供赛道 3 外部评测使用。

- MIRAGE 题共 **780** 道（BioASQ 5、MedMCQA 44、MedQA 600、MMLU 120、PubMedQA 11）
- 自建拒答/超范围题共 **10** 道

## 仓库保留文件

数据本体体积较大，不入库；Git 仓库内只保留以下文件：

- `README.md`：本说明
- `manifest.json`：筛选关键词、各子集数量与生成说明
- `score.py`：赛道 3 评分脚本

数据文件（`*_related.json`、`refusal_out_of_scope_questions.json`）需按 `manifest.json` 中的关键词从 `MIRAGE/benchmark.json` 重新筛选生成；当前仓库未附带生成脚本。

## 数据文件说明（本地生成后）

- `pubmedqa_related.json`：PubMedQA* 相关题（文献型，yes/no/maybe，附 PMID）
- `bioasq_related.json`：BioASQ-Y/N 相关题（文献型，yes/no，附 PMID）
- `medqa_related.json`：MedQA-US 相关题（USMLE 四选一）
- `medmcqa_related.json`：MedMCQA 相关题（四选一）
- `mmlu_related.json`：MMLU 医学子集相关题（四选一）
- `all_related.json`：以上 5 个子集合并（780 题）
- `refusal_out_of_scope_questions.json`：自建拒答/超范围题（10 道）

## 字段说明

MIRAGE 题目每条记录包含：`id`（MIRAGE 原始 key）、`source`、`question`、`options`、`answer`、`answer_text`、`pmid`、`topic_tags`（hypertension/lipid/cardiovascular）、`matched_keywords`、`strict_topic`。

拒答题每条记录包含：`id`（`REF-xxx`）、`question`、`topic_tags`、`answerable`、`refusal_reason`、`expected_action`、`note`。

## 评分

```bash
python3 track3_test_samples/score.py --predictions predictions.jsonl [--output report.json]
python3 track3_test_samples/score.py --template
```

预测 JSONL 每条记录字段：

- `id`：题目 id（MIRAGE 原始 key 或 `REF-xxx`）
- `source`：例如 `MIRAGE/pubmedqa`、`MIRAGE/bioasq`、`self-built/refusal`
- `condition`：实验条件，如 A/B/A2/C/D/E
- `decision`：`PASS` / `WARN` / `REFUSE` / `ABSTAIN`
- `answer_letter`：选择题答案字母，如 A
- `answer_text` / `raw_answer`：可选，用于解析兜底

## 注意事项

- `strict_topic=true` 表示命中高血压/血脂严格关键词；`false` 仅命中心血管等宽泛词。
- 子串匹配会误伤个别词（如 `statin` 命中 somatostatin、`lipid` 命中 antiphospholipid/phospholipid），使用前请人工复核。
- 答案来自 MIRAGE 原数据，未经本项目人工核验。

## Git 说明

- 测试集数据本体（`*_related.json`、`refusal_out_of_scope_questions.json`）不入库；`README.md`、`manifest.json`、`score.py` 会保留。
- `MIRAGE` 本体也不在 OpenEvidence_trace3 仓库内，需要时单独从 [MIRAGE](https://github.com/Teddy-XiongGZ/MIRAGE) 获取 `benchmark.json`，再按 `manifest.json` 的关键词重新筛选生成。
