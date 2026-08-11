"""A2 通用搜索对照（B3 交付物）

与项目检索（BM25/向量/RRF，EvidenceStore）完全隔离：
- 不使用项目 Evidence store，不读取 data/processed/evidence.jsonl
- 固定搜索预算：max_searches（搜索次数）、max_results_per_search（单次结果数）、timeout
- 每次搜索的响应快照写入 Run.tool_trace，引用用 [S#] 单独标识（config a2.citation_prefix）
- 搜索成本单独并入 Run.estimated_cost

provider:
  mock   : 离线模拟通用搜索。内置与项目证据库无关的"网页风格"条目（标题/URL/摘要），
           结果标注 simulated=True，仅用于无搜索 API key 时的流程演示与测试。
  serper : 真实 Google Serper API（https://serper.dev），需环境变量 SERPER_API_KEY。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

import httpx

from core.config import Config


@dataclass
class GeneralSearchResult:
    url: str = ""
    title: str = ""
    snippet: str = ""
    provider: str = ""
    simulated: bool = False      # True 表示离线模拟结果（不可点击，仅供流程演示）
    queried_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class SearchBudgetExceeded(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# mock provider：离线模拟通用搜索
# 知识库刻意与项目证据库独立（不同于 evidence.jsonl 的文献条目），
# 模拟"普通网页/新闻/科普站点"的返回样式。
# ---------------------------------------------------------------------------
_MOCK_PAGES = [
    {
        "title": "高血压防治 | 心血管健康科普",
        "url": "https://health-example.example.com/hypertension-guide",
        "keywords": ["高血压", "hypertension", "血压", "降压"],
        "snippet": "高血压是持续血压升高，长期未控制可损伤心、脑、肾等靶器官。"
                   "生活方式干预与规律用药是基础管理措施，请遵医嘱。",
    },
    {
        "title": "高血脂（血脂异常）怎么吃怎么动 - 生活方式专栏",
        "url": "https://lifestyle-example.example.com/dyslipidemia-diet",
        "keywords": ["高血脂", "血脂", "胆固醇", "LDL", "低密度脂蛋白", "lipid"],
        "snippet": "血脂异常主要包括 LDL-C 升高。饮食（减少饱和脂肪与反式脂肪）"
                   "和规律运动被广泛推荐为一线干预，具体目标因风险分层而异。",
    },
    {
        "title": "临床试验登记与结果平台（模拟站）",
        "url": "https://trials-example.example.com/results",
        "keywords": ["试验", "临床试验", "新药", "脂蛋白a", "Lp(a)", "PCSK9", "最新", "trial"],
        "snippet": "本模拟站收录近年心血管领域试验结果摘要，仅供演示："
                   "Lp(a) 靶向药物与 PCSK9 抑制剂长期结局研究持续推进。",
    },
    {
        "title": "诊室血压测量标准 | 体检百科",
        "url": "https://health-example.example.com/bp-standard",
        "keywords": ["诊室血压", "140", "90", "诊断标准", "mmHg"],
        "snippet": "常见科普口径：诊室血压 ≥140/90 mmHg 提示高血压，需非同日多次复测确认。"
                   "具体以最新指南为准。",
    },
    {
        "title": "限钠与 DASH 饮食：怎么吃降压",
        "url": "https://nutrition-example.example.com/dash-sodium",
        "keywords": ["限钠", "盐", "DASH", "饮食", "生活方式"],
        "snippet": "减少钠摄入与 DASH 饮食模式被多项研究支持可降低血压，"
                   "建议作为高血压生活方式干预的组成部分。",
    },
    {
        "title": "中草药降血压：证据与风险 | 循证医学问答站",
        "url": "https://evidence-example.example.com/herbal-bp",
        "keywords": ["中草药", "中药", "替代", "保健品", "红酒"],
        "snippet": "目前缺乏高质量对照证据支持中草药或保健品替代标准降压治疗，"
                   "自行停药存在血压反弹与心脑血管风险。",
    },
    {
        "title": "他汀类药物：目标与强度 | 药学科普",
        "url": "https://pharma-example.example.com/statin-goals",
        "keywords": ["他汀", "statin", "降脂药", "治疗目标", "LDL-C"],
        "snippet": "他汀是降 LDL-C 的一线药物，治疗目标按心血管风险分层确定；"
                   "强度选择与随访监测应个体化。",
    },
    {
        "title": "2024 心衰与高血压进展（模拟新闻稿）",
        "url": "https://news-example.example.com/hf-hypertension-2024",
        "keywords": ["心衰", "射血分数", "2023", "2024", "最新", "进展"],
        "snippet": "模拟新闻：近年来关于射血分数保留型心衰与高血压管理的新药研究"
                   "持续更新，具体结果请查阅正式临床试验登记。",
    },
]


def _mock_search(query: str, max_results: int) -> tuple[list[GeneralSearchResult], dict]:
    q = query.lower()
    scored = []
    for page in _MOCK_PAGES:
        score = sum(1 for kw in page["keywords"] if kw.lower() in q)
        if score > 0:
            scored.append((score, page))
    scored.sort(key=lambda x: (-x[0], x[1]["title"]))
    results = [
        GeneralSearchResult(
            url=p["url"], title=p["title"], snippet=p["snippet"],
            provider="mock", simulated=True,
            queried_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )
        for _, p in scored[:max_results]
    ]
    meta = {"matched_pages": len(scored), "total_pages": len(_MOCK_PAGES)}
    return results, meta


# ---------------------------------------------------------------------------
# serper provider：真实通用搜索（可选）
# ---------------------------------------------------------------------------
def _serper_search(query: str, cfg: dict, api_key: str) -> tuple[list[GeneralSearchResult], dict]:
    max_results = cfg["max_results_per_search"]
    t0 = time.time()
    resp = httpx.post(
        f"{cfg['api_base_url'].rstrip('/')}/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "gl": "cn", "hl": "zh-cn", "num": max_results},
        timeout=cfg.get("timeout", 20),
    )
    resp.raise_for_status()
    data = resp.json()
    organic = data.get("organic", [])[:max_results]
    results = [
        GeneralSearchResult(
            url=item.get("link", ""), title=item.get("title", ""),
            snippet=item.get("snippet", ""), provider="serper", simulated=False,
            queried_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )
        for item in organic
    ]
    meta = {"latency_ms": int((time.time() - t0) * 1000),
            "total_results": data.get("searchInformation", {}).get("totalResults", "")}
    return results, meta


# ---------------------------------------------------------------------------
# 统一入口：预算控制 + 响应快照
# ---------------------------------------------------------------------------
def search_general(query: str, cfg: Config, budget: Optional[dict] = None) -> tuple[list[GeneralSearchResult], dict]:
    """通用搜索（A2 条件专用）。

    返回 (results, meta)，meta 包含:
      provider, searches_used, results_returned, cost,
      snapshot (每次搜索的原始响应摘要，供 Run.tool_trace 落盘),
      simulated (是否离线模拟)

    预算：max_searches 次搜索 / max_results_per_search 条结果，超限抛 SearchBudgetExceeded。
    """
    a2 = dict(cfg.get("a2", {}))
    budget = budget or {}
    max_searches = budget.get("max_searches", a2.get("max_searches", 1))
    max_results = budget.get("max_results_per_search", a2.get("max_results_per_search", 5))
    provider = budget.get("provider", a2.get("provider", "mock"))
    cost_per_search = budget.get("cost_per_search", a2.get("cost_per_search", 0.0))

    all_results: list[GeneralSearchResult] = []
    snapshot: list[dict] = []
    searches_used = 0
    cost = 0.0
    elapsed = 0.0
    last_error = ""

    while searches_used < max_searches and len(all_results) < max_results:
        t0 = time.time()
        try:
            if provider == "serper":
                key = os.environ.get(a2.get("api_key_env", "SERPER_API_KEY"), "")
                if not key:
                    raise RuntimeError(
                        f"缺少环境变量 {a2.get('api_key_env', 'SERPER_API_KEY')}，"
                        f"A2 真实搜索需要 Serper API key；可改用 provider=mock")
                results, meta = _serper_search(query, a2, key)
                cost += cost_per_search
            elif provider == "mock":
                results, meta = _mock_search(query, max_results)
            else:
                raise RuntimeError(f"未知 A2 provider: {provider}（可选 mock | serper）")

            searches_used += 1
            elapsed += time.time() - t0
            all_results.extend(results[: max(max_results - len(all_results), 0)])
            snapshot.append({
                "search_no": searches_used,
                "query": query,
                "provider": provider,
                "latency_ms": int((time.time() - t0) * 1000),
                "results_returned": len(results),
                **{k: v for k, v in meta.items() if k not in ("latency_ms",)},
            })
        except (httpx.HTTPError, RuntimeError) as e:
            last_error = f"{type(e).__name__}: {e}"
            searches_used += 1
            elapsed += time.time() - t0
            if searches_used >= max_searches:
                break

    meta_out = {
        "provider": provider,
        "searches_used": searches_used,
        "results_returned": len(all_results),
        "cost": round(cost, 6),
        "elapsed_ms": int(elapsed * 1000),
        "simulated": provider == "mock",
        "budget": {"max_searches": max_searches, "max_results_per_search": max_results},
        "snapshot": snapshot,
        "error": last_error or None,
    }
    return all_results, meta_out
