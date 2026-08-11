"""B1 准备任务：从第一部分数据集生成离线 fixture（确定性、可复现）。

产物：
- data/processed/fixtures/evidence_fixture.jsonl   20 条 Evidence（覆盖 4 来源/多证据等级/双主题）
- data/processed/fixtures/sample_questions.jsonl   5 开发题 + 5 压力题样例（蓝图样例，非正式题）

用途：B3 在 A 组接口就绪前用固定 fixture 开发实验框架（实施规划 7.3）。
"""
from __future__ import annotations

import json
import hashlib
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion import config  # noqa: E402


def pick_evidence(conn, where, limit, seed_salt):
    """确定性抽样：按 sha256(id+seed_salt) 排序取前 limit 条（可复现）。"""
    rows = conn.execute(
        f"SELECT * FROM evidence WHERE {where} AND abstract_or_chunk IS NOT NULL "
        f"AND LENGTH(abstract_or_chunk) > 200 LIMIT 40"
    ).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM evidence LIMIT 1").description]
    recs = [dict(zip(cols, r)) for r in rows]
    recs.sort(key=lambda r: hashlib.sha256((r["id"] + seed_salt).encode()).hexdigest())
    return recs[:limit]


def main():
    fixtures_dir = config.DATA_PROCESSED / "fixtures"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(config.EVIDENCE_DB))
    picks = []
    # 1) 指南（回填成功的）
    picks += pick_evidence(conn, "record_kind='guideline' AND extras LIKE '%true%'", 2, "g")
    # 2) 系统综述（双主题各一）
    picks += pick_evidence(conn, "record_kind='abstract' AND evidence_level='systematic-review' AND topics LIKE '%hypertension%'", 1, "s1")
    picks += pick_evidence(conn, "record_kind='abstract' AND evidence_level='systematic-review' AND topics LIKE '%lipids%'", 1, "s2")
    # 3) meta-analysis（双主题）
    picks += pick_evidence(conn, "record_kind='abstract' AND evidence_level='meta-analysis' AND topics LIKE '%hypertension%'", 1, "m1")
    picks += pick_evidence(conn, "record_kind='abstract' AND evidence_level='meta-analysis' AND topics LIKE '%lipids%'", 1, "m2")
    # 4) RCT（双主题）
    picks += pick_evidence(conn, "record_kind='abstract' AND evidence_level='rct' AND topics LIKE '%hypertension%'", 1, "r1")
    picks += pick_evidence(conn, "record_kind='abstract' AND evidence_level='rct' AND topics LIKE '%lipids%'", 1, "r2")
    # 5) 临床试验（不同状态）
    picks += pick_evidence(conn, "record_kind='trial' AND extras LIKE '%COMPLETED%'", 1, "t1")
    picks += pick_evidence(conn, "record_kind='trial' AND extras LIKE '%RECRUITING%'", 1, "t2")
    # 6) 含全文的文献（pmcid 非空，可演示全文增强）
    picks += pick_evidence(conn, "record_kind='abstract' AND pmcid IS NOT NULL", 2, "ft")
    # 7) 综述/其他（双主题）
    picks += pick_evidence(conn, "record_kind='abstract' AND evidence_level='review' AND topics LIKE '%hypertension%'", 1, "v1")
    picks += pick_evidence(conn, "record_kind='abstract' AND evidence_level='review' AND topics LIKE '%lipids%'", 1, "v2")
    # 8) 经典证据（SPRINT/DASH 相关，覆盖早年）
    picks += pick_evidence(conn, "record_kind='abstract' AND (title LIKE '%Systolic Blood Pressure Intervention%' OR title LIKE '%Dietary Approaches to Stop Hypertension%')", 2, "classic")
    # 9) Europe PMC 独有摘要
    picks += pick_evidence(conn, "record_kind='abstract' AND source_type='europepmc' AND pmid IS NULL", 2, "epmc")
    # 10) 近期文献（2025+）
    picks += pick_evidence(conn, "record_kind='abstract' AND year >= 2025", 2, "recent")

    # 按 id 去重
    seen, fixture = set(), []
    for r in picks:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        fixture.append(r)
    fixture = fixture[:20]

    out = fixtures_dir / "evidence_fixture.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for r in fixture:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    conn.close()
    print(f"evidence_fixture.jsonl: {len(fixture)} 条")
    for r in fixture:
        print(f"  {r['id']:<30} {r['record_kind']:<16} {r['evidence_level']:<18} {r.get('title','')[:50]}")


if __name__ == "__main__":
    main()
