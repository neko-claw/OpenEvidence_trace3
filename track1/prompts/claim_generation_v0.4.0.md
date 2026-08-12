---
name: claim_generation
version: 0.4.0
output_contract: ClaimGenerationOutput
---

Return JSON that conforms exactly to the supplied ClaimGenerationOutput schema.
Plan atomic claims before any prose answer: each claim must contain one
independently verifiable fact. Use only Evidence IDs and Evidence span IDs from
the request whitelists, and bind every claim to at least one real span. Never
create or copy a PMID, DOI, NCT identifier, guideline identifier, or URL into a
claim. Use UNKNOWN when uncertainty cannot be resolved. Return an empty claims
array when the supplied evidence cannot support an atomic statement. Do not
write a narrative answer; the release gate and finalizer own publication.

## 字段名约定（必须严格遵守）

每条 claim 必须是如下 JSON 对象（字段名不得改写）：

```json
{
  "claim_id": "唯一字符串",
  "text": "原子事实陈述",
  "criticality": "critical | important | context",
  "evidence_ids": ["证据ID，来自白名单"],
  "evidence_span_ids": ["span_id，来自白名单，至少1条"],
  "uncertainty": "LOW | MEDIUM | HIGH | UNKNOWN",
  "population": null,
  "intervention": null,
  "comparator": null,
  "outcome": null
}
```

禁止使用 "claim"、"span_ids" 等替代字段名；禁止编造 evidence_ids / evidence_span_ids
以外的任何 ID；证据不支持任何原子主张时返回空数组 `{"claims": []}`。
