#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基于真实语料构建 LLM Wiki 主题页（规划 §5.3）。

Wiki 是“主题导航层”，不是新事实源：每个关键结论必须引用语料库内的真实
Evidence ID（[E:pmid:xxx] 等），回答生成仍回到原始证据。每主题固定结构：
  主题名/同义词/MeSH；临床问题与适用人群；关键结论（带 Evidence ID）；
  按证据类型分组（指南/系统综述/RCT/试验）；冲突与不确定性；更新时间与数据截止。

用法：
  python scripts/build_wiki.py [--topics hypertension dyslipidemia]
输出：data/processed/wiki/{topic}.md；并把 wiki 页作为 source_type=wiki 文档加入索引。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

EVIDENCE = BASE / "data" / "processed" / "evidence.jsonl"
WIKI_DIR = BASE / "data" / "processed" / "wiki"

TOPIC_TERMS = {
    "hypertension": ["hypertension", "blood pressure", "antihypertens", "高血压", "降压"],
    "dyslipidemia": ["lipid", "cholesterol", "statin", "triglycerid", "ldl", "hdl", "血脂", "他汀"],
}
TOPIC_MEAN = {
    "hypertension": ["Hypertension", "high blood pressure", "高血压"],
    "dyslipidemia": ["Dyslipidemias", "Hyperlipidemia", "血脂异常"],
}
TOPIC_LEVELS = {
    "hypertension": ["guideline", "systematic_review", "meta_analysis", "rct", "clinical-trial"],
    "dyslipidemia": ["guideline", "systematic_review", "meta_analysis", "rct", "clinical-trial"],
}


def load_corpus() -> list[dict]:
    recs = []
    with EVIDENCE.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                recs.append(json.loads(line))
    return recs


def select_evidence(recs: list[dict], topic: str, max_total: int = 14) -> list[dict]:
    terms = TOPIC_TERMS[topic]
    levels = TOPIC_LEVELS[topic]
    scored = []
    for r in recs:
        title = (r.get("title") or "").lower()
        text = ((r.get("abstract_or_chunk") or "")[:400]).lower()
        if not any(t in title or t in text for t in terms):
            continue
        level = (r.get("evidence_level") or "").lower()
        if level not in levels:
            continue
        priority = {"guideline": 0, "meta_analysis": 1, "systematic_review": 2,
                    "rct": 3, "clinical-trial": 4}.get(level, 9)
        year = r.get("year") or 0
        scored.append((priority, -year, r))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [r for _, _, r in scored[:max_total]]


def judge_client():
    from core.config import load_config
    cfg = load_config()
    j = cfg.get("judge") or {}
    base_url = j.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model = j.get("model") or "qwen3.8-max"
    key = os.environ.get(j.get("api_key_env") or "DASHSCOPE_API_KEY", "")
    return base_url.rstrip("/"), model, key


def llm_build_wiki(topic: str, evidence: list[dict], base_url: str, model: str, key: str) -> str:
    ev_lines = []
    for i, e in enumerate(evidence, 1):
        title = (e.get("title") or e.get("id"))[:150]
        text = ((e.get("abstract_or_chunk") or "")[:350]).replace("\n", " ")
        ev_lines.append(f"[E{i}] id={e['id']} | {e.get('source_type')} | "
                        f"{e.get('evidence_level')} | {e.get('published_at')} | {title}\n   {text}")
    prompt = (
        f"为医学主题『{topic}』撰写一个证据导航页（Markdown）。\n\n"
        f"下面是从语料库选出的 {len(evidence)} 条真实证据（含稳定 ID 与摘要）。\n"
        + "\n".join(ev_lines) +
        "\n\n要求：\n"
        "1. 结构固定：## 主题与同义词 / ## 临床问题与适用人群 / ## 关键结论 "
        "（每条结论末尾必须标注 [E:证据ID]，只能引用上面给出的 ID）/ "
        "## 按证据类型分组 / ## 冲突与不确定性 / ## 更新时间与数据截止\n"
        "2. 结论只能来自上面证据的摘要内容，不得编造数字或结论；\n"
        "3. 冲突与不确定性如实说明（如指南阈值差异、研究人群差异）；\n"
        "4. 只输出 Markdown，不要解释。"
    )
    import time as _t
    md = None
    for attempt in range(4):
        try:
            resp = httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "messages": [
                    {"role": "system", "content": "你是医学证据导航页撰写助手，只输出 Markdown。"},
                    {"role": "user", "content": prompt},
                ], "temperature": 0.2, "max_tokens": 3000},
                timeout=300,
            )
            resp.raise_for_status()
            md = resp.json()["choices"][0]["message"]["content"]
            break
        except Exception as e:
            print(f"  [retry {attempt + 1}] wiki {topic}: {str(e)[:80]}")
            _t.sleep(5 * (attempt + 1))
    if md is None:
        raise RuntimeError(f"wiki {topic} 生成失败")
    md += (f"\n\n> 生成模型：{model}（LLM 辅助草稿，须医学人工审核）\n"
           f"> 数据截止：2026-08-11；更新时间：{datetime.now(timezone.utc).isoformat()}\n"
           f"> 仅供教学研究，不用于临床诊疗。\n")
    return md


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topics", nargs="+", default=["hypertension", "dyslipidemia"])
    args = ap.parse_args()

    recs = load_corpus()
    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    base_url, model, key = judge_client()

    manifest = {"builder": "scripts/build_wiki.py", "model": model,
                "corpus_cutoff": "2026-08-11", "pages": {}}
    for topic in args.topics:
        ev = select_evidence(recs, topic)
        print(f"[{topic}] 选中证据 {len(ev)} 条")
        md = llm_build_wiki(topic, ev, base_url, model, key)
        out = WIKI_DIR / f"{topic}.md"
        out.write_text(md, encoding="utf-8")
        ids = [e["id"] for e in ev]
        manifest["pages"][topic] = {
            "file": str(out.relative_to(BASE)),
            "evidence_ids": ids,
            "evidence_count": len(ids),
        }
        print(f"  写出 {out.relative_to(BASE)}")
    (WIKI_DIR / "wiki_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wiki 构建完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
