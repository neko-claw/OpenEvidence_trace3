"""语料一致性校验脚本：evidence.db 与 JSONL 是否一致、无重复/空文本、chunk 元数据齐全。

用途（对应实施规划 §6.6/§9 可复现要求）：
- B1/B6 一键验证冻结语料的可重建性与完整性；
- 每次重建数据集后运行，输出 PASS/FAIL 清单，供报告引用。

用法：
    python scripts/verify_corpus.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion import config  # noqa: E402


def _load_jsonl(path: Path):
    recs = []
    for ln in path.read_text(encoding="utf-8").split("\n"):
        if ln.strip():
            recs.append(json.loads(ln))
    return recs


def _extras(r: dict) -> dict:
    ex = r.get("extras") or {}
    return json.loads(ex) if isinstance(ex, str) else ex


def main():
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")

    print("== 1) 文件存在 ==")
    ev_path = config.EVIDENCE_JSONL
    chunk_path = config.FULLTEXT_CHUNKS_JSONL
    db_path = config.EVIDENCE_DB
    check("evidence.jsonl", ev_path.exists())
    check("fulltext_chunks.jsonl", chunk_path.exists())
    check("evidence.db", db_path.exists())

    main_recs = _load_jsonl(ev_path) if ev_path.exists() else []
    chunk_recs = _load_jsonl(chunk_path) if chunk_path.exists() else []

    print("\n== 2) 记录唯一性与空文本 ==")
    ids = [r["id"] for r in main_recs + chunk_recs]
    check("记录 ID 唯一", len(ids) == len(set(ids)), f"({len(ids)} 条)")
    dup_pmid = {}
    for r in main_recs:
        if r.get("pmid"):
            dup_pmid.setdefault(r["pmid"], []).append(r["id"])
    dup = {k: v for k, v in dup_pmid.items() if len(v) > 1}
    check("主集同 PMID 无重复", not dup, f"({len(dup)} 组)" if dup else "")
    empty = [r["id"] for r in main_recs if not (r.get("abstract_or_chunk") or "").strip()]
    check("主集无空文本", not empty, f"({len(empty)} 条)" if empty else "")

    print("\n== 3) 全文 chunk 元数据 ==")
    if chunk_recs:
        missing = [r["id"] for r in chunk_recs if not _extras(r).get("section")]
        check("chunk 均带 section", not missing, f"({len(chunk_recs)} chunks)")
        tiny = [r["id"] for r in chunk_recs if len(r.get("abstract_or_chunk") or "") < 50]
        check("chunk 长度 >= 50", not tiny, f"({len(tiny)} 条)" if tiny else "")
        # 引用编号残留抽查（[数字] 形式）：仅对非表格 prose 检查；
        # 表格中的 [48]/[30] 为原表引用列、[38, 39] 为 IQR 区间，均属合法内容
        import re
        iqr_re = re.compile(r"\[\s*\d+\s*(?:[,;–-]\s*\d+\s*)+\.?\]")
        bad = [r["id"] for r in chunk_recs
               if " || " not in r.get("abstract_or_chunk", "")
               and re.search(r"\[\s*\d[\d,\s;]*\]", r.get("abstract_or_chunk") or "")
               and not iqr_re.search(r.get("abstract_or_chunk") or "")]
        check("prose chunk 无引用编号残留", not bad,
              f"({len(bad)} 条需人工核验)" if bad else "")
    else:
        check("chunk 元数据", False, "无 chunk 文件")

    print("\n== 4) SQLite 与 JSONL 一致性 ==")
    if db_path.exists():
        conn = sqlite3.connect(str(db_path))
        n_db = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        ids_db = set(r[0] for r in conn.execute("SELECT id FROM evidence"))
        check("evidence.db 行数 == JSONL 行数", n_db == len(ids), f"({n_db} vs {len(ids)})")
        diff = set(ids) - ids_db
        check("JSONL 与 db ID 集合一致", not diff, f"(仅 JSONL 有 {len(diff)} 条)" if diff else "")
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        print(f"    db meta: {meta}")
        conn.close()
    else:
        check("SQLite 一致性", False, "无 db 文件")

    print("\n== 5) manifest 哈希 ==")
    if config.MANIFEST_JSON.exists():
        m = json.loads(config.MANIFEST_JSON.read_text(encoding="utf-8"))
        import hashlib
        ok = True
        for name in ("evidence.jsonl", "fulltext_chunks.jsonl"):
            p = config.DATA_PROCESSED / name
            h = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
            if h and m.get("split_hashes", {}).get(name) != h:
                ok = False
                print(f"    哈希不一致: {name}")
        check("manifest split_hashes 匹配", ok)
    else:
        check("manifest 哈希", False)

    failed = [n for n, ok, _ in checks if not ok]
    print("\n" + "=" * 50)
    if failed:
        print(f"结果: {len(checks) - len(failed)}/{len(checks)} PASS，失败项: {failed}")
        return 1
    print(f"结果: {len(checks)}/{len(checks)} 全部 PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
