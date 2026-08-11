"""证据库浏览工具

用法：
  python scripts/view_evidence.py                  # 统计概览
  python scripts/view_evidence.py list             # 列出全部（每行一条）
  python scripts/view_evidence.py list --type pubmed --level guideline
  python scripts/view_evidence.py list --search 他汀
  python scripts/view_evidence.py show <evidence_id>
  python scripts/view_evidence.py count
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import Counter

from core.dataclasses import load_jsonl


def overview(recs: list[dict]) -> None:
    print(f"证据库共 {len(recs)} 条\n")
    print("--- 按来源类型 ---")
    for k, v in Counter(r["source_type"] for r in recs).most_common():
        print(f"  {k:16s} {v}")
    print("--- 按证据等级 ---")
    for k, v in Counter(r.get("evidence_level", "unknown") for r in recs).most_common():
        print(f"  {k:18s} {v}")
    print("--- 按年份 ---")
    for k, v in sorted(Counter((r.get("published_at") or "")[:4] for r in recs).items(), reverse=True):
        print(f"  {k}: {v}")


def list_ev(recs: list[dict], stype: str | None, level: str | None, search: str | None) -> None:
    for r in recs:
        if stype and r["source_type"] != stype:
            continue
        if level and r.get("evidence_level") != level:
            continue
        if search and search.lower() not in (r["title"] + r["text"][:2000]).lower():
            continue
        print(f"[{r['id']}] {r.get('evidence_level','?'):16s} {r.get('published_at','')[:4]:6s} "
              f"{r['title'][:60]}")


def show(recs: list[dict], ev_id: str) -> None:
    for r in recs:
        if r["id"] == ev_id:
            print(f"ID: {r['id']}")
            print(f"标题: {r['title']}")
            print(f"来源: {r['source_type']} | 等级: {r.get('evidence_level')} | 年份: {r.get('published_at','')[:4]}")
            print(f"PMID: {r.get('pmid','—')} | DOI: {r.get('doi','—')} | NCT: {r.get('nct_id','—')}")
            print(f"URL: {r.get('url','—')}")
            print(f"PICO: 人群={r.get('population','—')} 干预={r.get('intervention','—')}")
            print("\n文本:")
            print(r.get("text", "")[:1500])
            return
    print(f"未找到 {ev_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description="证据库浏览")
    ap.add_argument("cmd", nargs="?", default="overview", help="overview|list|show|count")
    ap.add_argument("--type", default=None, help="按来源过滤: pubmed|clinicaltrial|guideline|wiki")
    ap.add_argument("--level", default=None, help="按等级过滤: guideline|rct|systematic_review|cohort|unknown")
    ap.add_argument("--search", default=None, help="关键词搜索标题/摘要")
    ap.add_argument("id", nargs="?", default=None, help="show 用的证据 ID")
    args = ap.parse_args()

    recs = load_jsonl("data/processed/evidence.jsonl")
    if args.cmd == "count":
        print(len(recs))
    elif args.cmd == "list":
        list_ev(recs, args.type, args.level, args.search)
    elif args.cmd == "show":
        if not args.id:
            print("用法: python scripts/view_evidence.py show <evidence_id>")
            return
        show(recs, args.id)
    else:
        overview(recs)


if __name__ == "__main__":
    main()
