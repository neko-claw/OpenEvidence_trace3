"""一键构建高质量证据库：采集(26查询) → 相关性过滤 → 去重 → 证据等级标注 → 统计

用法： python scripts/build_kb.py [--retmax 20] [--target 300]
输出： data/processed/evidence.jsonl（覆盖旧库，旧库请先备份）
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dataclasses import save_jsonl
from ingestion.ctg import collect_ctg
from ingestion.filters import is_relevant
from ingestion.pubmed import collect_pubmed
from scripts.annotate_evidence import infer_level

# 25 个 PubMed 查询，覆盖高血压/血脂各子主题（设计原则：PICO + 文献类型 + 时间窗）
PUBMED_QUERIES = {
    # ---- 高血压 ----
    "htn_guideline": '("essential hypertension"[MeSH Terms] OR hypertension[Title/Abstract]) '
                     'AND (guideline[Publication Type] OR consensus[Title]) AND 2022:2025[dp]',
    "htn_treatment_meta": 'hypertension[Title/Abstract] AND "blood pressure lowering"[Title/Abstract] '
                          'AND (meta-analysis[Publication Type] OR systematic review[Publication Type])',
    "htn_lifestyle": 'hypertension[Title/Abstract] AND (diet OR sodium OR exercise OR weight) '
                     'AND randomized controlled trial[Publication Type]',
    "htn_trials_2023": 'hypertension[Title/Abstract] AND randomized controlled trial[Publication Type] '
                       'AND 2023:2025[dp]',
    "htn_elderly": '(hypertension[Title/Abstract] OR "blood pressure"[Title/Abstract]) AND elderly '
                   'AND randomized controlled trial[Publication Type]',
    "htn_salt": '(sodium[Title/Abstract] OR salt[Title/Abstract]) AND ("blood pressure"[Title/Abstract]) '
                'AND randomized controlled trial[Publication Type]',
    "htn_combination": '(hypertension[Title/Abstract]) AND ("combination therapy"[Title/Abstract] OR "fixed-dose combination"[Title/Abstract]) '
                       'AND randomized controlled trial[Publication Type]',
    "htn_ambulatory": '"ambulatory blood pressure" AND (hypertension OR "blood pressure") '
                      'AND 2021:2025[dp]',
    "htn_renin": '("RAAS inhibitor"[Title/Abstract] OR "angiotensin"[Title/Abstract] OR "aldosterone"[Title/Abstract]) '
                 'AND hypertension[Title/Abstract] AND randomized controlled trial[Publication Type]',
    "htn_adherence": '(antihypertensive[Title/Abstract]) AND (adherence[Title/Abstract] OR compliance[Title/Abstract]) '
                     'AND (review[Publication Type])',
    "htn_young": '("young adults"[Title/Abstract] OR "young people"[Title/Abstract]) '
                 'AND (hypertension[Title/Abstract] OR "blood pressure"[Title/Abstract])',
    "htn_diabetes": '(hypertension[Title/Abstract] OR "blood pressure"[Title/Abstract]) AND diabetes '
                    'AND randomized controlled trial[Publication Type] AND 2020:2025[dp]',
    "htn_stroke": '"blood pressure" AND (stroke[Title/Abstract]) '
                  'AND (meta-analysis[Publication Type] OR systematic review[Publication Type])',
    "htn_whitecoat": '"white coat"[Title/Abstract] AND hypertension AND 2020:2025[dp]',
    # ---- 血脂 ----
    "lipids_guideline": '("dyslipidemias"[MeSH Terms] OR "LDL cholesterol"[Title/Abstract]) '
                        'AND (guideline[Publication Type] OR consensus[Title]) AND 2022:2025[dp]',
    "lipids_statins": '(statin[Title/Abstract] OR "HMG-CoA reductase inhibitors"[MeSH Terms]) '
                      'AND (meta-analysis[Publication Type] OR systematic review[Publication Type])',
    "lipids_pcsk9": '(PCSK9[Title/Abstract] OR alirocumab OR evolocumab) '
                    'AND (cardiovascular outcomes OR mortality) AND randomized controlled trial[Publication Type]',
    "lipids_lpa": '(lipoprotein(a)[Title/Abstract] OR "Lp(a)"[Title/Abstract]) AND cardiovascular AND 2023:2025[dp]',
    "lipids_triglyceride": '(triglyceride[Title/Abstract] OR hypertriglyceridemia[Title/Abstract]) '
                           'AND cardiovascular AND (meta-analysis[Publication Type] OR randomized controlled trial[Publication Type])',
    "lipids_ezetimibe": '(ezetimibe[Title/Abstract]) AND (cholesterol[Title/Abstract] OR "LDL"[Title/Abstract]) '
                        'AND randomized controlled trial[Publication Type]',
    "lipids_nonstatin": '"non-statin"[Title/Abstract] AND ("LDL"[Title/Abstract] OR lipid[Title/Abstract]) '
                        'AND (meta-analysis[Publication Type] OR systematic review[Publication Type])',
    "lipids_diet": '(diet[Title/Abstract] OR eggs[Title/Abstract] OR "dietary pattern"[Title/Abstract]) '
                   'AND (cholesterol[Title/Abstract] OR "blood lipids"[Title/Abstract]) '
                   'AND (randomized controlled trial[Publication Type] OR cohort study[Publication Type])',
    "lipids_familial": '"familial hypercholesterolemia"[Title/Abstract] AND (management[Title/Abstract] OR guideline[Title/Abstract])',
    "lipids_statin_intolerance": '"statin intolerance"[Title/Abstract] OR "statin-associated"[Title/Abstract] AND management',
    "lipids_metabolic": '(metabolic syndrome[Title/Abstract]) AND (lipid[Title/Abstract] OR cholesterol[Title/Abstract]) '
                        'AND (guideline[Publication Type] OR systematic review[Publication Type])',
}

CTG_QUERIES = {
    "htn_trials": 'AREA[Condition] "Hypertension" AND AREA[StudyType] "Interventional"',
    "lipids_trials": 'AREA[Condition] "Dyslipidemia" OR AREA[Condition] "Hypercholesterolemia" OR AREA[Condition] "Hyperlipidemia"',
}


def collect_all(retmax: int) -> list[dict]:
    all_recs: list[dict] = []
    for name, query in PUBMED_QUERIES.items():
        try:
            recs = collect_pubmed(query, retmax=retmax)
            print(f"  [PubMed] {name:22s} -> {len(recs)} 条")
            all_recs.extend(recs)
        except Exception as e:
            print(f"  [PubMed] {name:22s} !! {e}")
    for name, query in CTG_QUERIES.items():
        try:
            recs = collect_ctg(query, page_size=retmax)
            print(f"  [CTGov ] {name:22s} -> {len(recs)} 条")
            all_recs.extend(recs)
        except Exception as e:
            print(f"  [CTGov ] {name:22s} !! {e}")
    return all_recs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retmax", type=int, default=20, help="每个查询的召回上限")
    ap.add_argument("--target", type=int, default=300, help="目标条数（用于提示）")
    args = ap.parse_args()

    print(f"阶段1/4 采集（{len(PUBMED_QUERIES)} 个 PubMed 查询 + {len(CTG_QUERIES)} 个试验查询, retmax={args.retmax}）")
    raw = collect_all(args.retmax)
    print(f"\n原始采集共 {len(raw)} 条")

    print("阶段2/4 相关性过滤")
    kept, dropped = [], 0
    drop_reasons: Counter = Counter()
    for r in raw:
        ok, reason = is_relevant(r.get("title", ""), r.get("text", ""))
        if ok:
            kept.append(r)
        else:
            dropped += 1
            if "排除词" in reason:
                drop_reasons["排除词(无关主题)"] += 1
            else:
                drop_reasons["无关键词命中"] += 1
    print(f"  保留 {len(kept)} 条，剔除 {dropped} 条（{dict(drop_reasons)}）")

    print("阶段3/4 去重 + 证据等级标注")
    seen: dict[str, dict] = {}
    for r in kept:
        r["evidence_level"] = infer_level(r.get("title", ""), r.get("text", ""))
        seen[r["id"]] = r
    records = list(seen.values())
    print(f"  去重后 {len(records)} 条")

    print("阶段4/4 写入")
    save_jsonl("data/processed/evidence.jsonl", records, mode="w")
    print(f"  已写入 data/processed/evidence.jsonl（{len(records)} 条，目标 {args.target}）")
    print("\n=== 最终构成 ===")
    print("  来源:", dict(Counter(r["source_type"] for r in records)))
    print("  等级:", dict(Counter(r["evidence_level"] for r in records)))


if __name__ == "__main__":
    main()
