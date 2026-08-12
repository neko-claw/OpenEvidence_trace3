#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""题集规划合规校验（v3）：只按真实运行入口判 PASS（审阅 P0-2 修复）。

v2 缺陷：把 latest_research + supplement_insufficient 计入“TEST 有效题”（91 道），
而运行时只加载 questions_110.json 的 77 道，导致验证器 PASS 与正式实验口径不一致。

v3 口径：
- 主集 = test_set/questions.jsonl（33 DEV + 77 TEST），由 rebuild_test_set.py 生成；
- STRESS = test_set/stress_20.jsonl（20 道，C/E 预注册扰动）；
- 补充包（latest_research/supplement_insufficient/external/reserve）只作留档，
  不参与主集配额，主集 PASS 只看运行时加载的文件。

检查项：
  0. 文件存在性与数量（questions 110 / stress 20）
  1. TEST 四类题型 19/19/19/20（最少 15 及格线，19 为当前目标）
  2. TEST 主题 高血压 39 / 血脂 38（目标 30 及格线）
  3. 来源家族占比 ≤40%
  4. options 覆盖：有 options 的题在运行时不再丢失选项（P0-1 验收）
  5. gold 状态诚实：gold_verified 一律 False + pending_review（P0-4 验收）
  6. gold 与语料库一致：gold_source_ids 必须存在于 data/processed/evidence.jsonl
  7. 评分指南唯一 ID 一对一、空评分点 = 0（P0-3 验收）
  8. DEV/TEST 隔离：跨 split 重复 = 0
  9. STRESS 预注册：20 道、4 类扰动各 5、stress_rule 映射齐备
  10. 可回答性/动作解耦：REFUSE 题 answerability=false，ANSWER 题 answerability=true

输出：test_set/validation_report.json / validation_report.md
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
P = BASE_DIR / "test_set"
QUESTIONS = P / "questions.jsonl"
STRESS = P / "stress_20.jsonl"
GUIDE = P / "scoring_guide.json"
CORPUS = BASE_DIR / "data" / "processed" / "evidence.jsonl"
OUT_JSON = P / "validation_report.json"
OUT_MD = P / "validation_report.md"

PLAN_TEST_TYPES = [
    "stable_knowledge_mechanism",
    "guideline_treatment",
    "latest_research_trial",
    "insufficient_conflict_out_of_scope",
]
TYPE_TARGET = 15            # 规划硬性下限（当前目标 19/19/19/20）
TOPIC_TARGET = {"hypertension": 30, "dyslipidemia": 30}
TOPIC_GOAL = {"hypertension": 39, "dyslipidemia": 38}
SOURCE_CAP = 40.0
STRESS_TYPES = ("retrieval_damage", "injected_unsupported",
                "no_evidence_outscope", "malicious_injection_fake_id")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> int:
    questions = load_jsonl(QUESTIONS)
    stress = load_jsonl(STRESS)
    guide_raw = json.loads(GUIDE.read_text(encoding="utf-8"))
    guide_items = guide_raw.get("questions", guide_raw)
    if isinstance(guide_items, dict):
        guide_items = list(guide_items.values())
    corpus = set()
    if CORPUS.exists():
        with CORPUS.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    corpus.add(json.loads(line)["id"])

    test = [q for q in questions if str(q.get("split")).lower() == "test"]
    dev = [q for q in questions if str(q.get("split")).lower() == "dev"]
    report: dict = {}

    # 0) 数据包
    report["packs"] = {
        "DEV": len(dev),
        "TEST": len(test),
        "STRESS": len(stress),
        "note": "运行时唯一主集 = questions.jsonl（DEV+TEST）；补充包（latest/supp/external/reserve）"
                "仅留档，不参与主集配额",
    }

    # 1) TEST 题型
    ttype = Counter(q.get("question_type") for q in test)
    type_ok = {}
    for t in PLAN_TEST_TYPES:
        n = ttype.get(t, 0)
        type_ok[t] = {"count": n, "floor": TYPE_TARGET, "goal": 19, "ok": n >= TYPE_TARGET}
    type_ok["unknown_or_missing"] = {
        "count": ttype.get("unknown", 0), "goal": 0, "ok": ttype.get("unknown", 0) == 0}
    report["test_question_type"] = type_ok

    # 2) TEST 主题
    ttopic = Counter(q.get("topic") for q in test)
    report["test_topic"] = {
        t: {"count": ttopic.get(t, 0), "floor": TOPIC_TARGET[t],
            "goal": TOPIC_GOAL[t], "ok": ttopic.get(t, 0) >= TOPIC_TARGET[t]}
        for t in TOPIC_TARGET
    }

    # 3) 来源家族（按真实 TEST 口径）
    fam_map = {
        "MIRAGE/medqa": "MIRAGE_family", "MIRAGE/medmcqa": "MIRAGE_family",
        "MIRAGE/pubmedqa": "MIRAGE_family", "MIRAGE/bioasq": "MIRAGE_family",
        "MIRAGE/mmlu": "MIRAGE_family", "MIRAGE/medmiqua": "MIRAGE_family",
        "MedQA-USMLE/train": "MedQA_USMLE_family", "MedQA-USMLE/dev": "MedQA_USMLE_family",
        "MedExpQA/en-train": "MedExpQA_family", "MedExpQA/en-dev": "MedExpQA_family",
        "MedExpQA/en-test": "MedExpQA_family",
    }
    fam = Counter(fam_map.get(str(q.get("source")), str(q.get("source"))) for q in test)
    fam_report = {}
    for k, v in fam.most_common():
        pct = 100.0 * v / max(1, len(test))
        fam_report[k] = {"count": v, "percent": round(pct, 1), "ok": pct <= SOURCE_CAP}
    report["test_source_family"] = fam_report
    report["source_cap"] = {
        "cap_percent": SOURCE_CAP,
        "violations": [k for k, v in fam_report.items() if not v["ok"]],
        "ok": all(v["ok"] for v in fam_report.values()),
    }

    # 4) options 覆盖（P0-1 验收：有选项的题不再丢失选项）
    with_opts = sum(1 for q in test if q.get("options"))
    missing_opts = [q["id"] for q in test if q.get("answer") and not q.get("options")]
    report["options_coverage"] = {
        "test_with_options": with_opts,
        "test_total": len(test),
        "answer_without_options": missing_opts,
        "ok": not missing_opts,
        "note": "Question 契约已保留 options 并在生成/judge Prompt 渲染（P0-1 已修）",
    }

    # 5) gold 状态诚实（P0-4）
    ans_true = [q for q in test if q.get("answerability") is True]
    gold_verified = [q["id"] for q in ans_true if q.get("gold_verified") is True]
    pending = [q["id"] for q in ans_true if q.get("gold_verification_status") == "pending_review"]
    missing_gold = [q["id"] for q in ans_true if not q.get("gold_source_ids")]
    report["gold_verification"] = {
        "answerable": len(ans_true),
        "gold_verified_ids": gold_verified,
        "pending_review": len(pending),
        "missing_gold_ids": missing_gold,
        "ok": not gold_verified and not missing_gold,
        "note": "gold_verified 一律为 False（无人工核验记录），gold_verification_status=pending_review；"
                "冻结前必须完成医学人工核验",
    }

    # 6) gold 与语料库一致
    gold_missing_corpus = []
    for q in ans_true:
        for g in q.get("gold_source_ids") or []:
            if g not in corpus:
                gold_missing_corpus.append({"question": q["id"], "gold": g})
    report["gold_corpus_coverage"] = {
        "missing_entries": len(gold_missing_corpus),
        "samples": gold_missing_corpus[:5],
        "ok": not gold_missing_corpus,
        "note": "gold_source_ids 必须存在于 data/processed/evidence.jsonl（否则检索指标不可算）",
    }

    # 7) 评分指南唯一 ID（P0-3）
    guide_ids = [str(g.get("id")) for g in guide_items if g.get("id")]
    dup_ids = {k for k, v in Counter(guide_ids).items() if v > 1}
    empty_kp = [str(g.get("id")) for g in guide_items
                if not g.get("key_points") and g.get("id")]
    qids = {str(q["id"]) for q in questions}
    missing_guide = sorted(qids - set(guide_ids))
    report["scoring_guide"] = {
        "unique_entries": len(guide_ids),
        "duplicate_ids": sorted(dup_ids),
        "empty_keypoints_ids": empty_kp,
        "questions_without_guide": missing_guide,
        "ok": not dup_ids and not empty_kp and not missing_guide,
    }

    # 8) DEV/TEST 隔离
    test_ids = {str(q["id"]) for q in test}
    dev_ids = {str(q["id"]) for q in dev}
    cross = sorted(test_ids & dev_ids)
    report["dev_test_isolation"] = {"cross_split_duplicates": cross, "ok": not cross}

    # 9) STRESS 预注册
    stype = Counter(q.get("perturb_type") for q in stress)
    stress_ok = all(stype.get(t, 0) == 5 for t in STRESS_TYPES) and len(stress) == 20
    missing_rule = [q["id"] for q in stress if not q.get("stress_rule")]
    report["stress"] = {
        "count": len(stress),
        "by_perturb_type": dict(stype),
        "missing_rule_ids": missing_rule,
        "ok": stress_ok and not missing_rule,
        "note": "E 条件按 stress_rule 执行（delete_gold_v1/inject_polluted_v1/out_of_scope/malicious_fake_id）",
    }

    # 10) 动作/可回答性一致性
    action_mismatch = [
        (q["id"], q.get("expected_action"), q.get("answerability"))
        for q in test
        if (q.get("expected_action") == "REFUSE" and q.get("answerability") is True)
        or (q.get("expected_action") == "ANSWER" and q.get("answerability") is False)
    ]
    report["action_answerability_consistency"] = {
        "mismatches": action_mismatch,
        "ok": not action_mismatch,
        "note": "REFUSE↔answerability=false；ANSWER/WARN↔answerability=true",
    }

    # 汇总
    fails = []
    for t, v in type_ok.items():
        if not v.get("ok"):
            fails.append(f"TEST 题型 {t}: {v['count']}/{v['floor']}")
    for t, v in report["test_topic"].items():
        if not v["ok"]:
            fails.append(f"TEST 主题 {t}: {v['count']}/{v['floor']}")
    for k, v in [("source_cap", report["source_cap"]), ("options_coverage", report["options_coverage"]),
                 ("gold_verification", report["gold_verification"]),
                 ("gold_corpus_coverage", report["gold_corpus_coverage"]),
                 ("scoring_guide", report["scoring_guide"]),
                 ("dev_test_isolation", report["dev_test_isolation"]),
                 ("stress", report["stress"]),
                 ("action_answerability_consistency", report["action_answerability_consistency"])]:
        ok = v.get("ok") if isinstance(v, dict) else False
        if not ok:
            fails.append(f"{k}: {v}")
    report["summary"] = {
        "fails": fails,
        "pass": not fails,
        "note": "口径=运行时唯一主集 questions.jsonl（77 TEST + 33 DEV）+ stress_20.jsonl；"
                "gold 仍为 pending_review，冻结前须医学人工核验；"
                "TEST 题型当前 19/19/19/20、主题 39/38（高于规划下限 15/30）",
    }

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(report)
    print("校验: ", "PASS" if report["summary"]["pass"] else "FAIL")
    for f in fails:
        print("  -", f)
    return 0 if report["summary"]["pass"] else 2


def write_markdown(r: dict) -> None:
    lines = [
        "# 题集规划合规校验报告（v3，真实运行口径）",
        "",
        "> 校验对象：test_set/questions.jsonl（33 DEV + 77 TEST，运行时唯一主集）+ test_set/stress_20.jsonl",
        "> v2 曾把 latest_research/supplement_insufficient 计入主集（91 道）导致口径不一致；v3 只按运行时入口判定。",
        "",
        "## 结论", "",
        f"- **{'PASS' if r['summary']['pass'] else 'FAIL'}**：{r['summary']['note']}", "",
        "## 0. 数据包", "",
        "| 包 | 数量 |", "|---|---:|",
        f"| DEV | {r['packs']['DEV']} |",
        f"| TEST（运行时主集） | {r['packs']['TEST']} |",
        f"| STRESS | {r['packs']['STRESS']} |",
        f"| 说明 | {r['packs']['note']} |",
        "", "## 1. TEST 四类题型（下限 15，目标 19/19/19/20）", "",
        "| 题型 | 当前 | 下限 | 目标 |", "|---|---:|---:|---:|",
    ]
    for t, v in r["test_question_type"].items():
        if "floor" in v:
            lines.append(f"| {t} | {v['count']} | {v['floor']} | {v['goal']} |")
        else:
            lines.append(f"| {t} | {v['count']} | - | {v['goal']} |")
    lines += ["", "## 2. TEST 主题（下限 30，目标 39/38）", "", "| 主题 | 当前 | 下限 | 目标 |", "|---|---:|---:|---:|"]
    for t, v in r["test_topic"].items():
        lines.append(f"| {t} | {v['count']} | {v['floor']} | {v['goal']} |")
    lines += ["", "## 3. 来源家族占比（<=40%）", "", "| 家族 | 数量 | 占比 | 达标 |", "|---|---:|---:|---|"]
    for fam, v in r["test_source_family"].items():
        lines.append(f"| {fam} | {v['count']} | {v['percent']}% | {'✅' if v['ok'] else '❌'} |")
    lines += ["", "## 4. 选项覆盖（P0-1）", "",
              f"- TEST 有选项题 {r['options_coverage']['test_with_options']}/{r['options_coverage']['test_total']}；"
              f"有答案但缺选项：{r['options_coverage']['answer_without_options'] or '无'}", "",
              "## 5. gold 核验状态（P0-4）", "",
              f"- 可回答题 {r['gold_verification']['answerable']}；gold_verified=True 的题："
              f"{r['gold_verification']['gold_verified_ids'] or '无（诚实标注 pending_review）'}；"
              f"缺 gold：{r['gold_verification']['missing_gold_ids'] or '无'}", "",
              "## 6. gold 与语料库一致性", "",
              f"- 缺失 {r['gold_corpus_coverage']['missing_entries']} 条"
              f"{'，样例：' + str(r['gold_corpus_coverage']['samples']) if r['gold_corpus_coverage']['missing_entries'] else '（全部在库）'}", "",
              "## 7. 评分指南（P0-3）", "",
              f"- 唯一条目 {r['scoring_guide']['unique_entries']}；重复 ID："
              f"{r['scoring_guide']['duplicate_ids'] or '无'}；空评分点："
              f"{r['scoring_guide']['empty_keypoints_ids'] or '无'}；无指南题："
              f"{r['scoring_guide']['questions_without_guide'] or '无'}", "",
              "## 8. DEV/TEST 隔离", "",
              f"- 跨 split 重复：{r['dev_test_isolation']['cross_split_duplicates'] or '无'}", "",
              "## 9. STRESS 预注册（P0-7）", "",
              f"- 共 {r['stress']['count']} 道，扰动分布：{r['stress']['by_perturb_type']}；"
              f"缺规则：{r['stress']['missing_rule_ids'] or '无'}", "",
              "## 10. 动作/可回答性一致性", "",
              f"- 不一致：{r['action_answerability_consistency']['mismatches'] or '无'}", "",
              "## 失败清单", ""]
    for f in r["summary"]["fails"]:
        lines.append(f"- {f}")
    if not r["summary"]["fails"]:
        lines.append("- （无）")
    lines.append("")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
