#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gold 医学核验管线：LLM 辅助首轮对齐检查 + 人工终审留痕。

背景（规划 §6.3 / §5.8）：gold 必须由人基于真实 PubMed/指南/试验核验，不能由
自动流程冒充。本脚本提供：
1. **首轮 LLM 辅助检查**：对每道可回答题的 gold 证据摘要与题目答案（answer_text /
   答案选项）做对齐判定（supported / unsupported / uncertain），标记为
   `llm_assisted_review`（**不是**人工核验）；
2. **人工终审接口**：输出 `gold_review.jsonl`，医学评审人逐题填
   `reviewer_verdict=verified|rejected|needs_fix` + 备注后，脚本把已核验题目的
   `gold_verification_status` 升级为 `human_verified` 并重新生成 questions.jsonl；
3. **汇总报告**：核验覆盖率、疑似不匹配清单、待人工复核清单。

用法：
  python scripts/verify_gold.py                  # LLM 辅助首轮（写入 gold_review.jsonl）
  python scripts/verify_gold.py --finalize       # 按 gold_review.jsonl 的人工裁决回写题集
  python scripts/verify_gold.py --dry-run        # 只读统计，不调 LLM
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parents[1]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
QUESTIONS = BASE / "test_set" / "questions.jsonl"
EVIDENCE = BASE / "data" / "processed" / "evidence.jsonl"
REVIEW = BASE / "test_set" / "gold_review.jsonl"
SUMMARY = BASE / "test_set" / "gold_review_summary.md"


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_corpus() -> dict[str, dict]:
    out = {}
    for rec in load_jsonl(EVIDENCE):
        out[rec["id"]] = rec
    return out


def _judge_client():
    """构建评审 LLM client（默认 qwen3.8-max / DashScope，config.judge）。"""
    from core.config import load_config
    cfg = load_config()
    j = cfg.get("judge") or {}
    base_url = j.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model = j.get("model") or "qwen3.8-max"
    key_env = j.get("api_key_env") or "DASHSCOPE_API_KEY"
    key = os.environ.get(key_env, "")
    if not key:
        raise RuntimeError(f"缺少 {key_env}")
    return base_url.rstrip("/"), model, key


def llm_check(question: dict, gold: dict, answer_text: str, base_url: str, model: str, key: str) -> dict:
    """单题 LLM 对齐判定。"""
    prompt = (
        "你是医学证据核验员。判断给定的『标准答案』是否能被『gold 证据摘要』支持。\n\n"
        f"题目：{question.get('question', '')}\n"
        f"标准答案：{answer_text or question.get('answer') or '（无，见评分指南）'}\n"
        f"gold 证据标题：{gold.get('title', '')}\n"
        f"gold 证据摘要：{(gold.get('abstract_or_chunk') or '')[:1200]}\n\n"
        "只输出 JSON：{\"verdict\": \"supported|unsupported|uncertain\", "
        "\"reason\": \"一句话理由（含具体不一致点）\"}"
    )
    resp = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": [
            {"role": "system", "content": "你是严格的医学证据核验员，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ], "temperature": 0.0, "max_tokens": 300,
               "response_format": {"type": "json_object"}},
        timeout=90,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    obj = json.loads(content)
    return obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--finalize", action="store_true", help="按 gold_review.jsonl 人工裁决回写题集")
    ap.add_argument("--refine", action="store_true", help="为 gold_flagged 题从检索证据中 LLM 重选更相关 gold")
    ap.add_argument("--dry-run", action="store_true", help="只读统计，不调 LLM")
    args = ap.parse_args()

    questions = load_jsonl(QUESTIONS)
    corpus = load_corpus()

    if args.finalize:
        return finalize(questions)

    if args.refine:
        return refine_gold(questions, corpus)

    answerable = [q for q in questions if q.get("answerability") is True]
    with_gold = [q for q in answerable if q.get("gold_source_ids")]
    print(f"可回答题 {len(answerable)}，含 gold {len(with_gold)}")

    if args.dry_run:
        no_answer = [q["id"] for q in with_gold
                     if not q.get("answer_text") and not q.get("answer")]
        print(f"dry-run: 无答案文本（跳过 LLM 检查，仅人工核验）{len(no_answer)}: {no_answer[:8]}")
        return 0

    base_url, model, key = _judge_client()
    existing = {r["question_id"]: r for r in load_jsonl(REVIEW)} if REVIEW.exists() else {}
    rows = []
    pending = []
    for i, q in enumerate(with_gold, 1):
        qid = q["id"]
        gold_ids = [g for g in q.get("gold_source_ids") if g in corpus]
        if not gold_ids:
            rows.append({"question_id": qid, "status": "no_gold_in_corpus",
                         "reviewer": "pipeline", "notes": "gold 不在语料库"})
            pending.append(qid)
            continue
        answer_text = q.get("answer_text") or (f"选项 {q.get('answer')}" if q.get("answer") else "")
        if not answer_text:
            rows.append({"question_id": qid, "status": "no_answer_text",
                         "reviewer": "pipeline", "notes": "缺 answer_text，需人工按评分指南核验"})
            pending.append(qid)
            continue
        gold = corpus[gold_ids[0]]
        try:
            verdict = llm_check(q, gold, answer_text, base_url, model, key)
        except Exception as e:
            rows.append({"question_id": qid, "status": "llm_error", "reviewer": model,
                         "notes": f"{type(e).__name__}: {str(e)[:100]}"})
            pending.append(qid)
            continue
        status = "llm_assisted_supported" if verdict.get("verdict") == "supported" else (
            "llm_assisted_unsupported" if verdict.get("verdict") == "unsupported" else "llm_assisted_uncertain")
        rows.append({
            "question_id": qid,
            "status": status,
            "reviewer": f"{model} (llm_assisted, NOT human_verified)",
            "verdict": verdict.get("verdict"),
            "reason": verdict.get("reason", ""),
            "gold_ids": gold_ids,
        })
        if status != "llm_assisted_supported":
            pending.append(qid)
        print(f"[{i}/{len(with_gold)}] {qid}: {status}")
        # 断点保存
        with REVIEW.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 汇总
    counter = Counter(r["status"] for r in rows)
    with SUMMARY.open("w", encoding="utf-8") as f:
        f.write("# gold 医学核验报告（LLM 辅助首轮）\n\n")
        f.write(f"- 可回答题：{len(answerable)}；含 gold：{len(with_gold)}\n")
        f.write(f"- 状态分布：{dict(counter)}\n")
        f.write(f"- **需人工终审**：{len(pending)} 题（{pending[:20]}...）\n")
        f.write("- 说明：llm_assisted_* 仅表示 LLM 对齐检查结果，**不是**医学人工核验；\n")
        f.write("  由医学评审人在 gold_review.jsonl 填 reviewer_verdict 后执行 "
                "`python scripts/verify_gold.py --finalize` 升级为 human_verified。\n")
    print(f"\n汇总: {dict(counter)}")
    print(f"需人工终审: {len(pending)} 题 -> {SUMMARY}")
    return 0


def refine_gold(questions: list[dict], corpus: dict[str, dict]) -> int:
    """为 gold_flagged 题重选更相关 gold：从题目 evidence_retrieved/literature_used 中
    用 LLM 挑选最能支持标准答案的证据；无合适候选则保持 flagged 待人工。"""
    base_url, model, key = _judge_client()
    flagged = [q for q in questions
               if q.get("answerability") is True
               and q.get("gold_verification_status") == "gold_flagged"]
    print(f"待精修 {len(flagged)} 题")
    refined = 0
    no_candidate = 0
    for i, q in enumerate(flagged, 1):
        answer_text = q.get("answer_text") or (f"选项 {q.get('answer')}" if q.get("answer") else "")
        if not answer_text:
            continue
        # 候选 = 题目检索证据中在语料库内的条目（排除当前 gold）
        seen = set(q.get("gold_source_ids") or [])
        candidates = []
        for key_ in ("evidence_retrieved", "literature_used"):
            for eid in q.get(key_) or []:
                if eid in corpus and eid not in seen:
                    candidates.append(eid)
                    seen.add(eid)
        if not candidates:
            no_candidate += 1
            continue
        cand_text = []
        for eid in candidates[:8]:
            rec = corpus[eid]
            cand_text.append(f"[{eid}] {rec.get('title','')} | {(rec.get('abstract_or_chunk') or '')[:200]}")
        prompt = (
            "从候选证据中挑选**最能支持标准答案**的一条（或判无）。\n\n"
            f"题目：{q.get('question','')}\n"
            f"标准答案：{answer_text}\n\n候选证据：\n" + "\n".join(cand_text) +
            "\n\n只输出 JSON：{\"pick\": \"证据ID 或 null\", \"reason\": \"一句话理由\"}"
        )
        picked = None
        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": model, "messages": [
                        {"role": "system", "content": "你是医学证据核验员，只输出 JSON。"},
                        {"role": "user", "content": prompt}],
                        "temperature": 0.0, "max_tokens": 300,
                        "response_format": {"type": "json_object"}},
                    timeout=90,
                )
                resp.raise_for_status()
                obj = json.loads(resp.json()["choices"][0]["message"]["content"])
                picked = obj.get("pick")
                break
            except Exception as e:
                print(f"  [retry {attempt+1}] {q['id']}: {str(e)[:80]}")
                import time
                time.sleep(2 ** attempt)
        if picked and picked in corpus and picked != "null":
            q["gold_source_ids"] = [picked]
            q["gold_literature"] = [picked]
            q["gold_verification_status"] = "llm_refined"
            q["gold_llm_reason"] = obj.get("reason", "") if obj else ""
            q["gold_verified"] = False
            refined += 1
        else:
            no_candidate += 1
        print(f"[{i}/{len(flagged)}] {q['id']}: {'refined->'+str(picked) if picked else 'keep flagged'}")
        # 增量保存
        with QUESTIONS.open("w", encoding="utf-8") as f:
            for qq in questions:
                f.write(json.dumps(qq, ensure_ascii=False) + "\n")
    print(f"精修完成: {refined} 题重选 gold；{no_candidate} 题保持 flagged 待人工")
    return 0


def finalize(questions: list[dict]) -> int:
    """按 gold_review.jsonl 的人工裁决回写题集。"""
    if not REVIEW.exists():
        print("gold_review.jsonl 不存在")
        return 2
    verdicts = {r["question_id"]: r for r in load_jsonl(REVIEW) if r.get("reviewer_verdict")}
    if not verdicts:
        print("gold_review.jsonl 中没有 reviewer_verdict（人工裁决尚未填写）")
        return 2
    n_verified = 0
    for q in questions:
        rv = verdicts.get(q["id"])
        if rv and rv.get("reviewer_verdict") == "verified":
            q["gold_verified"] = True
            q["gold_verification_status"] = "human_verified"
            q["gold_reviewer"] = rv.get("reviewer", "human")
            q["gold_review_note"] = rv.get("note", "")
            n_verified += 1
    with QUESTIONS.open("w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(f"已升级 {n_verified} 题为 human_verified（共 {len(questions)} 题）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
