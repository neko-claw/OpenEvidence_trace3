# B3 Review 终审（commit c2c1a7b · 合入前最终核查）

> 复核范围：`5786f57`（chat_json 回归修复 + E 扰动标签 + max_per_doc 分块键）+ `c2c1a7b`（离线 fixture 重新生成）
> 新事实：**main 已推送远端**（`origin/main = 2c428e2`，含 B1 全部交付物），与上一轮"B1 从未上远端"的定性不同。
> 验证方式：本地实跑 38 测试全绿；`--offline --emb-backend fallback` 端到端 STRESS×{C,E} → 4 runs 全 ok → consistency 审计 0 error；逐文件 diff 核对修复项；检查合并冲突面。

---

## 总评：**同意合入**（B3 → main）

上一轮的两个硬阻塞（P0 回归 `LLMClient.chat_json` 丢失、fixture 过期）已全部修复并有测试佐证，端到端链路与审计框架实测通过。剩余不足均为**已明确归属的后续任务**（B4 的 E 多扰动、B3/B1 契约对齐、A4 的 K1 调参），不构成合入阻塞。按上一轮既定计划（"合入本 PR → 随后 B1 推送 → B3/B4 对齐契约"）执行，本轮即 B1 推送后的合入时点。

---

## ✅ 已核实修复到位（上轮阻塞全部关闭）

| 上轮项 | 修复 | 本轮验证 |
|---|---|---|
| **P0 回归：LLMClient.chat_json 丢失** | `chat_json` 移回 `LLMClient`；`OfflineLLM.chat_json` 单独实现（返回固定 JSON） | 读码确认缩进正确；`tests/test_b3_runners.py:37` 新增契约测试 `hasattr(LLMClient,'chat_json')` + OfflineLLM 返回可解析 JSON；38 测试全绿 ✓ |
| **fixture 过期** | `tests/fixtures/runs_offline_smoke.jsonl` 重新生成 | `config_hash=3b4e9e93c62b-5786f57` = sha1(config.yaml)[:12] + 父提交短哈希（c2c1a7b 仅改动 fixture 本身，config 未变，功能一致）✓ |
| **E 标签与执行不一致** | tool_trace 拆分为 `perturbation`（题目声明）+ `perturbation_executed`（实际执行） | 端到端实测：s01(gold_removed) 落盘 `perturbation=gold_removed, perturbation_executed=topk_halved`——**声明与执行分离，审计可同时读到两者，不再误导** ✓ |
| **max_per_doc 对分块无效** | `mmr._doc_key` 剥离 `:chunk:`/`:p`/`-p` 后缀，回退 pmid/doi/nct | 读码确认：epmc:PMCxx:chunk:001 与同篇其他 chunk 共享 key，受 max_per_doc=2 约束 ✓ |
| E 派生基准（上上轮） | 保持 `derived_from=B_baseline_rerank_false` + top-k 减半 | 端到端审计 E 条件 0 error ✓ |

**端到端实测**（`python -m evaluation.experiment --questions stress --conditions C E --offline --limit 2 --emb-backend fallback`）：
- 4 runs（s01/s02 × C/E）全部 `status=ok`，claims 每条 3 条、candidate_ids 落盘、成本/cache 留痕；
- `consistency.audit_runs` → **ERROR 0 / WARN 2**（两条 warn 为 `e_split`：审计时未传 `--questions stress` 导致 split=未知，属调用方式问题，非代码缺陷）。

---

## 🟠 合并冲突面（3 个文件，需手工合并，已评估均为可解）

B3 从 `1f15af9` 分出，与 main（B1）在 3 个文件上双侧修改：

| 文件 | 冲突原因 | 合并方案 |
|---|---|---|
| `README.md` | 两侧均从零新增、内容完全不同（B1=数据集采集文档，B3=赛道3运行文档） | 保留两篇，建议将 B3 运行文档作为主 README，B1 采集文档移入 `docs/` 或作为二级章节 |
| `pyproject.toml` | main 加 `test` 可选依赖；B3 重写项目元数据（version/requires-python/依赖清单/packages.find） | 以 B3 版为主，补入 main 的 `test = ["pytest>=7.0"]`；注意 B3 把 `requires-python` 提到 `>=3.10`，与 `core/` 的类型注解（`|` 语法）一致，可接受 |
| `.gitignore` | 两侧均新增 `data/experiments/`、图片忽略规则 | 取并集，去重即可 |

无代码逻辑冲突，合入后需补跑全部测试。

---

## 🟡 剩余不足（合入后登记为后续任务，不阻塞本次）

1. **E 五类扰动只实现 1 类（B4 主责）**：`stress_sample.jsonl` 声明了 gold_removed / topk_reduced / inject_irrelevant_evidence / out_of_scope / prompt_injection，但 runner 对所有题执行 `topk_halved`。本轮已通过 `perturbation_executed` 诚实标注，**杜绝了"读到假标签"的问题**；但 §6.3 压力集的多类扰动设计仍待 B4 按 `e_perturbation_rules.json`（现在已在 main 远端，可见可读）扩展实现。
2. **契约双轨（B3/B1 对齐任务，现在具备条件）**：main 已含 B1 的 `evaluation/schemas/run.schema.json`、`score.schema.json`、`e_perturbation_rules.json`、`experiment_protocol.md`、fixtures；B3 用 `core/dataclasses.py` 定义同名契约。合入后需做一次对齐 PR：dataclass `to_dict` 输出与 JSON Schema 校验互认（建议以 B1 schema 为权威，B3 提供映射层），并让 E 实现读取 `e_perturbation_rules.json`。
3. **claims 口径仍为简化版**：`entailment_score/population_match/time_match` 字段已存在但恒为 null，`evidence_ids` 存 `[E1]` 编号而非真实证据 ID、criticality 恒为 important。主终点"可算"但 `claim_support_rate` 本质是引用编号存在性；**正式实验报告中必须披露该口径**，或与 A5 对齐统一结构化输出。
4. **K1 分层占位（A4 项）**：`k1_rerank: null`，特征重排作用于全量 RRF 候选；§4.3.2 的 K1∈{10,20,30,50} 网格调参未落地。
5. **小瑕疵**：
   - `--conditions C,E`（逗号分隔）会被当作未知条件 `"C,E"` 并触发 `UnboundLocalError` 内部崩溃，而非清晰报错——建议 `resolve_conditions` 对未知条件提前抛 `ValueError` 并提示"条件间用空格分隔"；
   - fixture 的 `config_hash` 后缀指向父提交 `5786f57` 而非当前 HEAD（c2c1a7b 只改 fixture，功能一致，纯观感问题；下次重生成 fixture 时用当前 HEAD 即可）；
   - `--conditions` 默认 `[A,B,C,D]` 不含 E，STRESS 题需显式传 E（README 已注明，符合设计）。

---

## 合入后待办清单（建议登记到 PR 评论 / issue）

1. **对齐 PR（B3/B1 契约）**：dataclass ↔ JSON Schema 映射 + 校验测试；E 实现读取 `e_perturbation_rules.json`（现在文件已上远端）。
2. **B4：E 多扰动实现**（gold 删除、注入不支持证据、prompt injection 处理），并补充对应测试。
3. **B5：评分链路接真实 LLM**（验证 `LLMClient.chat_json` 在 judge 中的实际使用），claims 口径在报告中披露。
4. **A4：K1 分层调参** + 特征权重在正式题上冻结。
5. **仓库运维**：建议后续多分支协作使用 `git worktree` 或独立 clone，避免同一工作目录被并发 checkout 覆盖（上轮已发生一次）。

---

## 合入决策

**建议合并（merge B3 → main），并立即执行**：
- 上轮两个硬阻塞已闭环（chat_json 回归修复 + 契约测试；fixture 重新生成）；
- 38 测试全绿，离线端到端 + 审计实测通过；
- 3 个文件冲突均为文档/依赖声明层面，无逻辑冲突，手工合并后重跑测试即可；
- 剩余不足（E 多扰动、契约对齐、claims 口径、K1）按上述待办在合入后推进，其中契约对齐与 E 扩展现在才具备前置条件（B1 文件已上远端）。

若不合并的代价：B3 的 A/A2/B 运行器 + 审计框架继续游离在主分支之外，B4/B5 无法基于合入后的仓库联调 C/D/E 与评分，契约对齐也无从谈起——因此**合入是推进后续工作的前提，而非可选项**。
