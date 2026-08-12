# gold 医学核验报告（LLM 辅助首轮）

- 可回答题：84；含 gold：84
- 状态分布：{'llm_assisted_uncertain': 11, 'llm_assisted_unsupported': 56, 'no_answer_text': 3, 'llm_assisted_supported': 14}
- **需人工终审**：70 题（['LATEST-16', 'LATEST-17', 'LATEST-18', 'LATEST-19', 'LATEST-20', '5c895cf0f9c2ba6b28000001', 'LATEST-25', 'LATEST-26', 'SUP-REF-D02', '0718', '0813', '0836', '0cd0e1c4-aabe-4ac3-ae2b-83b0633cb376', '0e7917ea-310b-4477-9897-f4901f728448', '1ea823e8-1b70-4820-96e1-c46d5fd23885', '23d04e70-f243-4c16-a7c4-827051a5b62b', '297ab88f-0697-406b-8994-332269314289', '0862', '623a24d6f0baec9a1b000002', '9c7e163e-d22f-43d9-8c77-fb036bc0b064']...）
- 说明：llm_assisted_* 仅表示 LLM 对齐检查结果，**不是**医学人工核验；
  由医学评审人在 gold_review.jsonl 填 reviewer_verdict 后执行 `python scripts/verify_gold.py --finalize` 升级为 human_verified。
