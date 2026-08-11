from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .schemas import StressManifest


def apply_stress(
    candidates: List[Dict[str, Any]],
    question: Dict[str, Any],
    rule: str = "drop_gold_v1",
    seed: int = 0,
) -> Tuple[List[Dict[str, Any]], StressManifest]:
    """对候选证据执行可复现的 E 劣化规则。"""
    original_ids = [c["evidence_id"] for c in candidates]
    gold_ids = set(question.get("gold_source_ids", []))
    stress_id = f"{question['id']}:{rule}:{seed}"

    if rule != "drop_gold_v1":
        raise ValueError(f"unsupported stress rule: {rule}")

    gold_candidates = [c for c in candidates if c["evidence_id"] in gold_ids]
    if not gold_candidates:
        manifest = StressManifest(
            stress_id=stress_id,
            question_id=question["id"],
            base_condition="C",
            stress_rule=rule,
            seed=seed,
            original_candidate_ids=original_ids,
            perturbed_candidate_ids=original_ids,
            applicable=False,
            reason="no gold evidence was present in the candidate set",
        )
        return list(candidates), manifest

    # Fixture 中 rank 越小代表越靠前；删除最高排名的 gold。
    removed = min(gold_candidates, key=lambda c: c.get("rank", 10**9))
    perturbed = [c for c in candidates if c["evidence_id"] != removed["evidence_id"]]
    manifest = StressManifest(
        stress_id=stress_id,
        question_id=question["id"],
        base_condition="C",
        stress_rule=rule,
        seed=seed,
        original_candidate_ids=original_ids,
        removed_evidence_ids=[removed["evidence_id"]],
        perturbed_candidate_ids=[c["evidence_id"] for c in perturbed],
    )
    return perturbed, manifest

