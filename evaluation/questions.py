"""统一题集加载器：兼容 data/questions JSONL 样例与 test_set/questions_110.json。

格式支持：
- .jsonl：每行一个题对象（旧样例格式）
- .json：
  - {"questions": [...]}（test_set/questions_110.json）
  - [...]（纯数组）
  - 单个题对象

返回记录保留全部原始字段，供 stats/charts 等按字段分组；`load_questions`
额外归一化为运行时 Question，并自动合并同目录 scoring_guide.json 的 rubric。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.dataclasses import Question, load_jsonl


def load_question_records(
    path: str | Path,
    split: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """读取题集原始记录；split 为 dev/test/all（None 等价 all）。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"题集不存在: {p}")

    if p.suffix.lower() == ".jsonl":
        records = load_jsonl(str(p))
    elif p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            records = data.get("questions")
            if not isinstance(records, list):
                records = [data]
        elif isinstance(data, list):
            records = data
        else:
            raise ValueError(f"不支持的 JSON 结构: {p}")
    else:
        raise ValueError(f"不支持的文件类型: {p.suffix}（仅支持 .json / .jsonl）")

    if split and split != "all":
        records = [
            r for r in records
            if str(r.get("split", "")).lower() == str(split).lower()
        ]
    if limit:
        records = records[:limit]
    return records


def _load_scoring_guide(path: Path) -> dict[str, dict]:
    """读取题集同目录的 scoring_guide.json（如有），按 id 建索引。"""
    guide_path = path.parent / "scoring_guide.json"
    if not guide_path.exists():
        return {}
    data = json.loads(guide_path.read_text(encoding="utf-8"))
    items = data.get("questions", data) if isinstance(data, dict) else data
    if isinstance(items, dict):
        items = list(items.values())
    return {
        str(q.get("id")): q
        for q in items
        if isinstance(q, dict) and q.get("id") is not None
    }


def to_question(record: dict, scoring_guide: dict[str, dict] | None = None) -> Question:
    """把原始题记录归一化为运行时 Question（缺省字段用 unknown/stable 兜底）。"""
    scoring_guide = scoring_guide or {}
    rubric = dict(record.get("rubric") or {})

    guide = scoring_guide.get(str(record.get("id")))
    if guide and not rubric:
        rubric = {
            "key_points": guide.get("key_points", []),
            "acceptable_evidence": guide.get("acceptable_evidence", []),
            "deductions": guide.get("deductions", []),
            "refusal_rule": guide.get("refusal_rule", ""),
            "wrong_answers": guide.get("wrong_answers", []),
        }
    if "key_points" in rubric:
        rubric["key_points"] = [
            k.get("point", str(k)) if isinstance(k, dict) else str(k)
            for k in rubric["key_points"]
        ]

    topic = record.get("topic") or (record.get("topic_tags") or [""])[0] or "unknown"
    difficulty = record.get("difficulty")
    if difficulty is None:
        difficulty = "unknown"

    # options 兼容两种格式：dict{"A":...}（test_set）与 list[...]；统一为固定顺序的文本列表
    raw_opts = record.get("options") or []
    if isinstance(raw_opts, dict):
        options = [str(v) for _, v in sorted(raw_opts.items())]
    elif isinstance(raw_opts, list):
        options = [str(o) for o in raw_opts]
    else:
        options = []

    return Question(
        id=str(record.get("id", "")),
        topic=str(topic),
        difficulty=str(difficulty),
        question=str(record.get("question", "")),
        question_type=str(record.get("question_type") or "unknown"),
        freshness=str(record.get("freshness") or "stable"),
        # 正式字段为 gold_source_ids；gold_literature 是 test_set 的兼容别名
        gold_source_ids=list(
            record.get("gold_source_ids") or record.get("gold_literature") or []
        ),
        split=str(record.get("split") or record.get("dataset_pack") or ""),
        dataset_pack=str(record.get("dataset_pack") or ""),
        answerable=(
            record.get("answerable")
            if record.get("answerable") is not None
            else (True if str(record.get("answerability")).lower() == "true" else None)
        ),
        as_of_date=str(record.get("as_of_date") or ""),
        source_group_id=str(record.get("source_group_id") or record.get("id") or ""),
        # 选择题选项（固定顺序，A/B/C/D 与 judge Prompt 均渲染，修复选项丢失问题）
        options=options,
        expected_action=str(record.get("expected_action") or record.get("rag_category") or ""),
        rubric=rubric,
    )


def load_questions(
    path: str | Path,
    split: str | None = None,
    limit: int | None = None,
) -> list[Question]:
    """统一加载题集并归一化为 Question 列表（保留 dev/test 分层）。"""
    p = Path(path)
    records = load_question_records(p, split=split, limit=limit)
    scoring_guide = _load_scoring_guide(p)
    return [to_question(r, scoring_guide) for r in records]
