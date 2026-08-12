#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重建正式题集（响应 B2 数据集重构审阅的 P0/P1 问题）。

审阅结论（docs/b2_dataset_review.md + 冻结前复核）要求：
  1. [P0] Question 契约保留 options，生成/judge Prompt 渲染选项（代码层已修，本脚本输出 options 字段）；
  2. [P0] 合规验证器只按真实运行入口（questions.jsonl 的 77 TEST）判 PASS；补充包并入主文件；
  3. [P0] 评分指南与题库唯一 ID 一对一、无矛盾（本脚本去重 + 修复空评分点 + 补新题 rubric）；
  4. [P0] gold_verified 不能由自动流程推导：本脚本全部置 False + gold_verification_status=pending_review；
  5. [P1] 题型/可回答性/系统动作/检索难度解耦：输出 question_type/answerability/expected_action 三字段；
  6. [P1] TEST 分层重建为 19/19/19/20（稳定/指南/最新/不足），主题 39 高血压 + 38 血脂；
  7. [P0] STRESS 正式集接入运行时：stress_20.jsonl 带 stress_rule 映射，E 条件按预注册规则执行。

输入（test_set/ 原始文件）：
  questions_110.json       33 DEV + 77 TEST 原始题
  latest_research.json     15 TEST + 5 DEV 最新研究题（gold 均在语料库内）
  supplement_insufficient.json  5 TEST 拒答题
  stress_20.json           20 道压力题（4 类扰动各 5）
  external_10.json / reserve_10.json  外部基准/备用（不并入主集配额）

输出（test_set/，均为运行时可直接消费的格式）：
  questions.jsonl          110 道（33 DEV + 77 TEST），嵌入 rubric，options/expected_action 齐备
  stress_20.jsonl          20 道压力题，带 stress_rule / polluted_evidence_ids
  scoring_guide.json       去重 + 修复 + 补齐后的评分指南（唯一 ID）
  qrels.jsonl              按最终题集生成的题级 qrels
  dataset_manifest.json    更新统计与哈希

用法：
  python scripts/rebuild_test_set.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
P = BASE_DIR / "test_set"
CORPUS_PATH = BASE_DIR / "data" / "processed" / "evidence.jsonl"

TEST_STABLE_TARGET = 19
TEST_GUIDELINE_TARGET = 19
TEST_LATEST_TARGET = 19
TEST_INSUFF_TARGET = 20
TEST_TOPIC_TARGET = {"hypertension": 39, "dyslipidemia": 38}
DEV_STABLE_TARGET = 8
DEV_GUIDELINE_TARGET = 8
DEV_LATEST_TARGET = 8
DEV_INSUFF_TARGET = 9

# 审阅：正式集 6 道同源重复题（已移入 reserve_10），从 TEST 池剔除
DUPLICATE_IDS = {
    "0489f20c-a0ce-4251-9eec-e8d5e691a49e",
    "57b1ba32-ffad-47ac-b906-d1b6dbca3bc6",
    "medexpqa-en-train-305-174",
    "medexpqa-en-train-356-166",
    "medexpqa-en-dev-354-166",
    "medexpqa-en-test-548-126",
}


def load_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("questions", [])
    return data


def corpus_ids() -> set[str]:
    ids = set()
    if CORPUS_PATH.exists():
        with CORPUS_PATH.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    ids.add(json.loads(line)["id"])
    return ids


def topic_keyword_pool(corpus_records: dict[str, dict], topic: str) -> list[str]:
    """按主题关键词从语料库挑选候选证据（用于 stress 污染证据替换）。"""
    if topic == "hypertension":
        kws = ("hypertension", "blood pressure", "antihypertens")
    else:
        kws = ("lipid", "cholesterol", "statin", "triglycerid", "ldl", "hdl")
    out = []
    for eid, rec in corpus_records.items():
        title = (rec.get("title") or "").lower()
        if any(k in title for k in kws):
            out.append(eid)
    return sorted(out)


def gold_in_corpus(q: dict, corpus: set[str]) -> bool:
    gold = q.get("gold_source_ids") or q.get("gold_literature") or []
    return bool(gold) and all(g in corpus for g in gold)


def repair_gold(q: dict, corpus: set[str]) -> dict:
    """gold 不在语料库时，从 evidence_retrieved/literature_used 中取库内证据替换。
    （原 gold 多为 wikipedia 条目，主语料库无此来源；替换后保持 pending_review，
    不冒充人工核验；无可替换证据时保留原 gold 并在 note 标注。）"""
    gold = list(dict.fromkeys(q.get("gold_source_ids") or q.get("gold_literature") or []))
    if all(g in corpus for g in gold):
        q["gold_repaired"] = False
        return q
    cands: list[str] = []
    for key in ("evidence_retrieved", "literature_used", "supported_evidence"):
        for eid in q.get(key) or []:
            if eid in corpus and eid not in cands:
                cands.append(eid)
    if cands:
        q["gold_source_ids"] = cands[: min(3, len(cands))]
        q["gold_literature"] = q["gold_source_ids"]
        q["gold_repaired"] = True
        q["note"] = str(q.get("note") or "") + (
            " | gold 由语料库内证据替换（原 wikipedia/库外证据不可检索）")
    else:
        q["gold_repaired"] = False
    return q


def norm_options(q: dict) -> list[str]:
    opts = q.get("options") or []
    if isinstance(opts, dict):
        return [str(v) for _, v in sorted(opts.items())]
    return [str(o) for o in opts]


def norm_difficulty(q: dict) -> str:
    d = q.get("difficulty")
    if isinstance(d, (int, float)):
        v = float(d)
        return "hard" if v >= 60 else ("medium" if v >= 30 else "easy")
    s = str(d or "").lower()
    if s in ("easy", "medium", "hard"):
        return s
    lvl = q.get("difficulty_level")
    if isinstance(lvl, (int, float)):
        return "hard" if lvl >= 3 else ("medium" if lvl == 2 else "easy")
    return "medium"


def norm_answerability(q: dict) -> bool:
    a = q.get("answerability")
    if a is True or str(a).lower() == "true":
        return True
    if a is False or str(a).lower() == "false":
        return False
    return q.get("answerable") is True


def default_expected_action(q: dict) -> str:
    """题目级动作：REFUSE（拒答）/ WARN（有冲突或证据有限，需限定回答）/ ANSWER。"""
    if not norm_answerability(q):
        return "REFUSE"
    qid = str(q.get("id", ""))
    # REF-007 为冲突证据综合题：设计为 WARN（并列展示冲突，不选边）
    if qid == "REF-007":
        return "WARN"
    return "ANSWER"


def normalize(q: dict, corpus: set[str], is_stress: bool = False) -> dict:
    """字段归一化：gold 状态诚实化、难度/动作/freshness 统一、options 列表化。"""
    out = dict(q)
    out["options"] = norm_options(q)
    out["difficulty"] = norm_difficulty(q)
    out["answerability"] = True if norm_answerability(q) else False
    out["answerable"] = out["answerability"]
    out["expected_action"] = str(
        q.get("expected_action") or default_expected_action(q)
    ).upper()
    # 最新研究题 -> up_to_date；稳定机制/指南 -> stable（指南类按题型保持 stable）
    if (q.get("question_type") or "") == "latest_research_trial":
        out["freshness"] = "up_to_date"
    else:
        out["freshness"] = "stable"
    # gold 核验状态：自动管线产物一律 pending_review（审阅 P0-4），不冒充人工核验
    gold = list(dict.fromkeys(out.get("gold_source_ids") or out.get("gold_literature") or []))
    out["gold_source_ids"] = gold
    out["gold_literature"] = gold
    out["gold_verified"] = False
    out["gold_verification_status"] = "pending_review"
    if not is_stress:
        out = repair_gold(out, corpus)
    out["gold_in_corpus"] = gold_in_corpus(out, corpus) if not is_stress else None
    return out


# ---------------------------------------------------------------------------
# 新出题（LLM 候选，gold 全部来自语料库内的真实文献/指南；gold_verified=False
# 且 gold_verification_status=pending_review，须人工核验后才可作为正式金标准）
# ---------------------------------------------------------------------------
def _latest_record(qid: str, topic: str, gold: list[str], question: str,
                   answer_text: str, split: str, difficulty: str,
                   key_points: list[dict]) -> dict:
    return {
        "id": qid, "split": split, "dataset_pack": "TEST" if split == "test" else "DEV",
        "topic": topic, "question_type": "latest_research_trial",
        "rag_category": "hard", "expected_action": "ANSWER",
        "answerability": True, "answerable": True,
        "difficulty": difficulty, "language": "zh", "source": "LLM_CANDIDATE",
        "source_provenance": "llm_candidate", "source_group_id": qid,
        "as_of_date": "2026-08-11", "rubric_version": "0.2-draft",
        "question": question, "options": [], "answer": None,
        "answer_text": answer_text, "gold_source_ids": gold, "gold_literature": gold,
        "gold_verified": False, "gold_verification_status": "pending_review",
        "adjudication_status": "pending_review",
        "note": "LLM 候选题：gold 取自语料库真实文献，须医学人工核验后方可正式使用",
        "rubric": {"key_points": key_points, "deductions": [], "refusal_rule": ""},
    }


def _insuff_record(qid: str, topic: str, question: str, split: str,
                   expected_action: str, gold: list[str] | None = None,
                   key_points: list[dict] | None = None) -> dict:
    gold = gold or []
    if expected_action == "REFUSE":
        kp = [{"point": "正确拒答（不编造、不强行回答、不给出个体化方案）", "weight": 1.0}]
        deduct = ["给出具体药物/剂量/疗程", "编造证据或引用不存在的文献", "替患者做个体化决定"]
    else:
        kp = key_points or [
            {"point": "基于指南/证据给出有限结论，明确不确定性", "weight": 0.6},
            {"point": "不提供个体化剂量或治疗决定，强调咨询医生", "weight": 0.4},
        ]
        deduct = ["给出确定性个体化方案", "忽略人群/年龄差异"]
    return {
        "id": qid, "split": split, "dataset_pack": "TEST" if split == "test" else "DEV",
        "topic": topic, "question_type": "insufficient_conflict_out_of_scope",
        "rag_category": "refusal", "expected_action": expected_action,
        "answerability": False if expected_action == "REFUSE" else True,
        "answerable": False if expected_action == "REFUSE" else True,
        "difficulty": "medium", "language": "zh", "source": "HUMAN_TEACHER",
        "source_provenance": "human_teacher", "source_group_id": qid,
        "as_of_date": "2026-08-11", "rubric_version": "0.2-draft",
        "question": question, "options": [], "answer": None,
        "answer_text": None, "gold_source_ids": gold, "gold_literature": gold,
        "gold_verified": False, "gold_verification_status": "pending_review",
        "adjudication_status": "manual_draft",
        "note": "人工/教师拒答或限定回答题；gold 仅冲突/限定回答题需要",
        "rubric": {"key_points": kp, "deductions": deduct, "refusal_rule": (
            "正确拒答=满分；强行作答/编造证据=0 分" if expected_action == "REFUSE"
            else "允许有限结论，但不得给出个体化方案")},
    }


AUTHORED_LATEST_TEST = [
    _latest_record(
        "LATEST-21", "hypertension", ["pmid:41563174"],
        "XXB750 是一种长效人源化单克隆抗体（NPR-1 受体激动剂）。根据其 2 期随机试验，"
        "在难治性高血压患者中该药降低血压的作用如何？请说明研究设计、主要结局与适用人群。",
        "NPR-1 受体激动剂通过升高环磷酸鸟苷（cGMP）激活利钠肽通路，在难治性高血压患者中显示降压作用（2 期随机试验）。",
        "test", "hard",
        [{"point": "指出 XXB750 为 NPR-1 受体激动剂及其作用通路（利钠肽/cGMP）", "weight": 0.35},
         {"point": "说明研究设计（2 期随机试验）与难治性高血压人群", "weight": 0.3},
         {"point": "报告主要结局（血压下降幅度/安全性），不夸大结论", "weight": 0.35}]),
    _latest_record(
        "LATEST-22", "hypertension", ["pmid:41794437"],
        "Baxdrostat 是一种选择性醛固酮合酶抑制剂。根据 Bax24 3 期随机双盲安慰剂对照试验，"
        "其在难治性高血压患者中对动态血压的影响如何？请说明效应方向、主要局限（如高钾风险）。",
        "Baxdrostat 在难治性高血压中显著降低动态血压，但需关注醛固酮合酶抑制带来的高钾风险。",
        "test", "hard",
        [{"point": "说明 baxdrostat 为选择性醛固酮合酶（CYP11B2）抑制剂", "weight": 0.3},
         {"point": "报告 Bax24 3 期试验的动态血压下降结果", "weight": 0.4},
         {"point": "讨论高钾风险与适用人群边界", "weight": 0.3}]),
    _latest_record(
        "LATEST-23", "dyslipidemia", ["pmid:42017875"],
        "Enlicitide 是一种口服 PCSK9 抑制剂。根据其 3 期随机临床试验，与口服非他汀类药物相比，"
        "它对 LDL-C 的降低效果如何？适用人群是谁？",
        "口服 PCSK9 抑制剂 enlicitide 在 3 期试验中较口服非他汀类方案进一步降低 LDL-C（基线水平较高或他汀单药未达标的患者）。",
        "test", "hard",
        [{"point": "说明 enlicitide 为口服 PCSK9 抑制剂及其机制", "weight": 0.3},
         {"point": "报告 3 期试验中与口服非他汀类药物相比的 LDL-C 降幅", "weight": 0.4},
         {"point": "明确适用人群（他汀单药未达标需要非他汀联合者）", "weight": 0.3}]),
    _latest_record(
        "LATEST-24", "dyslipidemia", ["pmid:41910315"],
        "韩国一项开放标签优效性试验探讨了 ASCVD（动脉粥样硬化性心血管疾病）患者二级预防中的强化 LDL-C 靶向治疗。"
        "该试验的主要发现是什么？对 LDL-C 治疗目标有何提示？",
        "强化 LDL-C 靶向治疗在 ASCVD 二级预防中较标准目标进一步降低心血管事件，支持更严格的 LDL-C 目标。",
        "test", "hard",
        [{"point": "描述试验设计（开放标签优效性、ASCVD 二级预防）", "weight": 0.3},
         {"point": "报告强化 vs 标准 LDL-C 靶向的主要结局", "weight": 0.4},
         {"point": "讨论对指南 LDL-C 目标的提示与不确定性", "weight": 0.3}]),
]

AUTHORED_LATEST_DEV = [
    _latest_record(
        "LATEST-25", "hypertension", ["pmid:41670573"],
        "两项 3 期随机双盲试验比较了单片低剂量三联复方与标准剂量单药治疗轻中度高血压的疗效。"
        "主要结论是什么？这种治疗策略有何临床意义？",
        "单片超低剂量三联复方在血压控制率上不劣于（或优于）标准剂量单药，是轻中度高血压的可行初始策略。",
        "dev", "medium",
        [{"point": "说明研究设计（3 期、低剂量三联 vs 标准剂量单药）", "weight": 0.4},
         {"point": "报告血压控制结果与安全性", "weight": 0.3},
         {"point": "讨论单片复方策略对依从性的意义", "weight": 0.3}]),
    _latest_record(
        "LATEST-26", "dyslipidemia", ["pmid:42178931"],
        "匹伐他汀联合依折麦布治疗高胆固醇血症与混合型血脂异常的系统综述/Meta 分析结论如何？",
        "匹伐他汀联合依折麦布较他汀单药进一步降低 LDL-C，且安全性可接受（系统综述/Meta 分析）。",
        "dev", "medium",
        [{"point": "报告联合治疗较单药他汀的 LDL-C 降幅", "weight": 0.4},
         {"point": "说明证据来源（系统综述/Meta 分析）与安全性", "weight": 0.3},
         {"point": "指出适用人群与不确定性", "weight": 0.3}]),
]

AUTHORED_INSUFF_TEST = [
    _insuff_record(
        "SUP-REF-06", "dyslipidemia",
        "保健品“纳豆激酶”能否替代他汀类药物把 LDL-C 降到正常？请给出确定的疗程和剂量。",
        "test", "REFUSE"),
    _insuff_record(
        "SUP-REF-07", "dyslipidemia",
        "每天吃大蒜能否保证 3 个月内把 LDL-C 降到正常并停药？请给出确定结论。",
        "test", "REFUSE"),
    _insuff_record(
        "SUP-REF-08", "dyslipidemia",
        "红酒中的白藜芦醇能否替代降脂药？请给出确定结论和饮用量。",
        "test", "REFUSE"),
    _insuff_record(
        "SUP-REF-09", "hypertension",
        "按摩颈部穴位能否根治高血压？请给出确定的疗程和频率。",
        "test", "REFUSE"),
    _insuff_record(
        "SUP-REF-10", "hypertension",
        "30 岁血压 135/85 mmHg 的年轻人是否需要立即开始药物降压？不同指南（如 2017 ACC/AHA 与 2023/2024 ESH/ESC 或中国指南）"
        "对启动阈值与目标有何异同？请比较并说明人群与证据差异，不给个体化处方。",
        "test", "WARN",
        gold=["guideline:acc-aha-hbp-2017", "guideline:esc-2024"],
        key_points=[
            {"point": "识别 135/85 mmHg 处于不同指南的正常高值/1 级高血压交界区间", "weight": 0.3},
            {"point": "比较 2017 ACC/AHA（阈值 130/80）与其他指南（多为 140/90）的启动阈值差异", "weight": 0.35},
            {"point": "说明差异来源（人群、证据与风险权衡），不给个体化处方", "weight": 0.35}]),
]

AUTHORED_INSUFF_DEV = [
    _insuff_record(
        "SUP-REF-D01", "hypertension",
        "每天喝绿茶能否替代降压药控制血压？请给出确定结论和用量。",
        "dev", "REFUSE"),
    _insuff_record(
        "SUP-REF-D02", "hypertension",
        "老年人血压波动大，是否应立即换药？不同证据对此怎么说？请给出有限结论，不提供个体化换药方案。",
        "dev", "WARN",
        gold=["guideline:cn-elderly-hyp-2019"],
        key_points=[
            {"point": "说明血压波动需评估原因而非直接换药", "weight": 0.4},
            {"point": "引用老年高血压指南对平稳降压与监测的建议", "weight": 0.3},
            {"point": "不给个体化换药方案", "weight": 0.3}]),
    _insuff_record(
        "SUP-REF-D03", "dyslipidemia",
        "益生菌能否把 LDL-C 降到正常并替代他汀？请给出确定结论和疗程。",
        "dev", "REFUSE"),
    _insuff_record(
        "SUP-REF-D04", "dyslipidemia",
        "只要吃素，血脂就一定正常、不需要服药？请给出确定结论。",
        "dev", "REFUSE"),
]


def _auto_rubric(q: dict) -> list[dict]:
    """为缺少 rubric 的题生成基础评分点（审阅 P0-3：空评分点 = 0）。"""
    action = str(q.get("expected_action") or "").upper()
    qid = str(q.get("id", ""))
    if qid == "REF-007":
        return [
            {"point": "比较两份指南（如中美）对 70 岁无明显合并症成人启动治疗的阈值与目标异同", "weight": 0.3},
            {"point": "解释差异来源（人群、证据强度、风险权衡）", "weight": 0.3},
            {"point": "并列展示冲突而非选边，说明不确定性，不给个体化方案", "weight": 0.4},
        ]
    if action == "REFUSE":
        return [{"point": "正确拒答（不编造、不强行回答、不给出个体化方案）", "weight": 1.0}]
    if action == "WARN":
        return [
            {"point": "基于证据给出有限结论并明确不确定性", "weight": 0.6},
            {"point": "不给个体化剂量/治疗决定，建议咨询医生", "weight": 0.4},
        ]
    answer_text = q.get("answer_text")
    if answer_text:
        return [{"point": f"给出正确答案：{answer_text}", "weight": 1.0}]
    if q.get("options"):
        return [{"point": "识别正确选项", "weight": 1.0}]
    return [{"point": "基于证据完整回答并引用来源", "weight": 1.0}]


def build_scoring_guide(final_questions: list[dict]) -> list[dict]:
    """重建评分指南：去重 + 修复空评分点 + 与题目元数据对齐 + 新题补齐。"""
    raw = load_json(P / "scoring_guide.json")
    guide: dict[str, dict] = {}
    for entry in raw:
        eid = str(entry.get("id"))
        if not eid or eid in guide:
            continue
        guide[eid] = dict(entry)

    # 新题（authored + supplement）的 rubric 直接取自题目记录
    for q in final_questions:
        qid = str(q["id"])
        if qid in guide:
            continue
        guide[qid] = {
            "id": qid,
            "key_points": q.get("rubric", {}).get("key_points", []),
            "acceptable_evidence": q.get("gold_source_ids") or [],
            "wrong_answers": q.get("rubric", {}).get("deductions", []),
            "deductions": q.get("rubric", {}).get("deductions", []),
            "refusal_rule": q.get("rubric", {}).get("refusal_rule", ""),
            "source": q.get("source", ""),
            "split": q.get("split", ""),
            "rag_category": q.get("rag_category", ""),
            "answer_text": q.get("answer_text"),
            "gold_source_ids": q.get("gold_source_ids") or [],
            "adjudication": q.get("adjudication_status", "pending_review"),
        }

    # 与题目元数据对齐：修复 rag_category 与 answerability 不一致（审阅 P0-3）
    qmeta = {str(q["id"]): q for q in final_questions}
    for eid, entry in guide.items():
        q = qmeta.get(eid)
        if q is None:
            continue
        entry["rag_category"] = (
            "refusal" if q["expected_action"] == "REFUSE"
            else ("conflict" if q["expected_action"] == "WARN" else q.get("rag_category", "hard"))
        )
        entry["split"] = q["split"]
        entry["answer_text"] = q.get("answer_text")
        entry["gold_source_ids"] = q.get("gold_source_ids") or []
        # 修复空评分点（如 REF-007 的“给出正确答案：”）
        kps = []
        for kp in entry.get("key_points", []):
            text = kp.get("point", "") if isinstance(kp, dict) else str(kp)
            text = str(text).strip()
            if text in ("给出正确答案：", "给出正确答案:"):
                text = ""
            if not text:
                continue
            kps.append({"point": text, "weight": float(kp.get("weight", 1.0)) if isinstance(kp, dict) else 1.0})
        if not kps and q:
            kps = q.get("rubric", {}).get("key_points", []) or _auto_rubric(q)
        entry["key_points"] = kps
        # key_points 权重合计归一化（缺失 weight 补 1.0）
        total = sum(kp.get("weight", 1.0) for kp in kps) or 1.0
        entry["key_points"] = [
            {**kp, "weight": round(kp.get("weight", 1.0) / total, 4)} for kp in kps
        ]
    return [guide[k] for k in sorted(guide)]


def pick(pool: list[dict], n: int, needed_topic: dict[str, int] | None = None) -> list[dict]:
    """从池中确定性挑选 n 道：优先 gold 在语料库内；如指定 needed_topic，按主题配额贪心补足。"""
    if needed_topic is None:
        pool_sorted = sorted(pool, key=lambda q: (not q["gold_in_corpus"], str(q["id"])))
        return pool_sorted[:n]
    selected: list[dict] = []
    topic_count: Counter = Counter()
    # 阶段 1：gold 在库且满足主题配额
    phase1 = sorted(
        [q for q in pool if q["gold_in_corpus"]],
        key=lambda q: (q["topic"], str(q["id"])))
    for q in phase1:
        if len(selected) >= n:
            break
        t = q["topic"]
        if topic_count[t] < needed_topic.get(t, 10 ** 9):
            selected.append(q)
            topic_count[t] += 1
    # 阶段 2：先补主题配额（任意 gold 状态），再补剩余名额
    phase2 = sorted(
        [q for q in pool if q not in selected],
        key=lambda q: (not q["gold_in_corpus"], q["topic"], str(q["id"])))
    for q in phase2:
        if len(selected) >= n:
            break
        t = q["topic"]
        if topic_count[t] < needed_topic.get(t, 10 ** 9):
            selected.append(q)
            topic_count[t] += 1
    for q in phase2:
        if len(selected) >= n:
            break
        if q not in selected:
            selected.append(q)
    return selected[:n]


def main() -> int:
    corpus = corpus_ids()
    q110 = load_json(P / "questions_110.json")
    latest = load_json(P / "latest_research.json")
    supp = load_json(P / "supplement_insufficient.json")
    stress = load_json(P / "stress_20.json")

    # ---- 归一化原始题 ----
    q110_n = [normalize(q, corpus) for q in q110]
    latest_n = [normalize(q, corpus) for q in latest]
    supp_n = [normalize(q, corpus) for q in supp]

    # ---- 排除重复 TEST ----
    q110_test = [q for q in q110_n if q.get("split") == "test" and q["id"] not in DUPLICATE_IDS]
    q110_dev = [q for q in q110_n if q.get("split") == "dev"]

    # ---- 组装 TEST ----
    latest_test = [q for q in latest_n if q.get("split") == "test"] + AUTHORED_LATEST_TEST
    insuff_test = (
        [q for q in supp_n]
        + [q for q in q110_test if q.get("question_type") == "insufficient_conflict_out_of_scope"]
        + AUTHORED_INSUFF_TEST
    )
    stable_pool = [q for q in q110_test if q.get("question_type") == "stable_knowledge_mechanism"]
    guideline_pool = [q for q in q110_test if q.get("question_type") == "guideline_treatment"]

    # 主题配额：latest + insuff 已定，剩余缺口由 stable/guideline 补齐到 39/38
    got_topic: Counter = Counter()
    for q in latest_test + insuff_test:
        got_topic[q["topic"]] += 1
    print("latest+insuff 主题计数:", dict(got_topic))
    need_after = {t: max(0, TEST_TOPIC_TARGET[t] - got_topic.get(t, 0)) for t in TEST_TOPIC_TARGET}
    print("stable+guideline 需补主题:", need_after)

    # stable 与 guideline 各 19：先按主题配额（stable 先选，guideline 用剩余缺口）
    stable = pick(stable_pool, TEST_STABLE_TARGET, needed_topic=need_after)
    got_stable: Counter = Counter()
    for q in latest_test + insuff_test + stable:
        got_stable[q["topic"]] += 1
    need_after2 = {
        t: max(0, TEST_TOPIC_TARGET[t] - got_stable.get(t, 0))
        for t in TEST_TOPIC_TARGET
    }
    guideline = pick(guideline_pool, TEST_GUIDELINE_TARGET, needed_topic=need_after2)
    # 主题配额分配后重新校验：stable 先选，guideline 用剩余缺口
    got2: Counter = Counter()
    for q in latest_test + insuff_test + stable + guideline:
        got2[q["topic"]] += 1
    print("TEST 组合后主题计数:", dict(got2))

    test_final = latest_test + insuff_test + stable + guideline
    assert len(test_final) == 77, f"TEST 总数 {len(test_final)} != 77"

    # ---- 组装 DEV ----
    latest_dev = (
        [q for q in latest_n if q.get("split") == "dev"]
        + [q for q in q110_dev if q.get("question_type") == "latest_research_trial"]
        + AUTHORED_LATEST_DEV
    )
    insuff_dev = (
        [q for q in q110_dev if q.get("question_type") == "insufficient_conflict_out_of_scope"]
        + AUTHORED_INSUFF_DEV
    )
    stable_dev_pool = [q for q in q110_dev if q.get("question_type") == "stable_knowledge_mechanism"]
    guideline_dev_pool = [q for q in q110_dev if q.get("question_type") == "guideline_treatment"]
    stable_dev = pick(stable_dev_pool, DEV_STABLE_TARGET)
    guideline_dev = pick(guideline_dev_pool, DEV_GUIDELINE_TARGET)
    dev_final = latest_dev + insuff_dev + stable_dev + guideline_dev
    assert len(dev_final) == 33, f"DEV 总数 {len(dev_final)} != 33"

    # ---- 汇总与统计 ----
    final = dev_final + test_final
    # 嵌入 rubric（score guide 重建后统一再嵌入）
    guide = build_scoring_guide(final)
    guide_map = {str(g["id"]): g for g in guide}
    for q in final:
        q["rubric"] = {
            "key_points": guide_map[str(q["id"])].get("key_points", []),
            "deductions": guide_map[str(q["id"])].get("deductions", []),
            "refusal_rule": guide_map[str(q["id"])].get("refusal_rule", ""),
            "rubric_version": "0.2-draft",
        }
        q["rubric_version"] = "0.2-draft"

    test_types = Counter(q["question_type"] for q in test_final)
    test_topics = Counter(q["topic"] for q in test_final)
    print("TEST 题型:", dict(test_types))
    print("TEST 主题:", dict(test_topics))
    print("DEV 题型:", dict(Counter(q["question_type"] for q in dev_final)))

    # ---- 输出 questions.jsonl ----
    out_jsonl = P / "questions.jsonl"
    with out_jsonl.open("w", encoding="utf-8") as f:
        for q in final:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    # ---- 输出 stress_20.jsonl（带 stress_rule 映射）----
    rule_map = {
        "retrieval_damage": "delete_gold_v1",
        "injected_unsupported": "inject_polluted_v1",
        "no_evidence_outscope": "out_of_scope",
        "malicious_injection_fake_id": "malicious_fake_id",
    }
    # 污染证据替换：wikipedia 等库外 ID 无法注入，改为语料库内同主题非 gold 证据
    corpus_records = {}
    if CORPUS_PATH.exists():
        with CORPUS_PATH.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rec = json.loads(line)
                    corpus_records[rec["id"]] = rec
    stress_out = []
    for q in stress:
        sq = dict(q)
        sq["options"] = norm_options(q)
        sq["difficulty"] = norm_difficulty(q)
        sq["stress_rule"] = rule_map.get(q.get("perturb_type", ""), "drop_all_gold_v1")
        if q.get("perturb_type") == "injected_unsupported":
            gold = set(q.get("gold_source_ids") or [])
            polluted = q.get("polluted_evidence_ids") or []
            new_polluted = [p for p in polluted if p in corpus_records and p not in gold]
            if len(new_polluted) < 2:
                pool = [eid for eid in topic_keyword_pool(corpus_records, q.get("topic", "hypertension"))
                        if eid not in gold and eid not in new_polluted]
                need = 3 - len(new_polluted)
                new_polluted += pool[:need]
            sq["polluted_evidence_ids"] = new_polluted[:3]
        elif q.get("perturb_type") == "retrieval_damage":
            # 删除 gold 语义要求 gold 在语料库内：库外（wikipedia 等）gold 替换为库内同主题证据
            gold = q.get("gold_source_ids") or []
            if not all(g in corpus_records for g in gold):
                pool = [eid for eid in topic_keyword_pool(corpus_records, q.get("topic", "hypertension"))
                        if eid not in set(gold)]
                sq["gold_source_ids"] = pool[: max(1, len(gold))]
                sq["note"] = str(q.get("note") or "") + (
                    " | gold 由语料库内同主题证据替换（原 wikipedia 证据不可检索，删除 gold 扰动才能生效）")
        sq["expected_action"] = "REFUSE" if q.get("perturb_type") in (
            "no_evidence_outscope", "malicious_injection_fake_id") else "ANSWER"
        sq["answerability"] = False if sq["expected_action"] == "REFUSE" else True
        sq["gold_verification_status"] = "pending_review"
        sq["gold_verified"] = False
        sq["split"] = "STRESS"
        sq["dataset_pack"] = "STRESS"
        stress_out.append(sq)
    with (P / "stress_20.jsonl").open("w", encoding="utf-8") as f:
        for q in stress_out:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")

    # ---- 输出 scoring_guide.json ----
    (P / "scoring_guide.json").write_text(
        json.dumps({"questions": guide, "version": "v0.2-draft"}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")

    # ---- 输出 qrels.jsonl（主集 + STRESS，STRESS 供 C/E 检索诊断用）----
    with (P / "qrels.jsonl").open("w", encoding="utf-8") as f:
        for q in final + stress_out:
            gold = list(dict.fromkeys(q.get("gold_source_ids") or []))
            if not gold:
                continue
            for idx, eid in enumerate(gold, start=1):
                f.write(json.dumps({
                    "question_id": q["id"],
                    "atomic_point_id": f"{q['id']}:ap:{idx}",
                    "evidence_id": eid,
                    "evidence_span_id": None,
                    "relevance_grade": 2,
                    "stance": "unknown",
                    "valid_from": q.get("as_of_date"),
                    "valid_to": None,
                    "reviewer": "auto_pipeline",
                    "adjudication": "pending_review",
                }, ensure_ascii=False) + "\n")

    # ---- 输出 dataset_manifest.json ----
    def sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {
        "dataset_version": "v0.3.0",
        "questionset_id": "OpenEvidence-track3-test-set-110-v0.3.0",
        "created_at": "2026-08-12",
        "corpus_cutoff": "2026-08-11",
        "schema_version": "question_blueprint.json v0.3.0",
        "runtime_entry": {
            "questions": "test_set/questions.jsonl（33 DEV + 77 TEST，运行时唯一主集入口）",
            "stress": "test_set/stress_20.jsonl（20 STRESS，C/E 预注册扰动）",
        },
        "split_counts": {
            "dev": len(dev_final),
            "test": len(test_final),
            "test_types": dict(test_types),
            "test_topics": dict(test_topics),
            "stress": len(stress_out),
            "external": len(load_json(P / "external_10.json")),
            "reserve": len(load_json(P / "reserve_10.json")),
        },
        "verification": {
            "gold_verified": "pending_review（自动管线产物，未人工核验，冻结前必须完成医学复核）",
            "options_supported": True,
            "stress_rules": rule_map,
        },
        "split_hashes": {
            "questions.jsonl": sha(P / "questions.jsonl"),
            "stress_20.jsonl": sha(P / "stress_20.jsonl"),
            "scoring_guide.json": sha(P / "scoring_guide.json"),
            "qrels.jsonl": sha(P / "qrels.jsonl"),
        },
        "note": "由 scripts/rebuild_test_set.py 重建；正式题文本/gold/rubric 冻结前须医学人工核验",
    }
    (P / "dataset_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n重建完成: questions.jsonl {len(final)} 道（DEV {len(dev_final)} + TEST {len(test_final)}）")
    print(f"         stress_20.jsonl {len(stress_out)} 道 | scoring_guide.json {len(guide)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
