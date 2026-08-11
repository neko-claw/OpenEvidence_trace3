"""Europe PMC REST 连接器：开放获取文献检索 + 全文 XML 下载。"""
from __future__ import annotations

import json
import logging
import re

import xml.etree.ElementTree as ET

from .. import config
from ..http_utils import fetch_json, fetch_text_or_none

log = logging.getLogger("ingestion.europepmc")

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def search(query: str, page_size: int = 500):
    """搜索，返回 hit 列表（resultType=core）。"""
    params = {"query": query, "format": "json", "pageSize": page_size,
              "resultType": "core"}
    data = fetch_json(f"{BASE}/search", params=params,
                      headers={"User-Agent": config.USER_AGENT},
                      sleep=config.EPMC_SLEEP)
    hits = data.get("resultList", {}).get("result", [])
    log.info("epmc search -> %d hits", len(hits))
    return hits


def save_raw(slug: str, hits):
    out = config.EPMC_DIR / f"search_{slug}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"slug": slug, "count": len(hits), "hits": hits},
                              ensure_ascii=False), encoding="utf-8")
    return out


def fulltext_xml(pmcid: str):
    """下载 PMC 全文 XML；无全文时返回 None。

    注意：fullTextXML 端点的路径为 /{id}/fullTextXML，id 必须带 "PMC" 前缀
    （官方示例：rest/PMC3257301/fullTextXML）。
    """
    url = f"{BASE}/{pmcid}/fullTextXML"
    text = fetch_text_or_none(url, headers={"User-Agent": config.USER_AGENT},
                              sleep=config.EPMC_SLEEP)
    if text is None:
        log.info("no full text for %s", pmcid)
    return text


def save_fulltext(pmcid: str, xml_text: str):
    out = config.EPMC_FULLTEXT_DIR / f"{pmcid}.xml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml_text, encoding="utf-8")
    return out


# ------------------------------------------------------------------ 全文解析

def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def xml_to_sections(xml_text: str):
    """把 JATS XML 解析为 [(section_title, [paragraph...]), ...]（正文部分）。"""
    root = ET.fromstring(xml_text)
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    body = None
    for tag in ("body", "sec"):
        cand = root.find(f".//{ns}{tag}")
        if cand is not None:
            body = cand
            break
    if body is None:
        return []

    sections = []

    def walk(elem, sec_title):
        cur = []
        for child in elem:
            name = _local_name(child.tag)
            if name == "sec":
                if cur:
                    sections.append((sec_title, cur))
                    cur = []
                t = child.find(f"{ns}title")
                new_title = "".join(t.itertext()).strip() if t is not None else ""
                walk(child, new_title or sec_title)
            elif name == "p":
                txt = "".join(child.itertext()).strip()
                if txt:
                    cur.append(txt)
            elif name in ("table-wrap", "fig", "boxed-text"):
                txt = " ".join("".join(x.itertext()).strip() for x in child.iter() if _local_name(x.tag) in ("p", "td", "th"))
                if txt:
                    cur.append(txt)
        if cur:
            sections.append((sec_title, cur))

    walk(body, "")
    return sections


def chunk_sections(sections, max_chars=4000, cap=20, skip=()):
    """按小节分块，每块带小节标题前缀；跳过参考文献等噪声小节。"""
    chunks = []
    for sec_title, paragraphs in sections:
        title = (sec_title or "").strip().lower()
        if title in skip:
            continue
        text = " ".join(paragraphs).strip()
        if not text:
            continue
        prefix = f"[{sec_title}] " if sec_title else ""
        while len(text) > max_chars:
            chunks.append(prefix + text[:max_chars])
            text = text[max_chars:]
            if len(chunks) >= cap:
                return chunks
        if text:
            chunks.append(prefix + text)
        if len(chunks) >= cap:
            break
    return chunks
