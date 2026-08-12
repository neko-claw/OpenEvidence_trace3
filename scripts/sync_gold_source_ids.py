"""把 gold_source_ids 定为正式字段，并同步现有数据里的 gold_literature 别名。

规则：
- gold_source_ids = gold_literature（refusal/无 gold 题为空列表 []）；
- gold_literature 保留为兼容别名，值不变。

覆盖文件：
- test_set/questions_110.json
- test_set/question_literature_annotation.jsonl
- test_set/scoring_guide.json
"""

from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
TARGETS = [
    BASE_DIR / "test_set" / "questions_110.json",
    BASE_DIR / "test_set" / "scoring_guide.json",
    BASE_DIR / "test_set" / "question_literature_annotation.jsonl",
]


def sync_questions(doc: dict) -> dict:
    for q in doc.get("questions", []):
        q["gold_source_ids"] = q.get("gold_literature") or []
    return doc


def main() -> None:
    for path in TARGETS:
        if not path.exists():
            print(f"skip missing: {path}")
            continue
        if path.suffix == ".jsonl":
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for row in rows:
                row["gold_source_ids"] = row.get("gold_literature") or []
            path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                encoding="utf-8",
            )
        else:
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc = sync_questions(doc)
            path.write_text(
                json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        print(f"synced: {path}")


if __name__ == "__main__":
    main()
