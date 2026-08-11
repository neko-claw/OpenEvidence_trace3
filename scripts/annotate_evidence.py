"""证据等级标注：根据标题/摘要关键词推断 evidence_level（无需重新采集）

用法： python scripts/annotate_evidence.py
规则： 指南 > 系统综述/Meta > RCT > 队列 > 其他，命中即标注
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dataclasses import load_jsonl, save_jsonl

KEYWORDS = {
    "guideline": ["guideline", "clinical practice guideline", "consensus", "recommendation",
                  "指南", "共识", "专家建议"],
    "systematic_review": ["systematic review", "meta-analysis", "meta analysis", "umbrella review",
                          "系统综述", "荟萃分析", "meta 分析"],
    "rct": ["randomized controlled trial", "randomised controlled trial", "randomized clinical trial",
            "randomized", "randomised", "randomized trial", "随机对照", "随机化"],
    "cohort": ["cohort study", "prospective cohort", "observational study", "longitudinal",
               "队列研究", "观察性研究"],
}

ORDER = ["guideline", "systematic_review", "rct", "cohort"]


def infer_level(title: str, text: str) -> str:
    hay = (title + " " + text[:2000]).lower()
    for level in ORDER:
        for kw in KEYWORDS[level]:
            if kw.lower() in hay:
                return level
    return "unknown"


def main() -> None:
    path = Path("data/processed/evidence.jsonl")
    recs = load_jsonl(str(path))
    changed = 0
    for r in recs:
        new = infer_level(r.get("title", ""), r.get("text", ""))
        if r.get("evidence_level", "unknown") != new:
            r["evidence_level"] = new
            changed += 1
    save_jsonl(str(path), recs, mode="w")
    from collections import Counter
    print(f"共 {len(recs)} 条，更新 {changed} 条")
    for k, v in Counter(r["evidence_level"] for r in recs).most_common():
        print(f"  {k:18s} {v} 条")


if __name__ == "__main__":
    main()
