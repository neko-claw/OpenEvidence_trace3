#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为 110 道题生成评分指南初稿（LLM 起草，供人工冻结前审阅）。

每题输出：
  key_points            关键回答点（原子主张 + 权重，合计 1.0）
  acceptable_evidence   可接受证据（只从 gold_literature 中取，不新造）
  wrong_answers         常见错误/反对答案
  deductions            扣分规则
  refusal_rule          拒答/部分给分规则

用法（必须用项目 conda 环境）:
    .conda/Scripts/python.exe scripts/build_scoring_guide.py

输出:
    test_set/scoring_guide.json
    test_set/scoring_guide.md
"""

from __future__ import annotations

import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

import check_corpus_coverage as ccc


BASE_DIR = Path(__file__).resolve().parents[1]
QUESTIONS_110 = BASE_DIR / "test_set" / "questions_110.json"
OUT_JSON = BASE_DIR / "test_set" / "scoring_guide.json"
OUT_MD = BASE_DIR / "test_set" / "scoring_guide.md"

BATCH_SIZE = 5
MAX_QUESTION_CHARS = 1200

SYSTEM_PROMPT = """你是医学题库评分指南起草助手。为每道题输出结构化评分指南，只输出 JSON，不要输出其他文字。

JSON 格式：
{
  "questions": [
    {
      "id": "题目 id",
      "key_points": [{"point": "原子可验证的要点", "weight": 0.4}],
      "acceptable_evidence": ["证据 ID"],
      "wrong_answers": ["常见错误/反对答案"],
      "deductions": ["扣分规则"],
      "refusal_rule": "拒答或部分给分规则"
    }
  ]
}

规则：
1. key_points 是判断答案对错必须覆盖的原子要点，1~4 条，weight 合计必须等于 1.0。
2. acceptable_evidence 只能使用输入中给出的 gold_source_ids（兼容别名 gold_literature），禁止编造新 ID。
3. 对 refusal 类题目：key_points 只写"正确拒答（不编造、不强行回答）"一条，weight=1.0；
   acceptable_evidence 为空；refusal_rule 结合 refusal_reason 写明什么算正确拒答。
4. 所有内容用中文，除非原文术语必须保留英文。"""


def load_questions():
    doc = json.loads(Path(QUESTIONS_110).read_text(encoding="utf-8"))
    return doc["questions"]


def build_batch_prompt(batch):
    items = []
    for q in batch:
        item = {
            "id": q["id"],
            "source": q["source"],
            "rag_category": q["rag_category"],
            "question": (q.get("question") or "")[:MAX_QUESTION_CHARS],
            "options": q.get("options"),
            "answer_text": q.get("answer_text"),
            "gold_source_ids": q.get("gold_source_ids") or q.get("gold_literature") or [],
            "gold_literature": q.get("gold_literature") or [],
            "refusal_reason": q.get("refusal_reason"),
            "expected_action": q.get("expected_action"),
        }
        items.append(item)
    return json.dumps({"questions": items}, ensure_ascii=False)


def parse_json(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group())


def call_llm(env, batch):
    api_key = env.get("DEEPSEEK_API_KEY", "").strip()
    base_url = env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    model = env.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_batch_prompt(batch)},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "max_tokens": 8192,
    }
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            if resp.status_code == 429:
                time.sleep(min(2 ** attempt, 30))
                continue
            resp.raise_for_status()
            return parse_json(resp.json()["choices"][0]["message"]["content"])
        except Exception as exc:
            last_err = exc
            time.sleep(min(2 ** attempt, 15))
    raise RuntimeError(f"LLM 调用失败: {last_err}")


def main():
    env = ccc.load_env(ccc.ENV_PATH)
    if not env.get("DEEPSEEK_API_KEY", "").strip():
        raise SystemExit("未检测到 DEEPSEEK_API_KEY")
    questions = load_questions()
    print(f"待起草: {len(questions)} 题")

    by_id = {q["id"]: q for q in questions}
    results = {}
    errors = []
    for i in range(0, len(questions), BATCH_SIZE):
        batch = questions[i : i + BATCH_SIZE]
        try:
            obj = call_llm(env, batch)
            for item in obj.get("questions") or []:
                results[str(item.get("id"))] = item
        except Exception as exc:
            errors.append({"batch_start": i, "ids": [q["id"] for q in batch], "error": str(exc)})
            print(f"批次失败: {[q['id'] for q in batch]}: {exc}")
        done = min(i + BATCH_SIZE, len(questions))
        print(f"进度: {done}/{len(questions)}，成功 {len(results)}")
        time.sleep(0.3)

    guide = []
    for q in questions:
        item = results.get(q["id"])
        if item is None:
            item = {"id": q["id"], "error": "生成失败"}
        item["id"] = q["id"]
        item["source"] = q["source"]
        item["split"] = q["split"]
        item["rag_category"] = q["rag_category"]
        item["answer_text"] = q.get("answer_text")
        item["gold_source_ids"] = q.get("gold_source_ids") or q.get("gold_literature") or []
        item["gold_literature"] = q.get("gold_literature") or []
        guide.append(item)

    doc = {
        "version": "0.1-draft",
        "created_at": date.today().isoformat(),
        "total": len(guide),
        "method": "DeepSeek 按题起草，需人工审阅冻结",
        "questions": guide,
    }
    OUT_JSON.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(guide)
    print(f"完成: {len(guide)} 题 | 失败 {len(errors)} 批")
    print(f"输出: {OUT_JSON} / {OUT_MD}")
    return 0


def write_markdown(guide):
    lines = [
        "# 110 题评分指南（初稿）",
        "",
        f"> 生成日期：{date.today().isoformat()} ｜ 状态：draft，需人工审阅后冻结",
        "",
        "## 评分规则总览",
        "",
        "- `key_points`：关键回答点，weight 合计 1.0，逐点判 supported/unsupported/missing",
        "- `acceptable_evidence`：只接受列表中的证据 ID，引用其他 ID 判不支持",
        "- `wrong_answers`：出现即判错/重扣",
        "- `deductions`：按条扣分",
        "- `refusal_rule`：拒答题判定（正确拒答=满分，强行作答=0 分）",
        "",
    ]
    for i, g in enumerate(guide, start=1):
        lines.append(f"## {i}. [{g['id']}] {g['source']}（{g['split']} / {g['rag_category']}）")
        lines.append("")
        if g.get("answer_text"):
            lines.append(f"- 正确答案：{g['answer_text']}")
        if g.get("error"):
            lines.append(f"- ⚠ 生成失败：{g['error']}")
            lines.append("")
            continue
        lines.append("- 关键回答点：")
        for kp in g.get("key_points") or []:
            lines.append(f"  - [{kp.get('weight')}] {kp.get('point')}")
        if g.get("acceptable_evidence"):
            lines.append(f"- 可接受证据：{', '.join(g['acceptable_evidence'])}")
        else:
            lines.append("- 可接受证据：无（拒答题不要求证据）")
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
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
