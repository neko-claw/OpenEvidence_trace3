# evaluation/ —— 赛道3 对比评估（B1 交付）

> 对应实施规划 §7.2 B1 实验负责人：假设与条件协议、公平性控制、题集蓝图、版本冻结、Run/Score schema。
> 本目录在开工前冻结为 **v0.1.0**；正式题文本/gold/rubric 由 B2 冻结，B1 不参与答案撰写。

## 交付清单

| 文件 | 内容 | 对应协议章节 |
|---|---|---|
| `../docs/experiment_protocol.md` | 实验协议（A/A2/B/C/D/E 定义、7 条公平性铁律、预注册、版本冻结、验收清单） | §1-§8 |
| `blueprints/question_blueprint.json` | 130 题蓝图（DEV30/TEST60/STRESS20/EXTERNAL10/RESERVE10、分层、来源分布、隔离规则） | §3 |
| `schemas/run.schema.json` | Run 记录契约（JSON Schema draft-07） | §6 |
| `schemas/score.schema.json` | Score 评分契约（JSON Schema draft-07） | §6 |
| `experiment_config.json` | 配置清单（模型、K 参数、rerank 权重、门禁阈值、预算；v0.1 起始值） | §5 |
| `preregistration/e_perturbation_rules.json` | E 劣化预注册规则（20 压力题 × 4 类） | §4.4 |
| `make_fixtures.py` | 从 `data/processed/evidence.db` 确定性生成离线 fixture | 开工门槛 |

## 离线 fixture（供 B3 开发实验框架，替换正式接口前使用）

- `../data/processed/fixtures/evidence_fixture.jsonl`：20 条 Evidence（4 来源、7 证据等级、双主题）
- `../data/processed/fixtures/sample_questions.jsonl`：5 DEV + 5 STRESS 样例题（**蓝图样例，非正式题**）

重建 fixture：
```bash
python evaluation/make_fixtures.py   # 从 evidence.db 确定性抽样
```

## 与 B1 验收对应关系

- [x] 实验协议、蓝图、配置清单、Run/Score schema 已冻结（v0.1.0）
- [x] 预注册主要终点（rubric_keypoint_score / unsupported_critical_claim_rate）、E 劣化规则、统计方法已写入
- [x] 20 条 Evidence fixture + 10 条样例题可用
- [x] D 条件结论仅解释为“组件包整体增量”（协议 §1 H3 / §7）
- [x] 公平性控制 7 条铁律（协议 §2）
