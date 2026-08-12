#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工裁定表与修复脚本：把 B2 题集的系统性标注错误一次修正到位。

修复内容（对应 docs/b2_dataset_review.md 的 P0/P1）：
1. 45 道"检索审计失败"的基准题：逐题人工裁定 answerable/question_type/topic；
   rag_category 从 refusal 恢复为 hard（可回答但需优化检索），
   a20495a2（牙科范围外）保持 refusal；
2. 16 道 topic=unknown 逐题裁定；
3. question_type 显式裁定（不再依赖不可靠的关键词分类器）；
4. 补齐 answer_text（MIRAGE/medmcqa 只有答案字母）；
5. 同源重复组标记（medexpqa 354/355/356、41a7eb65/57b1ba32/0489f20c、304/305），
   保留主题，重复题移入 RESERVE（reserve_reason=duplicate）；
6. 更新 refusal 字段（恢复题清除 no_evidence 拒答标注）。

裁定记录落盘：test_set/adjudication_manifest.json（人工审阅留痕）。

用法：
    python scripts/adjudicate_dataset.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
QUESTIONS_110 = BASE_DIR / "test_set" / "questions_110.json"
OUT_MANIFEST = BASE_DIR / "test_set" / "adjudication_manifest.json"

# ---------------------------------------------------------------------------
# 人工裁定表（2026-08-12，审查者基于题面医学内容逐题裁定）
# answerable: true=可回答 / false=不可回答(范围外)
# question_type: stable_knowledge_mechanism | guideline_treatment |
#                latest_research_trial | insufficient_conflict_out_of_scope
# topic: hypertension | dyslipidemia
# ---------------------------------------------------------------------------

# 45 道被误判为 refusal 的基准题（4 道已人工裁定 refusal 的除外）
MISLABELED = {
    # --- MIRAGE/medqa ---
    "0243": {"question_type": "guideline_treatment", "topic": "dyslipidemia",
             "note": "他汀肌病：停药后症状缓解，指南推荐减量再挑战（重启原药低剂量）"},
    "0405": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "他汀（HMG-CoA 还原酶抑制剂）机制：抑制甲羟戊酸生成"},
    "0407": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "烟酸潮红副作用经前列腺素介导，联用阿司匹林预防"},
    "0690": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "贝特/烟酸类可致胆石症（药物不良反应机制）"},
    "0813": {"question_type": "stable_knowledge_mechanism", "topic": "hypertension",
             "note": "老年单纯收缩期高血压机制：大动脉僵硬度增加"},
    "0836": {"question_type": "stable_knowledge_mechanism", "topic": "hypertension",
             "note": "ACEI+保钾利尿剂联用致高钾血症（药物相互作用）"},
    "0859": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "高血压急症静脉用药（硝普钠）血流动力学效应"},
    "0862": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "口服避孕药升高血压：换用非激素类避孕措施"},
    "1050": {"question_type": "guideline_treatment", "topic": "dyslipidemia",
             "note": "考来维仑（胆汁酸螯合剂）需与其他药物间隔服用"},
    "1164": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "老年收缩期高血压初始药物选择（ACEI 等 4 类之一）"},
    "1266": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "糖尿病+未控制高血压：联用二氢吡啶类 CCB（硝苯地平）"},
    # --- MIRAGE/medmcqa（均补 answer_text）---
    "0cd0e1c4-aabe-4ac3-ae2b-83b0633cb376": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "无脂高碳水饮食致肝性 VLDL 合成增加"},
    "0e7917ea-310b-4477-9897-f4901f728448": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "脂蛋白电泳：乳糜微粒不向电荷端迁移"},
    "1a31abe7-fbc1-41bc-b42d-fab66edfef39": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "血浆胆固醇主要运输载体为 LDL"},
    "215befbd-3775-40ea-b2e5-6537ba16ff86": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "HDL 蛋白含量占比最高（载脂蛋白为主）"},
    "4eef4a6b-af8e-4472-9caa-95c1f1a415c8": {"question_type": "stable_knowledge_mechanism", "topic": "hypertension",
             "note": "肾活检洋葱皮样改变：恶性高血压增生性小动脉硬化"},
    "5d0bb1e6-fa95-47e6-811e-abeb5a025ce6": {"question_type": "stable_knowledge_mechanism", "topic": "hypertension",
             "note": "ARB 兼有 PPARγ 激动活性：替米沙坦"},
    "8654832a-f650-4836-82ba-cc59f14e1bb9": {"question_type": "stable_knowledge_mechanism", "topic": "hypertension",
             "note": "噻嗪类利尿剂首日尿钠钾升高、尿钙降低"},
    "93b48788-a643-45c3-ad41-304738ff6f55": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "LDL/HDL 比值是 CVD 风险常用指标"},
    "f87f02ae-e248-473d-9a03-5a866b0dfbee": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "LDL 受体识别 apoB100/apoE、介导内吞、肝内外均有"},
    # --- MedExpQA ---
    "medexpqa-en-train-103-89": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "新发高血压伴空腹血糖偏高：查糖化血红蛋白排除糖尿病"},
    "medexpqa-en-train-104-91": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "家族性高胆固醇血症（纯合型）遗传与表型特征"},
    "medexpqa-en-train-166-82": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "双侧肾动脉狭窄：ACEI/ARB 禁忌（肾功能恶化风险）"},
    "medexpqa-en-train-304-174": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "老年高血压+NSAID：换对乙酰氨基酚以保护血压控制"},
    "medexpqa-en-train-305-174": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "同源重复题（与 304-174 同题改写），移入 RESERVE"},
    # --- MedQA-USMLE ---
    "medqa-usmle-dev-dev-01166": {"question_type": "stable_knowledge_mechanism", "topic": "hypertension",
             "note": "二氢吡啶类 CCB 主要作用于血管平滑肌"},
    "medqa-usmle-train-train-00630": {"question_type": "stable_knowledge_mechanism", "topic": "hypertension",
             "note": "年龄相关收缩压升高机制：动脉顺应性下降"},
    "medqa-usmle-train-train-01657": {"question_type": "stable_knowledge_mechanism", "topic": "hypertension",
             "note": "晨起头痛+打鼾：阻塞性睡眠呼吸暂停继发高血压"},
    "medqa-usmle-train-train-01827": {"question_type": "guideline_treatment", "topic": "dyslipidemia",
             "note": "高危患者强化他汀（阿托伐他汀 40mg）"},
    "medqa-usmle-train-train-01909": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "无合并症 1 级高血压初始治疗：ACEI/ARB/CCB/噻嗪四类均可"},
    "medqa-usmle-train-train-02152": {"question_type": "guideline_treatment", "topic": "dyslipidemia",
             "note": "他汀肌痛：停药后换用普伐他汀（非 CYP3A4 途径）"},
    "medqa-usmle-train-train-02832": {"question_type": "stable_knowledge_mechanism", "topic": "hypertension",
             "note": "妊娠高血压急症用硝苯地平：机制为拮抗 IP3 介导的钙释放"},
    "medqa-usmle-train-train-02901": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "初次就诊重度高血压：ACEI（赖诺普利）"},
    "medqa-usmle-train-train-04650": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "肥胖女性高血压筛查：尿常规（肾脏损害/蛋白尿）"},
    "medqa-usmle-train-train-05346": {"question_type": "stable_knowledge_mechanism", "topic": "hypertension",
             "note": "重度高血压眼底改变：视乳头水肿（恶性高血压）"},
    "medqa-usmle-train-train-06792": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "队列研究归因风险计算：RR=3.0 时归因分值约 67%"},
    "medqa-usmle-train-train-07858": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "肥胖伴高血压生活方式干预：体重下降收益最大"},
    "medqa-usmle-train-train-08100": {"question_type": "stable_knowledge_mechanism", "topic": "dyslipidemia",
             "note": "HDL 向其他脂蛋白传递甘油三酯水解活性：ApoC-II（LPL 激活）"},
    "medqa-usmle-train-train-08497": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "高血压伴肥胖：减重 15kg 为最有效生活方式干预"},
    "medqa-usmle-train-train-08597": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "哮喘+肾功能轻度异常的高血压：CCB（氨氯地平）"},
    "medqa-usmle-train-train-09794": {"question_type": "guideline_treatment", "topic": "dyslipidemia",
             "note": "CKD+DM+高血压伴 LDL 升高：他汀（辛伐他汀）"},
    "medqa-usmle-train-train-10034": {"question_type": "stable_knowledge_mechanism", "topic": "hypertension",
             "note": "老年收缩期高血压机制：动脉顺应性下降"},
    # --- MIRAGE/mmlu ---
    "professional_medicine-105": {"question_type": "guideline_treatment", "topic": "dyslipidemia",
             "note": "高胆固醇+吸烟+早发 CAD 家族史：戒烟为最优先干预"},
    "professional_medicine-202": {"question_type": "guideline_treatment", "topic": "hypertension",
             "note": "青少年血压升高：生活方式干预（运动+减重）首选"},
}

# a20495a2 牙科范围外：保持 refusal，answerable=False（人工裁定）
OUT_OF_SCOPE = {
    "a20495a2-6aba-40db-b41b-fb328e3a8d00": {
        "question_type": "insufficient_conflict_out_of_scope",
        "topic": "hypertension",
        "note": "牙科口腔预防处理，超出高血压/血脂证据助手范围，应拒答",
    },
}

# annotate_question_literature.py 中 REFUSE_OVERRIDE 人工裁定为 refusal 的 4 道基准题
MANUAL_REFUSE = {
    "clinical_knowledge-254": {"question_type": "insufficient_conflict_out_of_scope",
                                "topic": "hypertension",
                                "note": "人工裁定：语料无直接支撑，从 hard 改判 refusal（血压测量体位相关，证据不足）"},
    "4682d46d-f791-48cc-ac4d-b2a73fbb18c4": {"question_type": "insufficient_conflict_out_of_scope",
                                                "topic": "hypertension",
                                                "note": "人工裁定：牙科牙龈收缩线选择，超出证据助手范围"},
    "medqa-usmle-train-train-00782": {"question_type": "insufficient_conflict_out_of_scope",
                                        "topic": "hypertension",
                                        "note": "人工裁定：语料无直接支撑，从 hard 改判 refusal（初始治疗选择，待补 gold 后可恢复）"},
    "medqa-usmle-train-train-01389": {"question_type": "insufficient_conflict_out_of_scope",
                                        "topic": "dyslipidemia",
                                        "note": "人工裁定：语料无直接支撑，从 hard 改判 refusal（他汀肌病处理，待补 gold 后可恢复）"},
}

# topic=unknown 的 16 道（其中部分同时在 MISLABELED 中，取并集覆盖）
UNKNOWN_TOPIC = {
    "1110": {"topic": "dyslipidemia", "question_type": "stable_knowledge_mechanism",
             "note": "青少年跟腱痛+家族早发心梗：家族性高胆固醇血症（测 LDL）"},
    "714eb700-67f2-4ce9-ab0d-ffdf8660ac08": {"topic": "dyslipidemia", "question_type": "stable_knowledge_mechanism",
             "note": "脂蛋白密度：乳糜微粒密度最低"},
    "3a3e9d0e-cf13-4d9c-971f-f9d5cb902994": {"topic": "dyslipidemia", "question_type": "stable_knowledge_mechanism",
             "note": "ApoB-48 存在于乳糜微粒"},
    "0489f20c-a0ce-4251-9eec-e8d5e691a49e": {"topic": "hypertension", "question_type": "stable_knowledge_mechanism",
             "note": "美托洛尔+维拉帕米联用致心动过缓/房室阻滞（同源组 metoprolol-verapamil）"},
    "41a7eb65-1e8e-46ee-8d9a-8544101fe4db": {"topic": "hypertension", "question_type": "guideline_treatment",
             "note": "美托洛尔+维拉帕米联用危险（同源组 metoprolol-verapamil 主题）"},
    "e995894b-0611-4ae2-ae1f-0d35025845ae": {"topic": "hypertension", "question_type": "guideline_treatment",
             "note": "无合并症 2 级高血压首选噻嗪类（氯噻酮）"},
    "57b1ba32-ffad-47ac-b906-d1b6dbca3bc6": {"topic": "hypertension", "question_type": "guideline_treatment",
             "note": "同源重复（metoprolol-verapamil），移入 RESERVE"},
    "c78509b1-d4e3-473c-9020-3a9dc70e5c97": {"topic": "dyslipidemia", "question_type": "guideline_treatment",
             "note": "CAD 一级预防饮食目标（LDL<100、饱和脂肪<7%）"},
    "f608b3a8-f9f0-4096-af64-3fe43798a70f": {"topic": "hypertension", "question_type": "guideline_treatment",
             "note": "妊娠禁忌降压药：ACEI（依那普利）"},
    "REF-003": {"topic": "hypertension", "question_type": "insufficient_conflict_out_of_scope",
                "note": "心梗疑似症状：范围外急诊，应拒答并建议就医"},
    "REF-006": {"topic": "hypertension", "question_type": "insufficient_conflict_out_of_scope",
                "note": "冥想降压量化声称：无充分证据，应拒答/给出证据不足说明"},
    "REF-008": {"topic": "hypertension", "question_type": "insufficient_conflict_out_of_scope",
                "note": "提示注入+伪造 PMID：应拒答并拦截"},
}

# 同源重复组：主题保留，重复题移入 RESERVE（reserve_reason=duplicate）
DUPLICATE_GROUPS = {
    # 布洛芬/对乙酰氨基酚（MedExpQA 304/305）
    "medexpqa-en-train-305-174": {"duplicate_of": "medexpqa-en-train-304-174",
                                  "source_group_id": "medexpqa-304-305"},
    # 美托洛尔+维拉帕米（41a7eb65 为主，0489f20c/57b1ba32 重复）
    "0489f20c-a0ce-4251-9eec-e8d5e691a49e": {"duplicate_of": "41a7eb65-1e8e-46ee-8d9a-8544101fe4db",
                                             "source_group_id": "metoprolol-verapamil"},
    "57b1ba32-ffad-47ac-b906-d1b6dbca3bc6": {"duplicate_of": "41a7eb65-1e8e-46ee-8d9a-8544101fe4db",
                                             "source_group_id": "metoprolol-verapamil"},
    # 孕妇急诊（medexpqa 354/355/356：354 在 dev，355/356 在 test，跨 split 违规）
    "medexpqa-en-dev-354-166": {"duplicate_of": "medexpqa-en-train-355-166",
                                "source_group_id": "medexpqa-pregnant-354-356"},
    "medexpqa-en-train-356-166": {"duplicate_of": "medexpqa-en-train-355-166",
                                  "source_group_id": "medexpqa-pregnant-354-356"},
    # 难治性高血压诊断（medexpqa 548/564-126 同题改写）
    "medexpqa-en-test-548-126": {"duplicate_of": "medexpqa-en-test-564-126",
                                 "source_group_id": "medexpqa-refractory-548-564"},
}

# question_type=unknown 的 19 道逐题裁定
UNKNOWN_TYPE = {
    "0438": {"question_type": "stable_knowledge_mechanism", "note": "噻嗪类利尿剂作用靶点（Na+/Cl- 共转运体）"},
    "b5a8425a-1ddf-41e1-9ffa-c2088ce2897e": {"question_type": "stable_knowledge_mechanism", "note": "LDL 受体肝摄取配体为 apoB-100"},
    "9c7e163e-d22f-43d9-8c77-fb036bc0b064": {"question_type": "guideline_treatment", "note": "ACS 后强化他汀（阿托伐他汀 80mg）二级预防"},
    "dd032c3c-d1fc-42c9-bdbf-09d5fcef74fd": {"question_type": "stable_knowledge_mechanism", "note": "VLDL 在肝脏合成"},
    "297ab88f-0697-406b-8994-332269314289": {"question_type": "stable_knowledge_mechanism", "note": "VLDL 将内源性脂肪酸运往外周组织"},
    "22825590": {"question_type": "latest_research_trial", "note": "PubMedQA 研究问题：行为危险因素与血压转归"},
    "17971187": {"question_type": "latest_research_trial", "note": "PubMedQA 研究问题：儿童胆固醇筛查与家族史"},
    "23d04e70-f243-4c16-a7c4-827051a5b62b": {"question_type": "stable_knowledge_mechanism", "note": "IDL 在血浆中的命运（肝摄取+转 LDL）"},
    "1ea823e8-1b70-4820-96e1-c46d5fd23885": {"question_type": "stable_knowledge_mechanism", "note": "慢性高血压叠加子痫前期的诊断标准"},
    "medqa-usmle-train-train-01779": {"question_type": "guideline_treatment", "note": "贝特类与他汀联用注意肌病/横纹肌溶解风险"},
    "medqa-usmle-train-train-02266": {"question_type": "guideline_treatment", "note": "ESRD 肾性贫血：EPO 治疗（含高血压背景管理）"},
    "medqa-usmle-train-train-06927": {"question_type": "guideline_treatment", "note": "备孕停用 ACEI（致畸），换用妊娠安全药物"},
    "medqa-usmle-dev-dev-00182": {"question_type": "guideline_treatment", "note": "高甘油三酯血症：非诺贝特"},
    "medexpqa-en-train-528-134": {"question_type": "stable_knowledge_mechanism", "note": "隐蔽性高血压（masked hypertension）识别"},
    "medexpqa-en-train-356-166": {"question_type": "stable_knowledge_mechanism", "note": "孕 10 周 160/105：慢性高血压（重复题）"},
    "medexpqa-en-train-355-166": {"question_type": "stable_knowledge_mechanism", "note": "孕 10 周 160/105：慢性高血压"},
    "medexpqa-en-dev-354-166": {"question_type": "stable_knowledge_mechanism", "note": "孕 10 周 160/105：慢性高血压（跨 split 重复题）"},
    "medexpqa-en-test-564-126": {"question_type": "guideline_treatment", "note": "难治性高血压评估：原发性醛固酮增多症筛查（CT/螺内酯）"},
    "medexpqa-en-test-548-126": {"question_type": "guideline_treatment", "note": "难治性高血压评估（同源改写题）"},
}


def main() -> int:
    doc = json.loads(Path(QUESTIONS_110).read_text(encoding="utf-8"))
    questions = doc["questions"]
    by_id = {str(q["id"]): q for q in questions}

    applied = []
    changed_type = Counter()
    changed_topic = Counter()

    for q in questions:
        qid = str(q["id"])
        # 0) 默认可回答性：easy/hard=可回答（auto），refusal=待裁定（pending）——
        #    保证重建后不依赖 annotate_answerability.py 也有一致语义
        if q.get("answerability") is None:
            if q.get("rag_category") in ("easy", "hard"):
                q["answerability"] = "true"
                q["adjudication_status"] = "auto"
                q["adjudication_note"] = "easy/hard：有 gold 的可回答题（检索审计通过/候选命中）"
            else:
                q["answerability"] = "unknown"
                q["adjudication_status"] = "pending_review"
                q["adjudication_note"] = "待人工裁定（默认）"
        # 1) 恢复 45 道误判题
        if qid in MISLABELED:
            m = MISLABELED[qid]
            q["answerability"] = "true"
            q["adjudication_status"] = "manual"
            q["adjudication_note"] = m["note"]
            q["rag_category"] = "hard"  # 可回答但检索审计失败 → 需优化检索
            q["retrieval_audit"] = q.get("audit_status")
            q["question_type"] = m["question_type"]
            q["topic"] = m["topic"]
            q["answerable"] = True
            q["expected_action"] = "ANSWER"
            q["refusal_reason"] = None
            q["refusal_evidence_status"] = None
            q["refusal_annotation"] = {"status": "manual",
                                       "note": "人工裁定：可回答题，检索审计失败≠不可回答"}
            # medmcqa 只有答案字母：补 answer_text
            if not q.get("answer_text") and q.get("answer") and q.get("options"):
                letter = str(q["answer"])[:1].upper()
                q["answer_text"] = (q["options"] or {}).get(letter)
            applied.append({"id": qid, "action": "restore_hard", **m})
            changed_type[m["question_type"]] += 1
            changed_topic[m["topic"]] += 1

        # 2) 范围外题（保持 refusal，显式裁定）
        elif qid in OUT_OF_SCOPE:
            o = OUT_OF_SCOPE[qid]
            q["answerability"] = "false"
            q["adjudication_status"] = "manual"
            q["adjudication_note"] = o["note"]
            q["question_type"] = o["question_type"]
            q["topic"] = o["topic"]
            q["answerable"] = False
            q["expected_action"] = "REFUSE"
            q["refusal_reason"] = "out_of_scope"
            applied.append({"id": qid, "action": "out_of_scope", **o})

        # 2b) 人工裁定 refusal 的基准题（REFUSE_OVERRIDE 4 道）
        elif qid in MANUAL_REFUSE:
            m = MANUAL_REFUSE[qid]
            q["answerability"] = "false"
            q["adjudication_status"] = "manual"
            q["adjudication_note"] = m["note"]
            q["question_type"] = m["question_type"]
            q["topic"] = m["topic"]
            q["answerable"] = False
            q["expected_action"] = "REFUSE"
            q["refusal_reason"] = "no_evidence"
            applied.append({"id": qid, "action": "manual_refuse", **m})

        # 2b2) REF-007：有意设计的冲突证据题，期望 WARN（answerable=true）
        elif qid == "REF-007":
            q["answerability"] = "true"
            q["adjudication_status"] = "manual"
            q["adjudication_note"] = "有意设计：冲突证据题，期望 WARN 而非 REFUSE"
            q["question_type"] = "insufficient_conflict_out_of_scope"
            q["topic"] = q.get("topic") or "hypertension"
            q["answerable"] = True
            q["expected_action"] = "WARN"
            applied.append({"id": qid, "action": "conflict_warn"})

        # 2c) 原始拒答题（REF 系列）
        elif q.get("source") == "ORIGINAL_REFUSAL":
            q["answerability"] = "false"
            q["adjudication_status"] = "manual"
            q["adjudication_note"] = "人工原创拒答题（REF-001~REF-010）"
            q["question_type"] = "insufficient_conflict_out_of_scope"
            if q.get("topic") == "unknown":
                q["topic"] = "hypertension"
            q["answerable"] = False
            q["expected_action"] = q.get("expected_action") or "REFUSE"
            q["refusal_reason"] = q.get("refusal_reason") or "no_evidence"
            applied.append({"id": qid, "action": "original_refusal"})

        # 3) topic=unknown 补全（含上面未覆盖的）
        if qid in UNKNOWN_TOPIC and qid not in MISLABELED and qid not in OUT_OF_SCOPE:
            u = UNKNOWN_TOPIC[qid]
            q["topic"] = u["topic"]
            q["question_type"] = u["question_type"]
            q["adjudication_note"] = u["note"]
            applied.append({"id": qid, "action": "topic_type_fill", **u})
            changed_topic[u["topic"]] += 1

        # 3b) question_type=unknown 逐题裁定
        if qid in UNKNOWN_TYPE and qid not in MISLABELED and qid not in OUT_OF_SCOPE and qid not in UNKNOWN_TOPIC:
            u = UNKNOWN_TYPE[qid]
            q["question_type"] = u["question_type"]
            q["adjudication_note"] = (q.get("adjudication_note") or "") + " " + u["note"]
            applied.append({"id": qid, "action": "question_type_fill", **u})
            changed_type[u["question_type"]] += 1

        # 4) 同源重复组
        if qid in DUPLICATE_GROUPS:
            d = DUPLICATE_GROUPS[qid]
            q["duplicate_of"] = d["duplicate_of"]
            q["source_group_id"] = d["source_group_id"]
            q["reserve_candidate"] = True
            q["reserve_reason"] = "duplicate"
            q["adjudication_note"] = (q.get("adjudication_note") or "") + f" 同源重复，移入 RESERVE"
            applied.append({"id": qid, "action": "duplicate_to_reserve", **d})
        # 主题也写 source_group_id
        for dup, d in DUPLICATE_GROUPS.items():
            if qid == d["duplicate_of"]:
                q["source_group_id"] = d["source_group_id"]
                q["group_main"] = True

    # 更新 manifest 汇总
    doc["adjudication"] = {
        "adjudicated_at": "2026-08-12",
        "reviewer": "B2 review（review/b2-dataset-refactor）",
        "restored_hard": len(MISLABELED),
        "out_of_scope": list(OUT_OF_SCOPE.keys()),
        "topic_filled": len(UNKNOWN_TOPIC),
        "duplicates_to_reserve": list(DUPLICATE_GROUPS.keys()),
    }

    Path(QUESTIONS_110).write_text(
        json.dumps(doc, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n",
        encoding="utf-8")
    Path(OUT_MANIFEST).write_text(
        json.dumps({
            "adjudicated_at": "2026-08-12",
            "reviewer": "B2 review（review/b2-dataset-refactor）",
            "mislabled_restored": applied,
            "out_of_scope": OUT_OF_SCOPE,
            "unknown_topic_filled": UNKNOWN_TOPIC,
            "duplicate_groups": DUPLICATE_GROUPS,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("restored_hard:", len(MISLABELED))
    print("question_type applied:", dict(changed_type))
    print("topic applied:", dict(changed_topic))
    print("out_of_scope:", list(OUT_OF_SCOPE.keys()))
    print("duplicates_to_reserve:", list(DUPLICATE_GROUPS.keys()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
