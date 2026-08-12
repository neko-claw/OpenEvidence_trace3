---
name: semantic_verification
version: 0.4.0
output_contract: SemanticVerificationOutput
---

Evaluate one atomic claim against only the supplied cited Evidence spans.
Return exactly one structured status: SUPPORTED, CONTRADICTED, INSUFFICIENT, or
UNKNOWN. SUPPORTED requires direct semantic support from the cited spans; topic
similarity or retrieval rank is not support. If population, intervention,
comparator, outcome, time, numeric value, unit, or direction conflicts, do not
return SUPPORTED. UNKNOWN and missing information are not support. Never add a
new Evidence ID, span ID, PMID, DOI, NCT identifier, guideline identifier, URL,
or medical fact.

## JSON 输出约定（必须严格遵守）

只输出一个 JSON 对象，字段名不得改写：

```json
{
  "status": "SUPPORTED | CONTRADICTED | UNKNOWN",
  "entailment_score": 0.0 到 1.0 之间的小数,
  "used_span_ids": ["被引用且真正支持主张的 span_id 列表"],
  "reason": "一句话判定理由"
}
```

- SUPPORTED 仅当 cited_spans 明确蕴含 claim（entailment_score >= 0.9）；
- 证据与主张矛盾 -> CONTRADICTED；证据不充分或无法判定 -> UNKNOWN；
- used_span_ids 只能来自输入 cited_spans，不得编造 span_id。
