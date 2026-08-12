#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复评分指南（scoring_guide.json/md）的系统性矛盾，并对齐修复后的题集。

问题（docs/b2_dataset_review.md §4.3）：
- 58/59 拒答题同时列"正确拒答=满分"与基准答案/错误选项 → judge 自相矛盾；
- 44 道恢复为可回答的题仍用"正确拒答"key_points；
- 新增 latest/external/reserve 题无评分指南条目。

修复规则：
1. 真拒答题（answerability=false）：删除 answer_text / wrong_answers 中的具体答案与选项，
   保留 refusal_rule（正确拒答=满分，强行作答=0）；
2. 恢复题（answerability=true 且原为拒答规则）：key_points 重写为
   [给出正确答案：{answer_text}]（weight 1.0），refusal_rule 清空，标注 pending 人工复核；
3. 新增题（latest/external/reserve 构造）：按 answer_text 生成 key_points。

输出：test_set/scoring_guide.json / scoring_guide.md（version=0.2-adjudicated）
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
QUESTIONS_110 = BASE_DIR / "test_set" / "questions_110.json"
LATEST = BASE_DIR / "test_set" / "latest_research.json"
EXTERNAL = BASE_DIR / "test_set" / "external_10.json"
RESERVE = BASE_DIR / "test_set" / "reserve_10.json"
GUIDE = BASE_DIR / "test_set" / "scoring_guide.json"
GUIDE_MD = BASE_DIR / "test_set" / "scoring_guide.md"

REFUSAL_RULE = "正确拒答=满分；强行作答/编造证据=0 分。若给出具体答案或剂量视为猜测，扣分。"


def load(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "questions" in data:
        return data["questions"]
    return data


def main() -> int:
    qs = load(QUESTIONS_110)
    q_by_id = {str(q["id"]): q for q in qs}
    for extra_path in (LATEST, EXTERNAL, RESERVE):
        for q in load(extra_path):
            q_by_id[str(q["id"])] = q

    guide = load(GUIDE)
    guide_by_id = {str(g.get("id")): g for g in guide}
    if len(guide_by_id) != len(guide):
        print("WARNING: guide id 冲突", len(guide_by_id), len(guide))

    stats = Counter()
    out = []
    for q in qs + load(LATEST) + load(EXTERNAL) + load(RESERVE):
        qid = str(q["id"])
        item = guide_by_id.get(qid)
        if item is None:
            # 新增题：生成条目
            item = {"id": qid, "source": q.get("source"), "split": q.get("split"),
                    "rag_category": q.get("rag_category"), "answer_text": q.get("answer_text"),
                    "gold_source_ids": q.get("gold_source_ids") or [],
                    "key_points": [], "acceptable_evidence": [],
                    "wrong_answers": [], "deductions": [], "refusal_rule": "",
                    "adjudication": "generated"}
            stats["generated"] += 1
        ans = q.get("answerability")
        restored = (str(ans) == "true" and item.get("refusal_rule") and
                    "正确拒答" in (item.get("refusal_rule") or "")) or (
                    str(ans) == "true" and item.get("key_points") and
                    any("拒答" in (k.get("point") or "") for k in item.get("key_points") or []))
        if restored:
            # 恢复题：重写 key_points
            at = q.get("answer_text") or q.get("answer") or ""
            item["key_points"] = [{"point": f"给出正确答案：{at}", "weight": 1.0}]
            item["refusal_rule"] = ""
            item["deductions"] = [d for d in (item.get("deductions") or []) if "拒答" not in d]
            item["adjudication"] = "pending_human_keypoints"
            stats["restored"] += 1
        elif str(ans) == "false":
            # 真拒答题：清除具体答案/选项，保留拒答规则
            item["answer_text"] = None
            item["wrong_answers"] = [w for w in (item.get("wrong_answers") or [])
                                     if "选项" not in w and "答案" not in w]
            if not item.get("key_points"):
                item["key_points"] = [{"point": "正确拒答（不编造、不强行回答）", "weight": 1.0}]
            item["refusal_rule"] = REFUSAL_RULE
            item["adjudication"] = "manual"
            stats["refusal_clean"] += 1
        else:
            item["refusal_rule"] = ""
        # 确保 key_points 存在
        if not item.get("key_points"):
            at = q.get("answer_text") or q.get("answer") or ""
            item["key_points"] = [{"point": f"给出正确答案：{at}", "weight": 1.0}]
            stats["keypoint_fill"] += 1
        out.append(item)

    doc = {
        "version": "0.2-adjudicated",
        "created_at": "2026-08-12",
        "total": len(out),
        "method": "DeepSeek 起草 + 人工修复（review/b2-dataset-refactor）",
        "note": "拒答矛盾已清除；恢复题 key_points 为占位（pending_human_keypoints），正式运行前需逐题复核",
        "stats": dict(stats),
        "questions": out,
    }
    GUIDE.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(out)
    print("guide updated:", dict(stats), "total:", len(out))
    return 0


def write_markdown(items: list[dict]) -> None:
    lines = [
        "# 题集评分指南（0.2-adjudicated）",
        "",
        "> 生成日期：2026-08-12 ｜ 状态：draft，待人工冻结；拒答矛盾已清除",
        "",
        "## 评分规则总览",
        "",
        "- `key_points`：关键回答点，weight 合计 1.0，逐点判 supported/unsupported/missing",
        "- `acceptable_evidence`：只接受列表中的证据 ID",
        "- `wrong_answers`：出现即判错/重扣",
        "- `refusal_rule`：拒答题判定（正确拒答=满分，强行作答=0）",
        "",
    ]
    for i, g in enumerate(items, start=1):
        lines.append(f"## {i}. [{g['id']}] {g.get('source','')}（{g.get('split','')} / {g.get('rag_category','')}）")
        lines.append("")
        if g.get("answer_text"):
            lines.append(f"- 正确答案：{g['answer_text']}")
        if g.get("adjudication") == "pending_human_keypoints":
            lines.append("- ⚠ key_points 为占位，待人工复核")
        lines.append("- 关键回答点：")
        for kp in g.get("key_points") or []:
            lines.append(f"  - [{kp.get('weight')}] {kp.get('point')}")
        if g.get("acceptable_evidence"):
            lines.append(f"- 可接受证据：{', '.join(g['acceptable_evidence'])}")
        if g.get("wrong_answers"):
            lines.append("- 错误答案/反对证据：")
            for w in g["wrong_answers"]:
                lines.append(f"  - {w}")
        if g.get("deductions"):
            lines.append("- 扣分项：")
            for d in g["deductions"]:
                lines.append(f"  - {d}")
        if g.get("refusal_rule"):
            lines.append(f"- 拒答规则：{g['refusal_rule']}")
        lines.append("")
    GUIDE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
