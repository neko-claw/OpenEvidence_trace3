"""真实数据采集脚本（需要网络 + API key）

用法：
  python scripts/collect_real.py            # PubMed + ClinicalTrials 采集并写入 evidence.jsonl
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dataclasses import save_jsonl
from ingestion.ctg import collect_ctg
from ingestion.pubmed import collect_pubmed

QUERIES = {
    # 每类题型一个查询，聚焦高血压/血脂；用 MeSH + 文献类型 + 时间窗控制精度
    "hypertension_guideline": '("essential hypertension"[MeSH Terms] OR hypertension[Title/Abstract]) '
                              'AND (guideline[Publication Type] OR consensus[Title]) AND 2022:2025[dp]',
    "hypertension_treatment": 'hypertension[Title/Abstract] AND "blood pressure lowering"[Title/Abstract] '
                               'AND (meta-analysis[Publication Type] OR systematic review[Publication Type])',
    "hypertension_lifestyle": 'hypertension[Title/Abstract] AND (diet OR sodium OR exercise) '
                               'AND randomized controlled trial[Publication Type]',
    "lipids_guideline": '("dyslipidemias"[MeSH Terms] OR "LDL cholesterol"[Title/Abstract]) '
                         'AND (guideline[Publication Type] OR consensus[Title]) AND 2022:2025[dp]',
    "lipids_statins": '(statin[Title/Abstract] OR "HMG-CoA reductase inhibitors"[MeSH Terms]) '
                       'AND (meta-analysis[Publication Type] OR systematic review[Publication Type])',
    "lipids_pcsk9": '(PCSK9[Title/Abstract] OR alirocumab OR evolocumab) '
                     'AND (cardiovascular outcomes OR mortality) AND randomized controlled trial[Publication Type]',
    "lipids_lpa": '(lipoprotein(a)[Title/Abstract] OR "Lp(a)"[Title/Abstract]) AND cardiovascular AND 2023:2025[dp]',
    "hypertension_trials": 'hypertension[Title/Abstract] AND randomized controlled trial[Publication Type] '
                            'AND 2023:2025[dp]',
}

CTG_QUERIES = {
    "hypertension": 'AREA[Condition] "Hypertension" AND AREA[StudyType] "Interventional"',
    "lipids": 'AREA[Condition] "Dyslipidemia" OR AREA[Condition] "Hypercholesterolemia"',
}


def main() -> None:
    out_path = Path("data/processed/evidence.jsonl")
    all_recs = []
    for name, query in QUERIES.items():
        print(f"[PubMed] {name}: {query}")
        try:
            recs = collect_pubmed(query, retmax=15)
            print(f"  -> {len(recs)} 条")
            all_recs.extend(recs)
        except Exception as e:
            print(f"  !! 失败: {e}")
    for name, query in CTG_QUERIES.items():
        print(f"[CTGov] {name}: {query}")
        try:
            recs = collect_ctg(query, page_size=15)
            print(f"  -> {len(recs)} 条")
            all_recs.extend(recs)
        except Exception as e:
            print(f"  !! 失败: {e}")
    # 按 id 去重（保留后写）
    seen = {}
    for r in all_recs:
        seen[r["id"]] = r
    records = list(seen.values())
    save_jsonl(str(out_path), records, mode="w")
    print(f"\n共 {len(records)} 条证据 -> {out_path}（样本数据将被覆盖）")


if __name__ == "__main__":
    main()
