# B3 Review 复核（commit 9ea51ea · 响应修复）

> 复核范围：`9ea51ea fix: 响应 B3 Review - claims留痕 / E派生基准 / 离线回放 / 候选集落盘`
> 验证方式：独立 worktree（/tmp/oe_b3_check）实跑 36 测试全绿；离线 CLI 端到端（STRESS × C/E → 6 runs → consistency audit 0 error/0 warn）；`hasattr` 断言 chat_json；API 核验 B1 提交是否在远端。

## 复核结论

**修复提交对 review 的响应是认真且大体到位的：P0-2（claims 留痕）、P0-3（E 派生基准 + STRESS 入口）、P0-4（离线回放）均已落实并有测试佐证，5 项次要问题（candidate_ids 落盘、严格同源核验、q_freshness、MMR 上限配置化、attempt_count）也全部兑现。** 但引入 **1 个新的 P0 回归（LLMClient.chat_json 丢失，会直接打断 B5 评分）**，另有 P0-1（B1 交付物未上远端）需要以新的事实重新定性。

---

## ✅ 已核实修复到位

| Review 项 | 修复 | 验证 |
|---|---|---|
| P0-2 claims 留痕 | `run.claims` 由 split_claims 填充并绑定 [E#]/[S#] | 离线 run 每条 3 claims、evidence_ids=['E1'] 落盘 ✓ |
| P0-3 E 派生基准 | E 改为 B 基线初检（use_rerank=False）派生，tool_trace 含 `derived_from=B_baseline_rerank_false`/`perturbation=topk_halved` | 端到端验证 ✓ |
| P0-3 STRESS 入口 | `--questions stress` 别名 + stress_sample.jsonl（5 道，含 perturbation 标签）；config 修正 E 为 P0（仅 STRESS） | CLI 实测 ✓ |
| P0-4 离线回放 | OfflineLLM + `--offline` + 10-run fixture + 5 项新测试 | 36 测试全绿，STRESS×C/E 离线跑通，审计 0/0/0 ✓ |
| candidate_ids 落盘 | Run 新增字段，RRF 候选 ≤100 | 实测 candidates=100 ✓ |
| 严格同源核验 | C 证据必须 ⊆ B.candidate_ids（error 级），旧 run 退化为交集比例 | 审计 PASS ✓ |
| q_freshness | 传入 Question.freshness | 代码核实 ✓ |
| MMR 上限配置化 | max_per_source=4 / max_per_doc=2 进 config | ✓ |
| K1 分层 | k1_rerank 配置占位（null 默认不截断） | ✓（仍是占位，见下） |
| attempt_count | 异常路径改用 `llm.last_attempts` | ✓ |
| --questions 任意路径 | 别名或 .jsonl 路径均可 | ✓ |
| README 367→11630 | 已修正 | ✓ |

---

## 🔴 新回归（P0，必须修复后才能合入）

### `LLMClient.chat_json` 丢失 → B5 评分必然崩溃

`core/llm.py` 中新增 `OfflineLLM` 时，**原属于 `LLMClient` 的 `chat_json` 方法被错误地留在了 `OfflineLLM` 类的缩进内**，且第二个定义覆盖了 OfflineLLM 自己的 `chat_json`。实测：

```python
hasattr(LLMClient, 'chat_json')   # -> False  ← 方法丢了
hasattr(OfflineLLM, 'chat_json')  # -> True
```

后果：
- `evaluation/judge.py:42` `llm.chat_json(msgs, ...)` 在真实 LLM 评分时必然 `AttributeError`，**B5 的评分/盲评流程整个不可用**；
- `OfflineLLM.chat_json` 现在拿着 LLMClient 的 JSON 解析实现：对离线 Markdown 回答 `json.loads` 失败、正则 `\{.*\}` 找不到花括号 → 静默返回 `{}`，离线评分会是全 0 的"假通过"；
- 36 个测试全绿具有误导性：**没有任何测试覆盖 `LLMClient.chat_json`**（judge 不在测试范围内）。

**修复建议**：把原 `chat_json` 从 `OfflineLLM` 内移回 `LLMClient`（类缩进）；`OfflineLLM` 单独实现 `chat_json`（可返回固定结构的 JSON 字典）。并补 1 个冒烟测试：`LLMClient` 存在 `chat_json` 且 `OfflineLLM.chat_json` 返回可解析 JSON。

---

## 🟠 P0-1 重新定性：B1 交付物从未推送到远端

本次核实推翻了我上一轮 review 的表述（"B3 缺 B1 交付物需 merge main"）。事实是：

- 远端 `origin/main` 停在 `1f15af9`；B1 的提交（`bfc53f6`/`dbd004a`/`1b1120e`）对 GitHub API 返回 **422（远端不存在）**——它们**只存在于本地 main，从未推送**；
- 因此 B3（9ea51ea）相对远端 main 是干净的，PR 可合并；"分叉"问题实际是 **B1 的 schema/预注册规则/fixture 从未上远端**。

**遗留协作待办**（需 B1/仓库管理员处理，非 B3 过错）：
1. 把本地 main 上的 B1 交付物（`docs/experiment_protocol.md`、`evaluation/schemas/*.json`、`evaluation/preregistration/e_perturbation_rules.json`、`make_fixtures.py`、fixtures、`fulltext_service.py`）推送到远端（建议单独 PR）；
2. 之后 B3/B4 再把 Run/Score 契约与 B1 的 JSON Schema 对齐（当前仍是 dataclass 与 schema 双轨）；
3. E 的完整扰动实现依赖 `e_perturbation_rules.json`，该文件上远端前，B4 无法按预注册规则扩展。

---

## 🟡 其余不足（可合入后由 B4/B5 跟进）

1. **E 的 5 类扰动只实现 1 类，且标签与执行不一致**：`stress_sample.jsonl` 每题声明了 perturbation（gold_removed / topk_reduced / inject_irrelevant_evidence / out_of_scope / prompt_injection），但 runner 对**所有题都执行 `topk_halved`**（tool_trace 硬编码 `perturbation=topk_halved`）。例如 s01 声明 `gold_removed` 实际跑的是 top-k 减半——**审计会读到一个与题目声明不符的扰动标签**。B4 接手时应：按题读取 rubric.perturbation（或 e_perturbation_rules.json）选择对应派生逻辑；至少补 gold 删除与注入不支持证据两类，否则 §6.3 压力集四类扰动不成立。
2. **claims 仍是"列表项正则拆分"的简化版**：evidence_ids 存 "E1"/"S1" 编号字符串而非真实证据 ID、criticality 恒为 important、无 entailment/population/time 字段——主终点"可算"了，但 `claim_support_rate` 本质是"引用编号存在性"而非语义支持（§6.2 要求统一 claims 输出 schema）。P0 可接受，**必须在报告中披露口径**，或与 A5 对齐结构化输出。
3. **离线 fixture 过期 + 内容空洞**：`tests/fixtures/runs_offline_smoke.jsonl` 的 `config_hash=3b4e9e93c62b-22021fc` 嵌的是**旧 commit 22021fc**（修复提交前生成、提交后未重新生成）；且首条 run 的 `retrieved_evidence[0].text` 为空（pmid:39210715 无 abstract）。建议：提交前用当前 HEAD 重新生成 fixture，保证 config_hash/commit/corpus_version 与仓库一致；空文本证据也提示离线链路"只验链路、不验内容质量"。
4. **max_per_doc 对分块证据无效**：`mmr.py` 的 `_doc_key = pmid or doi or nct_id or id`，分块证据（`epmc:PMCxxxx:chunk:001`、指南分块）无 pmid/doi/nct，key 回落为 chunk id → **同篇文献的多个 chunk 不会被 max_per_doc=2 限制**（每 chunk 独立计数）。建议 key 去掉 chunk/页码后缀（A4/B4 范围）。
5. **K1 分层仍是占位**：`k1_rerank: null`，特征重排仍作用于全部 RRF 候选（最多 100 条）。P0 成本可接受，但 §4.3.2 的 K1∈{10,20,30,50} 网格调参尚未落地（A4 项）。
6. **工作目录并发使用提醒（仓库运维）**：本次复核期间发现工作目录被另一进程切换分支（reflog 显示 13:32 有 B2 相关的 cherry-pick），我的 checkout 被切回。**同一工作目录多分支并行操作会互相覆盖工作树**，建议各成员/各分支使用独立 clone 或 `git worktree`（我本次复核全部在 /tmp/oe_b3_check 完成，未触碰主工作目录）。

---

## 合入建议

**当前 9ea51ea 不建议直接合入**：`LLMClient.chat_json` 回归会在 B5 评分阶段暴露，且会以"测试全绿"误导后续判断。建议：

1. 修复 chat_json 回归 + 补 1 个契约测试（预计 10 分钟）；
2. 用当前 HEAD 重新生成 offline smoke fixture；
3. 合入本 PR（B3 的 A/A2/B 运行器 + 审计框架质量达标）；
4. 随后由 B1 推送实验协议/schema/预注册规则，B3/B4 对齐契约并实现 E 的多扰动版本（P0-1/P0-3 完整闭环）。

其余简化项（claims 口径、max_per_doc、K1）作为 B4/B5/A4 的后续任务登记，不必阻塞本次合入。
