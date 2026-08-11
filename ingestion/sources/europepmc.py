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


# ---- JATS XML 结构噪声清理（在 ET 树级别处理，避免正则破坏 XML 结构） ----

# 数学公式相关标签（local name）：mml:math / tex-math / inline-formula / disp-formula
_MATH_TAGS = {"math", "tex-math", "inline-formula", "disp-formula"}
# 交叉引用标记被移除后残留的引用编号括号，如 [1]、[9,10,11]、[1-3]
_CITE_BRACKET_RE = re.compile(r"\[\s*[\d,\s;\-–—]*\]")


def _strip_math_xrefs(root) -> None:
    """在解析后的树上：移除 <xref>（bibr/fig/table/fn/aff 交叉引用标记），
    把数学公式替换为 [MATH] 占位符（只处理最外层，避免嵌套重复）。

    注意：Element.remove/clear 会同时丢弃子元素的 tail 文本，必须先把 tail
    并回父元素 text，否则 xref/公式之后的正文会丢失。
    """
    pending_xrefs, pending_math = [], []
    for parent in root.iter():
        for child in list(parent):
            name = _local_name(child.tag)
            if name == "xref":
                pending_xrefs.append((parent, child))
            elif name in _MATH_TAGS:
                if _local_name(parent.tag) in _MATH_TAGS:  # 嵌套由外层处理
                    continue
                pending_math.append((parent, child))
    for parent, child in pending_xrefs:
        if child.tail:
            parent.text = (parent.text or "") + child.tail
        parent.remove(child)
    for parent, child in pending_math:
        tail = child.tail or ""
        child.clear()
        child.text = ("[MATH] " + tail).strip() if tail else "[MATH]"
        # 确保占位符出现在父文本流中（itertext 会读取该元素 text）


def _norm_sec_title(title: str) -> str:
    """章节标题规范化：去掉前导编号（如 '1.'、'2.3.1'）与尾部冒号。"""
    t = re.sub(r"^\s*\d+(?:\.\d+)*\s*[\.\)]?\s*", "", (title or "")).strip()
    t = re.sub(r"[:：]\s*$", "", t).strip()
    return t


def _table_text(table_wrap) -> str:
    """表格文本：单元格用 ' | ' 分隔、行用 ' || ' 分隔，避免不同单元格内容粘连。"""
    rows = []
    for tr in table_wrap.iter():
        if _local_name(tr.tag) != "tr":
            continue
        cells = []
        for el in tr.iter():
            if _local_name(el.tag) in ("td", "th") and el is not tr:
                txt = "".join(el.itertext()).strip()
                if txt:
                    cells.append(txt)
        if cells:
            rows.append(" | ".join(cells))
    return " || ".join(rows)


def _clean_para(txt: str) -> str:
    """段落后处理：去除引用编号括号残留、压缩连续 [MATH] 占位符与空白。"""
    txt = _CITE_BRACKET_RE.sub("", txt)
    txt = re.sub(r"(?:\[MATH\]\s*)+", "[MATH] ", txt)
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


def xml_to_sections(xml_text: str):
    """把 JATS XML 解析为 [(section_title, [paragraph...]), ...]（正文部分）。

    保证：一个 section 内的全部文本（含嵌套 sec、表格、图注）归属该 section；
    标题做编号规范化；数学公式与交叉引用噪声已在树级别剥离。
    """
    root = ET.fromstring(xml_text)
    _strip_math_xrefs(root)
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
                new_title = _norm_sec_title("".join(t.itertext()).strip()) if t is not None else sec_title
                walk(child, new_title)
            elif name == "p":
                txt = _clean_para("".join(child.itertext()))
                if txt:
                    cur.append(txt)
            elif name == "table-wrap":
                txt = _table_text(child)
                if txt:
                    cur.append(txt)
            elif name in ("fig", "boxed-text"):
                txt = _clean_para(" ".join("".join(x.itertext()).strip() for x in child.iter() if _local_name(x.tag) == "p"))
                if txt:
                    cur.append(txt)
        if cur:
            sections.append((sec_title, cur))

    walk(body, "")
    return sections


# ---- 小节内句子边界切分（改进 5：分块严格不跨小节） ----

def _split_sentences(text: str, max_chars: int):
    """按句末标点切句（保留标点）；超长句按 max_chars 硬切，保证句长 <= max_chars。"""
    out = []
    for s in re.split(r"(?<=[.!?。！？])\s+", text):
        s = s.strip()
        while len(s) > max_chars:
            out.append(s[:max_chars])
            s = s[max_chars:]
        if s:
            out.append(s)
    return out


def _chunk_section_text(text: str, max_chars: int, overlap_chars: int):
    """单小节内按句子边界分块。

    返回 [(text, start, end), ...]：start/end 为相对该小节规范化文本的字符区间
    （以句子间单空格拼接的 canon 为基准，用于 evidence_span 定位）。
    相邻块重叠约 overlap_chars 字符，避免硬切丢失上下文。
    """
    sentences = _split_sentences(text, max_chars)
    if not sentences:
        return []
    offsets = [0]
    for s in sentences:
        offsets.append(offsets[-1] + len(s) + 1)

    chunks = []
    i, n = 0, len(sentences)
    while i < n:
        j, length = i, 0
        while j < n:
            L = len(sentences[j]) + (1 if j > i else 0)
            if length + L > max_chars and j > i:
                break
            length += L
            j += 1
        chunk_text = " ".join(sentences[i:j]).strip()
        start, end = offsets[i], offsets[j] - 1
        chunks.append((chunk_text, start, end))
        if j >= n:
            break  # 句子已耗尽，不再产生重叠块
        # 重叠：下一块起点回退约 overlap_chars（至少推进 1 句，单句块不回退）
        nxt = j
        if j - i > 1:
            back, k = 0, j
            while k > i and back < overlap_chars:
                k -= 1
                back += len(sentences[k]) + 1
            nxt = k if k > i else i + 1
        i = nxt
    return chunks


def chunk_sections(sections, max_chars=4000, cap=20, skip=(), overlap_chars=150):
    """按小节分块：**每块严格属于单一小节**，句子边界切分 + 相邻块重叠。

    返回 [{"text", "section", "start", "end"}, ...]；跳过参考文献等噪声小节。
    text 带 "[小节标题] " 前缀；start/end 为该块正文相对小节的字符区间。
    """
    chunks = []
    for sec_title, paragraphs in sections:
        title = (sec_title or "").strip().lower()
        if title in skip:
            continue
        text = " ".join(paragraphs).strip()
        if not text:
            continue
        prefix = f"[{sec_title}] " if sec_title else ""
        for body, start, end in _chunk_section_text(text, max_chars, overlap_chars):
            chunks.append({
                "text": prefix + body,
                "section": sec_title or "(untitled)",
                "start": start,
                "end": end,
            })
            if len(chunks) >= cap:
                return chunks
    return chunks
