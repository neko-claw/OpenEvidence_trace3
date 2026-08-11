"""按需全文拉取服务（供 RAG/MCP 工具在生成/验证阶段使用）。

架构原则（对应规划 4.1 / 12.3）：
- 检索召回用摘要（快、全）；命中高价值证据后，**按需**拉取 OA 全文片段用于
  生成细节与支持性验证，避免把全部正文塞进索引。
- 支持按 PMID 或 PMCID 拉取；全文 XML 缓存于 data/raw/europepmc/fulltext/。

用法：
    python -m ingestion.fulltext_service --pmid 39210715            # 按 PMID
    python -m ingestion.fulltext_service --pmcid PMC13209865        # 按 PMCID
    python -m ingestion.fulltext_service --pmid 39210715 --no-chunk # 只下不切块
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import config
from .http_utils import fetch_json
from .sources import europepmc

log = logging.getLogger("ingestion.fulltext_service")

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def resolve_pmcid(pmid: str):
    """把 PMID 解析为 PMCID（仅 OA 文献返回 pmcid，否则 None）。"""
    data = fetch_json(f"{BASE}/search",
                      params={"query": f"EXT_ID:{pmid}", "format": "json",
                              "pageSize": 5, "resultType": "core"},
                      headers={"User-Agent": config.USER_AGENT},
                      sleep=config.EPMC_SLEEP)
    for h in data.get("resultList", {}).get("result", []):
        if h.get("pmid") == pmid and h.get("pmcid"):
            return h
    return None


def get_fulltext(pmcid: str, force: bool = False):
    """按 PMCID 获取全文 XML（带缓存）。返回 (xml_text|None, 缓存路径|None)。"""
    out = config.EPMC_FULLTEXT_DIR / f"{pmcid}.xml"
    if out.exists() and not force:
        return out.read_text(encoding="utf-8"), out
    xml_text = europepmc.fulltext_xml(pmcid)
    if xml_text is None:
        return None, None
    europepmc.save_fulltext(pmcid, xml_text)
    return xml_text, out


def fetch_by_pmid(pmid: str, chunk: bool = True, force: bool = False):
    """按 PMID 拉取全文并（可选）分块。返回 dict 或 None。"""
    hit = resolve_pmcid(pmid)
    if not hit:
        log.info("PMID %s 无 OA 全文", pmid)
        return None
    pmcid = hit["pmcid"]
    xml_text, _ = get_fulltext(pmcid, force=force)
    if xml_text is None:
        log.info("PMID %s (%s) 全文不可用", pmid, pmcid)
        return None
    sections = europepmc.xml_to_sections(xml_text)
    chunks = europepmc.chunk_sections(
        sections, max_chars=config.FULLTEXT_CHUNK_MAX_CHARS,
        cap=config.FULLTEXT_CHUNK_CAP_PER_ARTICLE,
        skip=config.FULLTEXT_SKIP_SECTIONS) if chunk else []
    return {
        "pmid": pmid,
        "pmcid": pmcid,
        "title": hit.get("title"),
        "doi": hit.get("doi"),
        "journal": hit.get("journalTitle"),
        "pub_year": hit.get("pubYear"),
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def fetch_by_pmcid(pmcid: str, chunk: bool = True, force: bool = False):
    """按 PMCID 拉取全文并（可选）分块。"""
    xml_text, _ = get_fulltext(pmcid, force=force)
    if xml_text is None:
        return None
    sections = europepmc.xml_to_sections(xml_text)
    chunks = europepmc.chunk_sections(
        sections, max_chars=config.FULLTEXT_CHUNK_MAX_CHARS,
        cap=config.FULLTEXT_CHUNK_CAP_PER_ARTICLE,
        skip=config.FULLTEXT_SKIP_SECTIONS) if chunk else []
    return {"pmcid": pmcid, "chunk_count": len(chunks), "chunks": chunks}


def main():
    ap = argparse.ArgumentParser(description="按需全文拉取（Europe PMC OA）")
    ap.add_argument("--pmid", help="PMID")
    ap.add_argument("--pmcid", help="PMCID（含 PMC 前缀）")
    ap.add_argument("--no-chunk", action="store_true", help="只下载 XML 不切块")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    if args.pmid:
        res = fetch_by_pmid(args.pmid, chunk=not args.no_chunk, force=args.force)
        if res:
            _dump(res)
            return 0
        print(f"PMID {args.pmid}: 无可用 OA 全文", file=sys.stderr)
        return 1
    if args.pmcid:
        res = fetch_by_pmcid(args.pmcid, chunk=not args.no_chunk, force=args.force)
        if res:
            _dump(res)
            return 0
        print(f"{args.pmcid}: 无可用全文", file=sys.stderr)
        return 1
    ap.print_help()
    return 1


def _dump(res):
    """输出完整 JSON 到 stdout（供管道/程序调用）；日志只走 stderr。"""
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
