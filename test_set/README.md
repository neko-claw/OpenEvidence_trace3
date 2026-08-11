# 最终测试集（110 题）

本目录是赛道 3 使用的测试数据：**110 道唯一题 = 100 道公开基准题 + 10 道原始拒答题**。

## 文件说明

- `questions_110.json`：110 题的合并单文件（推荐入口），包含划分、分类和文献标注。
- `questions_test.json`：100 道高血压/血脂相关公开基准题（DeepSeek 筛选、难度归一化和分档）。
- `refusal_split.json`：10 道原始拒答/超范围题（REF-001～REF-010）。
- `question_rag_split.jsonl`：110 题开发集/测试集划分（3:7）。
- `question_rag_split_summary.json`：划分汇总。
- `question_literature_annotation.jsonl`：110 题 RAG 文献标注。
- `question_literature_summary.json`：文献标注汇总。
- `oracle_support_annotation.jsonl`：hard 题 oracle 检索支撑判定。

## 划分与分类

开发集 : 测试集 = **33 : 77（3:7）**，每类按比例分层，随机种子 42，可复现。

| 类别 | 含义 | 总数 | 开发集 | 测试集 |
|---|---|---:|---:|---:|
| easy | 基础 RAG 直接通过（审计 pass） | 39 | 12 | 27 |
| hard | 需要优化检索才能命中（corpus_only，或精选候选可进前 5 但仍 fail，含人工确认 5 道） | 12 | 3 | 9 |
| refusal | 检索不到支撑、应拒答（fail 无候选 + 原始拒答 + 人工裁定 4 道） | 59 | 18 | 41 |

## 字段说明

`questions_110.json` 每题包含：

- 基础字段：`id`、`source`、`question`、`options`、`answer`、`answer_text`
- 难度：`difficulty_raw`、`difficulty_norm1`、`difficulty`（0～100）、`difficulty_level`（1～4）
- 划分与分类：`split`（dev/test）、`rag_category`（easy/hard/refusal）、`audit_status`（pass/corpus_only/fail）
- 拒答字段（REF-* 题）：`answerable`、`expected_action`、`refusal_reason`、`note`
- 文献标注：
  - `literature_used`：RAG 检索命中的文章级文献（PMID/PMCID/EPMC/指南/维基）
  - `supported_evidence`：judge 判定支撑的证据（含维基、试验等）
  - `supported_literature`：支撑证据中的文献部分（维基百科可接受）
  - `candidate_literature`：hard 题待优化引入的候选文献
  - `gold_literature`：最终可接受文献（= supported + 题面 PMID，已确认）
  - `gold_verified`：是否已确认（true/false）
  - `evidence_retrieved`：RAG 原始命中的全部证据 ID

规则：easy/hard 的 `supported_literature` 非空；refusal 的 supported/gold 一律为 `null`。

## 再生脚本

```bash
.conda/Scripts/python.exe scripts/build_dev_test_split.py          # 划分
.conda/Scripts/python.exe scripts/extract_oracle_support.py        # hard 题 oracle 支撑
.conda/Scripts/python.exe scripts/annotate_question_literature.py  # 文献标注
.conda/Scripts/python.exe scripts/build_questions_110.py           # 合并 110 题 JSON
```
