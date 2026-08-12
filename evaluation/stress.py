"""E 劣化（预注册规则集）

对应 ``evaluation/preregistration/e_perturbation_rules.json`` 的 4 类压力
（STRESS 20 题 × 每类 5 题）与实施规划 §6.3：

- ``drop_all_gold_v1``        : 删除候选集中 gold_source_ids 对应的全部证据（其余保持原样）
- ``drop_gold_v1``            : 仅删除排名最高的一条 gold（早期骨架，保留兼容）
- ``topk_reduced``            : K2 从 8 降到 3，且在降序候选中去掉 gold 后再截断
- ``inject_unsupporting_v1``  : 注入 2-4 条“主题相关但不支持”证据到上下文（近似实现，见函数 docstring）
- ``unanswerable_malicious``  : 不改候选集，压力由题面内容承载（范围外/提示注入/伪造 ID）

设计要点（响应 B4 Review）：

1. 规则在“检索阶段候选集”（BM25+Vector+RRF 融合，B/C 同源）上执行，返回的
   ``perturbed`` 列表即 E 的最终生成上下文（截断到 ``final_k``），保证劣化对
   生成可见——不再出现“gold 未进 C 的最终上下文时 C/E 输出完全相同”的情况。
2. gold 删除类规则在候选集中找不到 gold 时，回退 ``topk_reduced`` 并记录原因，
   保证 20 道 STRESS 题 C/E 配对不因“初检未召回 gold”而断档。
3. ``seed`` 参与注入选择（确定性），同一 (题目, 规则, seed) 可复现同一扰动。
4. 每道题可在 ``rubric.stress_rule`` 或顶层 ``stress_rule`` 字段声明规则，
   覆盖配置默认值，便于 B2/B4 按预注册分类（每类 5 题）分配。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

from .schemas import StressManifest

# 预注册规则注册表（与 e_perturbation_rules.json 的 categories 对齐）
SUPPORTED_RULES: Tuple[str, ...] = (
    "drop_all_gold_v1",
    "drop_gold_v1",
    "topk_reduced",
    "inject_unsupporting_v1",
    "unanswerable_malicious",
    # stress_20.json 的 perturb_type 映射（B2 正式压力集）
    "delete_gold_v1",          # retrieval_damage：删除全部 gold + 截断（= drop_all_gold_v1 语义）
    "inject_polluted_v1",      # injected_unsupported：注入题目声明的 polluted_evidence_ids
    "out_of_scope",            # no_evidence_outscope：压力由题面承载，不改候选集
    "malicious_fake_id",       # malicious_injection_fake_id：提示注入/伪造 ID，不改候选集
)

TOPK_REDUCED_K2: int = 3  # 预注册：K2 从 8 降到 3
INJECT_MIN: int = 2
INJECT_MAX: int = 4


def _gold_ids(question: Dict[str, Any]) -> set[str]:
    return set(question.get("gold_source_ids") or [])


def _resolve_rule(question: Dict[str, Any], rule: str) -> str:
    """优先取题目声明的 stress_rule，再取配置默认；未知规则直接报错（防拼写错误静默失效）。"""
    declared: Optional[str] = None
    rubric = question.get("rubric")
    if isinstance(rubric, dict):
        declared = rubric.get("stress_rule")
    declared = declared or question.get("stress_rule")
    chosen = str(declared or rule or "drop_all_gold_v1").strip().lower()
    if chosen not in SUPPORTED_RULES:
        raise ValueError(
            f"unsupported stress rule: {chosen!r} "
            f"(supported: {', '.join(SUPPORTED_RULES)})"
        )
    return chosen


def _manifest(**kwargs: Any) -> StressManifest:
    return StressManifest(**kwargs)


def _apply_topk_reduced(
    candidates: List[Dict[str, Any]],
    question: Dict[str, Any],
    seed: int,
    stress_id: str,
    *,
    fallback_from: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], StressManifest]:
    """预注册 topk_reduced：排除 gold 后截断到 K2=3。"""
    gold = _gold_ids(question)
    candidate_ids = [c.get("evidence_id") for c in candidates]
    perturbed = [c for c in candidates if c.get("evidence_id") not in gold][:TOPK_REDUCED_K2]
    reason = (
        f"fallback from {fallback_from}: no gold evidence in candidate set"
        if fallback_from else None
    )
    manifest = _manifest(
        stress_id=stress_id,
        question_id=question["id"],
        base_condition="C",
        stress_rule="topk_reduced",
        seed=seed,
        original_candidate_ids=list(candidate_ids),
        removed_evidence_ids=sorted(gold & set(candidate_ids)),
        perturbed_candidate_ids=[c.get("evidence_id") for c in perturbed],
        applicable=True,
        reason=reason,
    )
    return perturbed, manifest


def _apply_inject_unsupporting(
    candidates: List[Dict[str, Any]],
    question: Dict[str, Any],
    seed: int,
    final_k: int,
    stress_id: str,
) -> Tuple[List[Dict[str, Any]], StressManifest]:
    """预注册 unsupporting_injected：注入 2-4 条“主题相关但不支持”证据到上下文。

    近似实现：从 RRF 池中选取“非 gold 且不在当前 final 上下文”的尾部候选作为
    “相关但不支持”的工程代理（它们因主题相关而被召回，但不属于 gold，视为不支持
    关键主张）。真正的“不蕴含任何关键主张”判定需要 qrels/NLI，列为 P1 增强，
    限制与口径在 manifest.reason 中记录。
    """
    gold = _gold_ids(question)
    original_ids = [c.get("evidence_id") for c in candidates]
    selected = list(candidates[:final_k])
    tail = [c for c in candidates[final_k:] if c.get("evidence_id") not in gold]
    rng = random.Random(seed)
    rng.shuffle(tail)
    n_inject = max(INJECT_MIN, min(INJECT_MAX, len(tail)))
    injected = tail[:n_inject]
    injected_ids = {c.get("evidence_id") for c in injected}

    ordered = list(injected)
    ordered.extend(c for c in selected if c.get("evidence_id") not in injected_ids)
    # 确保上下文长度恰好 final_k（不足时从池中按原序补齐）
    seen = {c.get("evidence_id") for c in ordered}
    for c in candidates:
        if len(ordered) >= final_k:
            break
        if c.get("evidence_id") not in seen:
            ordered.append(c)
            seen.add(c.get("evidence_id"))
    perturbed = ordered[:final_k]
    manifest = _manifest(
        stress_id=stress_id,
        question_id=question["id"],
        base_condition="C",
        stress_rule="inject_unsupporting_v1",
        seed=seed,
        original_candidate_ids=list(original_ids),
        injected_evidence_ids=[c.get("evidence_id") for c in injected],
        perturbed_candidate_ids=[c.get("evidence_id") for c in perturbed],
        reason=(
            "approximation: non-gold tail candidates used as 'related-but-unsupporting'; "
            "refine with qrels-stance/NLI in P1"
        ),
    )
    return perturbed, manifest


def _apply_inject_polluted(
    candidates: List[Dict[str, Any]],
    question: Dict[str, Any],
    seed: int,
    final_k: int,
    stress_id: str,
    polluted_ids: List[str],
) -> Tuple[List[Dict[str, Any]], StressManifest]:
    """预注册 inject_polluted_v1：把题目声明的 polluted_evidence_ids（主题相关但不支持）
    注入上下文，并保证其排名进入前 final_k（与 e_perturbation_rules.json 的
    unsupporting_injected 一致；污染证据由 B2 预注册指定，不是随机选取）。"""
    gold = _gold_ids(question)
    original_ids = [c.get("evidence_id") for c in candidates]
    polluted = [p for p in polluted_ids if p not in gold]
    selected = [c for c in candidates if c.get("evidence_id") not in polluted][:final_k]
    injected = []
    for pid in polluted:
        # 在候选集中找对应项；不在候选集时构造轻量条目（ID 仍写入 manifest，
        # 运行时由 EvidenceStore 按 ID 取回，保证“注入证据进入 top-k”对生成可见）
        match = next((c for c in candidates if c.get("evidence_id") == pid), None)
        if match is not None:
            injected.append(dict(match))
        else:
            injected.append({"evidence_id": pid, "rank": 0, "score": 0.0,
                             "synthetic": True})
    # 污染证据排在最前（保证进入 top-k），其余按原序填充到 final_k
    ordered = list(injected)
    seen = {c.get("evidence_id") for c in ordered}
    for c in candidates:
        if len(ordered) >= final_k:
            break
        if c.get("evidence_id") not in seen and c.get("evidence_id") not in polluted:
            ordered.append(c)
            seen.add(c.get("evidence_id"))
    perturbed = ordered[:final_k]
    manifest = _manifest(
        stress_id=stress_id,
        question_id=question["id"],
        base_condition="C",
        stress_rule="inject_polluted_v1",
        seed=seed,
        original_candidate_ids=list(original_ids),
        injected_evidence_ids=[c.get("evidence_id") for c in injected],
        perturbed_candidate_ids=[c.get("evidence_id") for c in perturbed],
        reason=(
            "polluted_evidence_ids declared by B2 preregistration; candidates not in the "
            "RRF pool are recorded but skipped from context injection"
        ),
    )
    return perturbed, manifest


def _apply_unanswerable_malicious(
    candidates: List[Dict[str, Any]],
    question: Dict[str, Any],
    final_k: int,
    stress_id: str,
    rule_name: str,
) -> Tuple[List[Dict[str, Any]], StressManifest]:
    """压力由题面内容承载（范围外/提示注入/伪造 ID），不对候选集做扰动；
    C/E 保留同源上下文，E 运行单独标记供 B5 评估拒答与非法引用。"""
    original_ids = [c.get("evidence_id") for c in candidates]
    perturbed = list(candidates[:final_k])
    manifest = _manifest(
        stress_id=stress_id,
        question_id=question["id"],
        base_condition="C",
        stress_rule=rule_name,
        seed=int(question.get("stress_seed") or 0),
        original_candidate_ids=list(original_ids),
        perturbed_candidate_ids=[c.get("evidence_id") for c in perturbed],
        reason=(
            "stress carried by question content (out-of-scope / prompt injection / "
            "fake identifiers); no candidate perturbation"
        ),
    )
    return perturbed, manifest


def apply_stress(
    candidates: List[Dict[str, Any]],
    question: Dict[str, Any],
    rule: str = "drop_all_gold_v1",
    seed: int = 0,
    final_k: int = 4,
    polluted_ids: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], StressManifest]:
    """对候选证据执行可复现的 E 劣化规则。

    参数
    ----
    candidates : 检索阶段候选集（BM25+Vector+RRF 融合，按 rank 升序；B/C 同源）。
    rule       : 预注册规则名；题目级 ``rubric.stress_rule`` / ``stress_rule`` 可覆盖。
    seed       : 随机种子（注入选择等随机环节，保证确定性）。
    final_k    : E 最终生成上下文条数（默认 4，与实验配置一致）。
    polluted_ids : inject_polluted_v1 专用：题目声明的污染证据 ID 列表。

    返回
    ----
    (perturbed, manifest)：perturbed 为劣化后的最终上下文（截断到 final_k），
    manifest 记录规则、seed、删除/注入项与回退原因。
    """
    original_ids = [c.get("evidence_id") for c in candidates]
    gold = _gold_ids(question)
    effective = _resolve_rule(question, rule)
    stress_id = f"{question['id']}:{effective}:{seed}"

    # stress_20 别名 → 规范规则
    alias_map = {
        "delete_gold_v1": "drop_all_gold_v1",
    }
    effective = alias_map.get(effective, effective)
    stress_id = f"{question['id']}:{effective}:{seed}"

    if effective in ("drop_all_gold_v1", "drop_gold_v1"):
        gold_candidates = [c for c in candidates if c.get("evidence_id") in gold]
        if not gold_candidates:
            # gold 不在候选集：初检本身失败，回退 topk_reduced 保 C/E 配对
            return _apply_topk_reduced(
                candidates, question, seed, stress_id, fallback_from=effective
            )
        if effective == "drop_all_gold_v1":
            removed = list(gold_candidates)
        else:
            # 兼容早期骨架：仅删除排名最高的一条 gold
            removed = [min(gold_candidates, key=lambda c: c.get("rank", 10 ** 9))]
        removed_ids = [c["evidence_id"] for c in removed]
        removed_set = set(removed_ids)
        perturbed = [c for c in candidates if c.get("evidence_id") not in removed_set][:final_k]
        manifest = _manifest(
            stress_id=stress_id,
            question_id=question["id"],
            base_condition="C",
            stress_rule=effective,
            seed=seed,
            original_candidate_ids=list(original_ids),
            removed_evidence_ids=removed_ids,
            perturbed_candidate_ids=[c.get("evidence_id") for c in perturbed],
        )
        return perturbed, manifest

    if effective == "topk_reduced":
        return _apply_topk_reduced(candidates, question, seed, stress_id)

    if effective == "inject_unsupporting_v1":
        return _apply_inject_unsupporting(candidates, question, seed, final_k, stress_id)

    if effective == "inject_polluted_v1":
        return _apply_inject_polluted(
            candidates, question, seed, final_k, stress_id, list(polluted_ids or [])
        )

    if effective in ("unanswerable_malicious", "out_of_scope", "malicious_fake_id"):
        return _apply_unanswerable_malicious(
            candidates, question, final_k, stress_id, effective
        )

    raise ValueError(f"unsupported stress rule: {effective}")  # pragma: no cover
