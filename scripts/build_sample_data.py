"""生成离线样例证据库（不依赖网络，用于跑通 B/C/D 管线冒烟测试）

用法： python scripts/build_sample_data.py
生成： data/processed/evidence.jsonl（20 条高血压/血脂主题样例）
真实数据采集见 ingestion/pubmed.py、ingestion/ctg.py（需要网络）。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dataclasses import save_jsonl

SAMPLES = [
    # (source_type, title, text, evidence_level, published, url, pmid/doi)
    ("guideline", "中国高血压防治指南：血压分级与治疗启动阈值",
     "诊室血压测量是诊断高血压的标准方法，诊室血压>=140/90 mmHg 为高血压。降压治疗的目标是降低心脑血管事件风险，多数患者需要长期服药，停药后血压常再次升高。生活方式干预是所有患者的基础治疗。",
     "guideline", "2023-01-01", "https://example.org/guideline/chinese-hypertension-2023", ""),
    ("systematic_review", "降压治疗与心血管事件风险的 meta 分析",
     "对随机对照试验的系统综述显示，收缩压每降低 10 mmHg，主要心血管事件风险显著下降。降压获益主要来自血压降低本身而非特定药物类别。长期坚持治疗是关键。",
     "systematic_review", "2022-06-15", "https://pubmed.example/0001", "pmid_0001"),
    ("rct", "强化降压目标（<130/80 vs <140/90）对结局的影响",
     "随机对照试验比较了强化与标准降压目标，强化降压组主要心血管事件发生率更低，但低血压和晕厥等不良事件略多。结果支持部分高危患者可考虑更低的降压目标。",
     "rct", "2021-03-10", "https://pubmed.example/0002", "pmid_0002"),
    ("rct", "限钠饮食对血压影响的随机对照研究",
     "随机对照试验显示，减少钠摄入可使收缩压平均降低约 4-6 mmHg，对高血压患者效果更明显。DASH 饮食模式配合限钠具有叠加降压效果。",
     "rct", "2020-09-01", "https://pubmed.example/0003", "pmid_0003"),
    ("guideline", "血脂异常基层诊疗指南：LDL-C 目标值分层",
     "根据心血管风险分层设定 LDL-C 目标：极高危患者目标 <1.4 mmol/L，高危 <1.8 mmol/L，中危 <2.6 mmol/L。他汀为一线降脂药物，高强度他汀用于高危患者。",
     "guideline", "2023-05-01", "https://example.org/guideline/lipids-2023", ""),
    ("systematic_review", "他汀类药物一级预防的系统综述",
     "系统综述与 meta 分析表明，他汀用于心血管高危人群的一级预防可显著降低心肌梗死、卒中和心血管死亡风险，获益与基线风险成正比。",
     "systematic_review", "2021-12-01", "https://pubmed.example/0004", "pmid_0004"),
    ("rct", "PCSK9 抑制剂长期结局试验（模拟）",
     "随机对照试验显示，在他汀基础上加用 PCSK9 抑制剂可进一步降低 LDL-C 约 50%-60%，并在长期随访中减少主要不良心血管事件，安全性总体良好。",
     "rct", "2023-08-20", "https://clinicaltrials.example/NCT0001", "nct_0001"),
    ("rct", "地中海饮食与心血管事件：PREDIMED 试验（模拟摘要）",
     "随机试验显示，补充橄榄油或坚果的地中海饮食模式可降低高危人群主要心血管事件风险约 30%。研究强调整体饮食模式而非单一食物。",
     "rct", "2018-06-01", "https://pubmed.example/0005", "pmid_0005"),
    ("cohort", "长期血压控制与靶器官损害的前瞻性队列",
     "前瞻性队列研究显示，长期血压控制不佳与左室肥厚、肾功能下降和颈动脉粥样硬化进展相关，血压达标时间越长，靶器官损害越轻。",
     "cohort", "2019-04-11", "https://pubmed.example/0006", "pmid_0006"),
    ("expert", "医学专家共识：保健品降压宣称不可靠",
     "专家共识指出，目前缺乏高质量随机对照证据支持任何保健品可替代降压药物。声称三个月显著降压的产品通常缺乏对照试验支持，患者应咨询医生。",
     "expert", "2020-01-15", "https://example.org/expert/supplements", ""),
    ("rct", "酒精摄入与心血管健康的孟德尔随机化研究",
     "孟德尔随机化研究提示，酒精摄入与心血管风险之间可能并非简单的保护性 J 型关系，少量饮酒的所谓保护效应部分源于混杂。不推荐为健康目的开始饮酒。",
     "rct", "2022-02-14", "https://pubmed.example/0007", "pmid_0007"),
    ("trial", "脂蛋白a靶向药物 II 期试验进展（模拟）",
     "针对脂蛋白a 的反义寡核苷酸与小干扰RNA 药物在 II 期试验中显示可显著降低 Lp(a) 水平（幅度 60%-90%），心血管结局的 III 期试验正在进行中。",
     "trial", "2024-01-10", "https://clinicaltrials.example/NCT0002", "nct_0002"),
    ("systematic_review", "omega-3 脂肪酸与心血管结局的系统综述",
     "系统综述显示，高剂量二十碳五烯酸（EPA）制剂在特定试验中减少心血管事件，但多数 omega-3 补充试验总体为中性结果，获益可能取决于剂量与剂型。",
     "systematic_review", "2022-10-05", "https://pubmed.example/0008", "pmid_0008"),
    ("rct", "年轻人轻度高血压的自然史与干预试验",
     "研究提示无症状的年轻人血压升高同样与远期心血管风险相关，早期生活方式干预可延缓进展；但不建议仅凭一次测量下结论。",
     "rct", "2019-08-01", "https://pubmed.example/0009", "pmid_0009"),
    ("cohort", "膳食胆固醇摄入与心血管风险队列研究",
     "观察性研究对鸡蛋摄入与心血管风险结论不一致；多数现代队列认为中等量摄入（每日 1 个）对一般人群心血管风险影响很小，但糖尿病患者仍需谨慎。",
     "cohort", "2021-05-20", "https://pubmed.example/0010", "pmid_0010"),
    ("guideline", "生活方式干预的证据等级：饮食、运动与减重",
     "指南推荐生活方式干预为血脂与血压管理的一线基础措施：限钠、地中海饮食、规律有氧运动与减重均有中等以上强度证据；证据等级随干预类型不同而异。",
     "guideline", "2022-07-01", "https://example.org/guideline/lifestyle", ""),
    ("rct", "运动干预对血压的随机对照试验汇总",
     "随机对照试验汇总显示，规律有氧运动可使高血压患者收缩压平均降低 5-8 mmHg，动态抗阻训练也有类似获益，运动强度与依从性是关键。",
     "rct", "2020-11-15", "https://pubmed.example/0011", "pmid_0011"),
    ("trial", "新型降压药物临床试验注册信息（模拟）",
     "ClinicalTrials.gov 登记显示，针对醛固酮合成酶抑制等新靶点的降压药物正在开展 III 期结局试验，主要终点为心血管事件，预计未来两年公布结果。",
     "trial", "2024-03-01", "https://clinicaltrials.example/NCT0003", "nct_0003"),
    ("expert", "高血压管理的教育性说明：何时应就医",
     "高血压为慢性疾病，多数患者需要长期服药维持血压达标。任何保健品或替代疗法宣称可替代标准降压治疗时，均应要求查看随机对照证据并咨询医生。",
     "expert", "2021-01-01", "https://example.org/education/hypertension", ""),
    ("cohort", "血压波动性与心血管预后的观察研究",
     "观察研究提示，血压的长期波动性（visit-to-visit variability）与心血管事件风险独立相关，平稳达标比偶测达标更重要。",
     "cohort", "2020-03-09", "https://pubmed.example/0012", "pmid_0012"),
]


def build() -> str:
    out_path = Path(__file__).resolve().parent.parent / "data/processed/evidence.jsonl"
    records = []
    for i, (src, title, text, level, pub, url, stable_id) in enumerate(SAMPLES, start=1):
        content_hash = hashlib.sha1((title + text).encode()).hexdigest()[:16]
        rec = {
            "id": f"samp_{i:03d}",
            "source_type": src,
            "title": title,
            "text": text,
            "authors": "",
            "published_at": pub,
            "url": url,
            "evidence_level": level,
            "content_hash": content_hash,
        }
        if stable_id.startswith("pmid"):
            rec["pmid"] = stable_id
        elif stable_id.startswith("nct"):
            rec["nct_id"] = stable_id
        records.append(rec)
    save_jsonl(str(out_path), records, mode="w")
    print(f"已生成 {len(records)} 条样例证据 -> {out_path}")
    return str(out_path)


if __name__ == "__main__":
    build()
