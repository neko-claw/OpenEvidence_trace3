from __future__ import annotations

from typing import Any, Dict, List


class MockProvider:
    """不调用网络的确定性回答器，用于验证 B4 运行、诊断和劣化流程。"""

    def generate(
        self,
        question: Dict[str, Any],
        evidence: List[Dict[str, Any]],
        condition: str,
    ) -> Dict[str, Any]:
        context_ids = [item["evidence_id"] for item in evidence]
        context_titles = [item.get("title", "") for item in evidence]
        claims = []
        for point in question.get("atomic_points", []):
            supported_ids = [
                evidence_id for evidence_id in question.get("gold_source_ids", [])
                if evidence_id in context_ids
            ]
            decision = "supported" if supported_ids else "insufficient"
            claims.append({
                "claim_id": f"{question['id']}:{point['id']}",
                "text": point["text"],
                "criticality": point.get("criticality", "important"),
                "evidence_ids": supported_ids[:2],
                "decision": decision,
            })

        if not question.get("answerable", True):
            answer = "[REFUSE] 该问题要求个体化诊疗或处方建议，离线系统不提供此类结论。"
        elif not evidence:
            answer = "[WARN] 当前没有可用证据，无法形成有依据的回答。"
        else:
            supported = sum(claim["decision"] == "supported" for claim in claims)
            answer = (
                f"[{condition}] 离线模拟回答：检索到 {len(evidence)} 条证据，"
                f"其中 {supported}/{len(claims)} 个原子主张有 gold 证据命中。"
                f"证据标题：{'；'.join(context_titles[:3])}。"
            )

        citations = [
            {"evidence_id": evidence_id, "valid": evidence_id in context_ids}
            for evidence_id in context_ids
        ]
        return {
            "answer": answer,
            "claims": claims,
            "citations": citations,
            "input_tokens": None,
            "output_tokens": None,
            "estimated_cost": 0.0,
        }

