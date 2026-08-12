#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构造 latest_research_trial 分层题（15 TEST + 5 DEV），填补 TEST 题型缺口。

题目全部从 data/processed/evidence.db 中的 2025-2026 真实文献/试验抽象，
gold_source_ids 为语料库中可检索到的证据 ID（保证 Hit@k / Recall@50 可测），
来源标记为 guideline_literature（指南与文献问题抽象），语言为中文（增加中英混合）。

题目形态：中文开放问答题（与 REF 中文题一致，评测走 key_points 打分）。

输出：test_set/latest_research.json（20 题）
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
EVIDENCE_DB = BASE_DIR / "data" / "processed" / "evidence.db"
OUT = BASE_DIR / "test_set" / "latest_research.json"

AS_OF_DATE = "2026-08-11"

# (id, split, topic, question, answer_text, note)
QUESTIONS = [
    # ---------------- TEST 15 ----------------
    ("LATEST-01", "test", "hypertension",
     "英国初级保健中对培哚普利单药治疗后收缩压仍≥145 mmHg 的成人，加用吲达帕胺缓释 1.5 mg "
     "与继续培哚普利单药相比，对收缩压的效果如何？",
     "联合治疗使收缩压显著下降，降幅具有临床意义，优于培哚普利单药（target trial emulation 研究）。",
     "epmc:MED:41656849"),
    ("LATEST-02", "test", "hypertension",
     "对收缩压 130–139 mmHg 且 ASCVD 风险 ≥7.5% 的无症状成人，药物联合饮食的强化降压与仅饮食干预相比，"
     "主要心血管事件结局如何？",
     "强化降压可能带来心血管获益（PRINT-TAHA9 提示有益，试验因资源提前终止）。",
     "epmc:MED:41532016"),
    ("LATEST-03", "test", "dyslipidemia",
     "Meta 分析中，含 Monacolin K 的红曲补充剂对血脂（尤其 LDL-C）的影响如何？",
     "显著降低 LDL-C，可作为他汀不耐受/不愿用他汀或未达标患者的辅助治疗。",
     "epmc:MED:41681060"),
    ("LATEST-04", "test", "hypertension",
     "与常规医生管理+标准血压目标相比，综合血压管理项目联合严格血压目标对产后 7–10 天血压结局的影响？",
     "严格目标+综合管理降低产后收缩压并增加 10 天内启动新降压药的比例（未提高产后复查依从性）。",
     "epmc:MED:41648074"),
    ("LATEST-05", "test", "dyslipidemia",
     "网络 Meta 分析中，有氧、抗阻、HIIT、联合训练对超重/肥胖儿童青少年血脂谱的影响有何差异？",
     "不同运动模式对不同血脂参数有差异化影响，支持表型靶向的运动处方。",
     "epmc:MED:41555426"),
    ("LATEST-06", "test", "dyslipidemia",
     "在老年多病多药患者中，停用他汀与继续用药相比，对心血管事件或全因死亡复合终点的影响？",
     "停药与心血管事件或全因死亡复合终点风险增加相关，主要由非心血管死亡驱动。",
     "epmc:MED:41028982"),
    ("LATEST-07", "test", "dyslipidemia",
     "Meta 分析中，阿托伐他汀对肺部疾病患者炎症标志物、血脂与肺功能的影响？",
     "具有抗炎与降脂作用，并带来轻度呼吸功能与体力表现改善。",
     "epmc:MED:41555409"),
    ("LATEST-08", "test", "dyslipidemia",
     "CLEAR Outcomes 研究中，他汀不耐受的高危患者使用贝培多酸对主要不良心血管事件的影响？",
     "贝培多酸降低主要不良心血管事件风险约 13%，在常见成本效益阈值下具有经济学价值。",
     "epmc:MED:40833562"),
    ("LATEST-09", "test", "dyslipidemia",
     "面向医生的教育干预（GOULD EDU）对 ASCVD 患者 1 年内降脂治疗优化与 LDL-C 达标的影响？",
     "未显著改善降脂治疗优化或 LDL-C 达标，需要新的干预方法。",
     "epmc:MED:41344145"),
    ("LATEST-10", "test", "dyslipidemia",
     "Meta 分析中，核桃补充对成人血脂谱（TC/LDL-C/TG 及 HDL-C）的影响？",
     "显著降低 TC、LDL-C 与 TG；对 HDL-C 与载脂蛋白的影响证据不确定。",
     "epmc:MED:41676011"),
    ("LATEST-11", "test", "hypertension",
     "对未控制高血压的中年成人，整合瑜伽、教育与自我监测的护理干预与常规护理相比的效果？",
     "显著改善血压控制、减轻压力并提高用药依从性（RCT）。",
     "epmc:MED:41660670"),
    ("LATEST-12", "test", "hypertension",
     "粗粮替代主食对血压的影响及其个体差异（肠道菌群/宿主基因）？",
     "粗粮替代可降低血压，效果受基线肠道菌群预测与宿主 ABO 基因型（rs514659）调节。",
     "epmc:MED:41565707"),
    ("LATEST-13", "test", "dyslipidemia",
     "每日适量山核桃摄入对成人心血管风险标志（血脂）的剂量-效应证据？",
     "中等剂量每日山核桃摄入带来心脏保护益处（首次剂量-效应证据）。",
     "epmc:MED:41651071"),
    ("LATEST-14", "test", "dyslipidemia",
     "对家族性高胆固醇血症（FH）患者返回机会性基因筛查结果对 LDL-C 水平的影响（RCT）？",
     "未达统计学显著改善，但提示立即返回结果组有小到中等获益，需更大样本确认。",
     "epmc:MED:41511773"),
    ("LATEST-15", "test", "dyslipidemia",
     "在收治 ACS 的医院中使用降脂决策支持系统（DSS）对 16 周内降脂治疗强化与 LDL-C 达标的影响？",
     "未显著改善降脂强化或 LDL-C 达标，但显示出更早联合降脂治疗的趋势。",
     "epmc:MED:41624559"),
    # ---------------- DEV 5 ----------------
    ("LATEST-16", "dev", "dyslipidemia",
     "在 CVD 风险成人中，以 10%/20%/30% 能量占比补充棉籽油的剂量-效应研究对空腹血脂的影响？",
     "三种剂量均改善空腹血脂，20% 与 30% 剂量效果最佳。",
     "epmc:MED:41238122"),
    ("LATEST-17", "dev", "hypertension",
     "6 周间歇性低氧-高氧暴露对血压、呼吸功能与炎症指标的影响？",
     "与安慰剂相比，血压、呼吸功能、心脏自主神经活性与 CRP 均呈改善趋势。",
     "epmc:MED:41590984"),
    ("LATEST-18", "dev", "dyslipidemia",
     "基于基因型的减重建议与标准减重咨询对体重及血脂指标的长期效果比较？",
     "基因定制建议未带来优于标准咨询的临床结局（减肥管理中）。",
     "epmc:MED:41654718"),
    ("LATEST-19", "dev", "dyslipidemia",
     "能量匹配条件下，低碳水与高碳水饮食对血糖、HDL-C、甘油三酯与 LDL-C 的影响？",
     "低碳水饮食对血糖、HDL-C 与甘油三酯有适度优势，高碳水饮食降低 LDL-C 更明显。",
     "epmc:MED:41493485"),
    ("LATEST-20", "dev", "dyslipidemia",
     "北欧行走（Nordic Walking）对糖尿病前期/糖尿病患者体重、糖化血红蛋白与血脂的影响？",
     "改善体重、HbA1c 与 HDL-C，对收缩压/舒张压无影响。",
     "epmc:MED:41523744"),
]


def main() -> int:
    import sqlite3
    con = sqlite3.connect(str(EVIDENCE_DB))
    cur = con.cursor()
    rows = []
    missing = []
    for qid, split, topic, question, answer, evidence_id in QUESTIONS:
        r = cur.execute("SELECT id FROM evidence WHERE id=?", (evidence_id,)).fetchone()
        if not r:
            missing.append(evidence_id)
            continue
        rows.append({
            "id": qid,
            "source": "GUIDELINE_LITERATURE_ABSTRACT",
            "split": split,
            "dataset_pack": "TEST" if split == "test" else "DEV",
            "rag_category": "easy",  # gold 在语料库可检索 → 基础 RAG 可达
            "audit_status": "pass",
            "answerability": "true",
            "adjudication_status": "manual",
            "adjudication_note": "由 2025-2026 真实文献摘要抽象，gold 为语料库可检索证据",
            "question_type": "latest_research_trial",
            "topic": topic,
            "language": "zh",
            "question": question,
            "options": {},
            "answer": None,
            "answer_text": answer,
            "as_of_date": AS_OF_DATE,
            "source_provenance": "guideline_literature",
            "source_group_id": qid,
            "gold_source_ids": [evidence_id],
            "gold_literature": [evidence_id],
            "gold_verified": False,  # 答案要点人工核对，gold 文献待二次核验后置真
            "gold_verification_status": "pending_review",
            "rubric_version": "0.2-adjudicated",
            "evidence_retrieved": [evidence_id],
        })
    con.close()

    if missing:
        print("MISSING evidence:", missing)
        return 1

    doc = {
        "version": "1.0",
        "created_at": AS_OF_DATE,
        "description": "latest_research_trial 分层补充题（15 TEST + 5 DEV），从语料库 2025-2026 文献抽象",
        "count": len(rows),
        "by_split": dict(Counter(r["split"] for r in rows)),
        "by_topic": dict(Counter(r["topic"] for r in rows)),
        "questions": rows,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written {OUT}: {len(rows)} 题（TEST {sum(1 for r in rows if r['split']=='test')} / "
          f"DEV {sum(1 for r in rows if r['split']=='dev')}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
