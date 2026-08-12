# B4 接口约定

> 版本：v0.1
> 用途：支持 B4 在赛道一尚未完成时先用 fixture/mock 开发，后续无痛替换真实系统。

## 1. 接口原则

B4 只依赖稳定输入输出，不依赖赛道一的内部目录和实现细节。

所有结果必须包含：

- `question_id`；
- `condition`；
- `dataset_version`；
- `corpus_version`；
- `index_version`；
- `config_hash`；
- `status`；
- `error`。

## 2. RetrievalResult

```python
class RetrievalResult:
    question_id: str
    query: str
    query_rewrites: list[str]
    index_version: str
    bm25_candidates: list[dict]
    vector_candidates: list[dict]
    rrf_candidates: list[dict]
    rerank_candidates: list[dict]
    final_evidence: list[dict]
    feature_scores: list[dict]
    latency_ms: int
    errors: list[dict]
```

每个候选证据至少包含：

```text
evidence_id
rank
score
source_type
record_kind
title
url
evidence_level
published_at
content_hash
```

## 3. FullSystemResult

```python
class FullSystemResult:
    question_id: str
    system_version: str
    skill_versions: dict
    mcp_tools_called: list[str]
    agent_plan: dict
    tool_trace: list[dict]
    retrieved_evidence: list[dict]
    claims: list[dict]
    citations: list[dict]
    verification_result: dict
    answer: str | None
    refusal_reason: str | None
    latency_ms: int
    errors: list[dict]
```

## 4. B4 运行入口

```python
run_condition(
    question: dict,
    condition: str,
    config: dict,
) -> dict
```

条件值固定为：

```text
C
D
E
```

B3 的运行器可以复用同一入口，但 A/B 的实现由 B3 负责。

## 5. 适配器

### FixtureRetriever

```python
search(question: dict, config: dict) -> RetrievalResult
```

用于无网络开发和单元测试。输入题目 ID，返回预设候选集。

### ReferenceRetriever

```python
ReferenceRetriever(
    evidence_path="data/processed/evidence.jsonl",
    index_version="reference-bm25-v0.1",
)
```

读取完整 Evidence 快照，建立本地 BM25 索引。当前版本是单路 BM25 reference：
`vector_candidates` 为空，`rrf_candidates` 和 `rerank_candidates` 保留统一字段但标记为单路 BM25 结果。
它用于在赛道一尚未完成时验证真实语料规模下的运行和诊断流程，不代表最终的 BM25+向量+RRF 系统。

### HybridReferenceRetriever

```python
HybridReferenceRetriever(
    evidence_path="data/processed/evidence.jsonl",
    config_path="config.yaml",
    embedding_backend="local",
    use_rerank=True,
)
```

复用仓库现有的 `EvidenceStore`，按固定配置执行：

```text
BM25 Top-50 + Vector Top-50 → RRF → feature rerank → MMR
```

Adapter 将各阶段转换为统一的 `RetrievalResult`，并保存 `bm25_candidates`、
`vector_candidates`、`rrf_candidates`、`rerank_candidates` 和 `final_evidence`。
`embedding_backend=fallback` 只用于无模型环境下的工程链路测试，不能作为正式向量效果结论。

### Track1RetrieverAdapter

```python
search(question: dict, config: dict) -> RetrievalResult
rerank(question: dict, candidates: list[dict], config: dict) -> RetrievalResult
```

用于接入赛道一 A4 的真实检索系统。

### MockFullSystem

```python
run(question: dict, config: dict) -> FullSystemResult
```

用于赛道一 A5 尚未完成时验证 D 的日志和运行流程。

### Track1FullSystemAdapter

```python
run(question: dict, config: dict) -> FullSystemResult
```

用于最终接入赛道一的完整系统。

## 6. E 劣化接口

```python
apply_stress(
    candidates: list[dict],
    qrel: dict,
    rule: str,
    seed: int,
) -> tuple[list[dict], dict]
```

返回：

1. 劣化后的候选集；
2. `StressManifest`，记录规则、seed、删除项和注入项。

主规则：`drop_gold_v1`。

## 7. 错误状态

统一使用：

```text
success
cached
invalid_output
timeout
provider_error
retrieval_error
verification_error
not_applicable
failed
```

失败不得被静默丢弃。批量运行必须保留对应的 Run 记录。

## 8. 本地运行

使用 fixture：

```powershell
python -m evaluation.run_conditions --retriever fixture --condition C,D,E --split ALL
```

使用完整 Evidence 快照：

```powershell
python -m evaluation.run_conditions `
  --retriever reference `
  --evidence data/processed/evidence.jsonl `
  --condition C,D,E `
  --split ALL
```

使用本地向量模型进行混合检索：

```powershell
python -m evaluation.run_conditions `
  --retriever hybrid-rerank `
  --embedding-backend local `
  --evidence data/processed/evidence.jsonl `
  --condition C,D,E `
  --split ALL
```
