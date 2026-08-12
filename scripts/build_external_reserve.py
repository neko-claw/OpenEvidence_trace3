#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构造 EXTERNAL（10）与 RESERVE（10）两个数据包。

EXTERNAL：跨题目来源泛化检查（10 题，来源=ClinicalTrials 试验 + Europe PMC 文献，
gold 为语料库可检索证据，不参与 A/B/C/D 主对比，只做确定性评分+抽查）。
RESERVE：备用集（10 题）= questions_110 中标记的 6 道同源重复题 + 4 道语料库构造题，
用于替换泄漏/重复/gold 失效/解析失败。

输出：test_set/external_10.json / test_set/reserve_10.json
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
QUESTIONS_110 = BASE_DIR / "test_set" / "questions_110.json"
EVIDENCE_DB = BASE_DIR / "data" / "processed" / "evidence.db"
OUT_EXT = BASE_DIR / "test_set" / "external_10.json"
OUT_RES = BASE_DIR / "test_set" / "reserve_10.json"

AS_OF_DATE = "2026-08-11"

# EXTERNAL 10：试验 5 + 文献 5（跨来源泛化）
EXTERNAL = [
    # --- ClinicalTrials ---
    ("EXT-01", "hypertension", "nct:NCT05843162",
     "比较替米沙坦与氯沙坦在高血压患者中血压控制效果的 4 期随机开放试验，其主要设计特点是什么？",
     "多中心、随机、开放标签、活性对照的 4 期试验，比较两种 ARB 的血压控制。"),
    ("EXT-02", "hypertension", "nct:NCT02664610",
     "REACH OUT 社区研究探索用什么方式降低高血压患者的血压？",
     "通过短信（text messaging）进行社区干预以降低血压。"),
    ("EXT-03", "hypertension", "nct:NCT04218903",
     "老年高血压患者中不同周训练频率的抗阻+有氧联合训练研究关注什么？",
     "联合训练是改善老年高血压患者功能与降低血压的基础干预，研究比较不同周频率。"),
    ("EXT-04", "hypertension", "nct:NCT02844413",
     "关于运动对高血压患者血压与动脉僵硬度影响的临床试验基于什么推荐？",
     "欧美国指南推荐规律运动作为高血压辅助治疗，试验评估其血压与动脉僵硬度效应。"),
    ("EXT-05", "hypertension", "nct:NCT05395403",
     "自动诊室血压监测（AOBP）研究比较了哪三种血压测量方法？",
     "比较诊室血压测量（OBPM）、自动诊室血压测量（AOBP）与相关方法的差异。"),
    # --- Europe PMC ---
    ("EXT-06", "dyslipidemia", "pmid:37415367",
     "系统综述中，DASH 饮食对血脂谱的影响如何？",
     "DASH 饮食对血脂谱（TC/LDL/HDL/TG）有改善作用（系统综述证据）。"),
    ("EXT-07", "dyslipidemia", "pmid:38777087",
     "限盐背景下 DASH 饮食与地中海饮食对代谢综合征人群的效果比较？",
     "两者结合限盐对代谢综合征相关指标均有改善，DASH 在某些血脂指标上更优（按摘要结论）。"),
    ("EXT-08", "hypertension", "pmid:39194352",
     "系统综述中，远程医疗管理心血管危险因素（含高血压）的结论？",
     "远程医疗在初级保健中管理心血管危险因素显示出可行性/有效性证据（按摘要）。"),
    ("EXT-09", "dyslipidemia", "pmid:39304616",
     "PCSK9 抑制剂在杂合子家族性高胆固醇血症（HeFH）患者中的疗效？",
     "PCSK9 抑制剂显著降低 HeFH 患者 LDL-C（疗效证据）。"),
    ("EXT-10", "dyslipidemia", "pmid:38483844",
     "远程康复（telerehabilitation）对高血压患者心脏重构与血流动力学的影响？",
     "远程康复改善高血压患者心脏重构与血流动力学参数（按摘要）。"),
]

# RESERVE 4 道构造题（其余 6 道为 questions_110 标记的同源重复题）
RESERVE_EXTRA = [
    ("R-07", "dyslipidemia", "pmid:37815648",
     "强化降脂治疗对冠脉斑块稳定性的影响（影像学研究）结论？",
     "强化降脂治疗对冠脉斑块稳定有积极作用（斑块稳定化证据）。"),
    ("R-08", "dyslipidemia", "pmid:39343641",
     "儿童与青少年中他汀、依折麦布及联合治疗的疗效与安全性证据？",
     "联合/单药均有效降低儿童青少年 LDL-C，安全性总体可接受（按摘要）。"),
    ("R-09", "dyslipidemia", "pmid:39466484",
     "他汀治疗对脂蛋白相关磷脂酶 A2（Lp-PLA2）质量与活性的影响？",
     "他汀降低 Lp-PLA2 质量与活性（meta 分析，按摘要）。"),
    ("R-10", "hypertension", "pmid:38483844",
     "高血压患者远程康复对心脏重构与血流动力学参数的影响？",
     "远程康复改善心脏重构与血流动力学参数。"),
]


def check_evidence(cur, eid):
    return cur.execute("SELECT id FROM evidence WHERE id=?", (eid,)).fetchone() is not None


def make_record(qid, split, pack, topic, eid, question, answer, source_label,
                extra=None):
    rec = {
        "id": qid,
        "source": source_label,
        "split": split,
        "dataset_pack": pack,
        "rag_category": "easy",
        "audit_status": "pass",
        "answerability": "true",
        "adjudication_status": "manual",
        "adjudication_note": "从语料库真实文献/试验抽象，gold 为语料库可检索证据",
        "question_type": "latest_research_trial",
        "topic": topic,
        "language": "zh",
        "question": question,
        "options": {},
        "answer": None,
        "answer_text": answer,
        "as_of_date": AS_OF_DATE,
        "source_provenance": source_label,
        "source_group_id": qid,
        "gold_source_ids": [eid],
        "gold_literature": [eid],
        "gold_verified": False,
        "gold_verification_status": "pending_review",
        "rubric_version": "0.2-adjudicated",
        "evidence_retrieved": [eid],
    }
    if extra:
        rec.update(extra)
    return rec


def main() -> int:
    con = sqlite3.connect(str(EVIDENCE_DB))
    cur = con.cursor()
    missing = []

    ext_rows = []
    for qid, topic, eid, question, answer in EXTERNAL:
        if not check_evidence(cur, eid):
            missing.append(eid)
            continue
        ext_rows.append(make_record(qid, "external", "EXTERNAL", topic, eid, question,
                                    answer, "clinicaltrial_literature" if eid.startswith("nct:") else "europepmc_literature"))
    con.close()

    # RESERVE = 110 题中 6 道同源重复 + 4 道构造
    doc = json.loads(Path(QUESTIONS_110).read_text(encoding="utf-8"))
    dup_rows = [q for q in doc["questions"] if q.get("reserve_candidate")]
    if len(dup_rows) != 6:
        print(f"WARNING: 期望 6 道 reserve_candidate，实际 {len(dup_rows)}")
    res_rows = []
    for q in dup_rows:
        rec = dict(q)
        rec["dataset_pack"] = "RESERVE"
        rec["split"] = "reserve"
        rec["reserve_reason"] = q.get("reserve_reason", "duplicate")
        res_rows.append(rec)

    con = sqlite3.connect(str(EVIDENCE_DB))
    cur = con.cursor()
    for qid, topic, eid, question, answer in RESERVE_EXTRA:
        if not check_evidence(cur, eid):
            missing.append(eid)
            continue
        res_rows.append(make_record(qid, "reserve", "RESERVE", topic, eid, question,
                                    answer, "europepmc_literature"))
    con.close()

    if missing:
        print("MISSING evidence:", missing)
        return 1

    ext_doc = {
        "version": "1.0", "created_at": AS_OF_DATE,
        "description": "EXTERNAL 外部基准集 10 题（跨来源泛化：ClinicalTrials 5 + Europe PMC 5），"
                       "只做确定性评分+抽查，不参与 A/B/C/D 主对比",
        "dataset_pack": "EXTERNAL", "split": "external", "count": len(ext_rows),
        "by_source": dict(Counter(r["source"] for r in ext_rows)),
        "questions": ext_rows,
    }
    res_doc = {
        "version": "1.0", "created_at": AS_OF_DATE,
        "description": "RESERVE 备用集 10 题（6 道同源重复题 + 4 道语料库构造题），"
                       "用于替换泄漏/重复/gold 失效/解析失败",
        "dataset_pack": "RESERVE", "split": "reserve", "count": len(res_rows),
        "by_reason": dict(Counter(r.get("reserve_reason", "constructed") for r in res_rows)),
        "questions": res_rows,
    }
    OUT_EXT.write_text(json.dumps(ext_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_RES.write_text(json.dumps(res_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written {OUT_EXT}: {len(ext_rows)} 题")
    print(f"written {OUT_RES}: {len(res_rows)} 题")
    return 0


if __name__ == "__main__":
    sys.exit(main())
