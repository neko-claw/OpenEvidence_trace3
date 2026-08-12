"""Prompt 构建：A（无证据）与 B/C/D（有证据）两种模板，输出结构统一"""
from __future__ import annotations

from core.dataclasses import Question

SYSTEM_BASE = (
    "你是一个医学证据研究助手，服务对象是医学生与科研人员。"
    "回答必须严谨、可追溯，不提供个体化诊断或用药调整建议。"
    "项目仅供教学研究，不用于临床诊疗。"
)

ANSWER_FORMAT = (
    "请严格按以下 Markdown 结构输出：\n"
    "## 结论摘要\n2-4 句，给出证据强弱与适用范围。\n"
    "## 证据说明\n列出关键结论，每条注明不确定性。\n"
    "## 局限与边界\n说明证据年份、研究人群、检索缺口；不提供个体化诊疗建议。"
)


def _format_options(q: Question) -> str:
    """选择题选项渲染：固定顺序，带字母前缀；非选择题返回空串。"""
    if not q.options:
        return ""
    lines = ["选项（请按字母选择或引用）："]
    for i, opt in enumerate(q.options):
        letter = chr(ord("A") + i)
        lines.append(f"{letter}. {opt}")
    return "\n".join(lines)


def _question_text(q: Question) -> str:
    """题干 + 选项（有选项时附加）。"""
    opts = _format_options(q)
    return f"题目：{q.question}\n\n{opts}".rstrip() if opts else f"题目：{q.question}"


def build_prompt_a(q: Question) -> list[dict]:
    """条件 A：纯 LLM，无外部证据。不得出现引用，不得声称引用来源。"""
    user = (
        f"{_question_text(q)}\n\n"
        f"说明：这是一个医学常识/证据问题。请基于你的知识回答。"
        f"如果没有把握，明确说明证据不足。不允许编造文献、数字或来源。\n\n"
        f"{ANSWER_FORMAT}"
    )
    return [{"role": "system", "content": SYSTEM_BASE}, {"role": "user", "content": user}]


def build_prompt_bcd(q: Question, retrieved: list[dict]) -> list[dict]:
    """条件 B/C/D：提供证据上下文，强制用 [E#] 引用且只能引用给定证据。"""
    q_text = _question_text(q)
    if not retrieved:
        user = (
            f"{q_text}\n\n"
            f"本次检索未找到可用证据。请如实说明检索缺口，不要补写结论。\n\n{ANSWER_FORMAT}"
        )
        return [{"role": "system", "content": SYSTEM_BASE}, {"role": "user", "content": user}]

    blocks = []
    for i, ev in enumerate(retrieved, start=1):
        blocks.append(
            f"[E{i}] {ev['title']}\n"
            f"来源类型: {ev['source_type']} | 发表: {ev['published_at'] or '未知'} | "
            f"证据等级: {ev['evidence_level']}\n"
            f"内容: {ev['text'][:1500]}\n"
        )
    evidence_text = "\n".join(blocks)

    user = (
        f"{q_text}\n\n"
        f"以下是本次检索到的证据片段（只允许使用这些证据）：\n\n{evidence_text}\n\n"
        f"要求：\n"
        f"1. 只根据上述证据回答；证据不支持的结论不要写。\n"
        f"2. 关键陈述必须用 [E1]、[E2] 等编号引用上述证据。\n"
        f"3. 证据不足、冲突或过时时，如实说明而不是补写。\n"
        f"4. 不允许引用 [E#] 以外的任何来源。\n\n"
        f"{ANSWER_FORMAT}"
    )
    return [{"role": "system", "content": SYSTEM_BASE}, {"role": "user", "content": user}]


def build_prompt_a2(q: Question, search_results: list[dict]) -> list[dict]:
    """条件 A2：提供通用搜索结果（而非项目证据库），强制用 [S#] 引用，与 [E#] 严格区分。

    公平性：与 A/B/C 使用同一系统提示与输出结构；引用只允许来自本次搜索响应。
    结果 simulated=True 时会在提示中标注（离线演示，避免与真实搜索混淆）。
    """
    blocks = []
    for i, r in enumerate(search_results, start=1):
        tag = "（离线模拟结果）" if r.get("simulated") else ""
        blocks.append(
            f"[S{i}]{tag} {r.get('title', '')}\n"
            f"URL: {r.get('url', '')}\n"
            f"摘要: {r.get('snippet', '')[:1500]}\n"
        )
    search_text = "\n".join(blocks) if blocks else "（搜索未返回可用结果）"

    user = (
        f"{_question_text(q)}\n\n"
        f"以下是使用通用搜索工具获得的网页结果（只允许使用这些结果）：\n\n{search_text}\n\n"
        f"要求：\n"
        f"1. 只根据上述搜索结果回答；结果未覆盖的内容不要编造。\n"
        f"2. 关键陈述必须用 [S1]、[S2] 等编号引用上述搜索结果。\n"
        f"3. 不允许引用 [S#] 以外的任何来源、URL 或文献编号。\n"
        f"4. 搜索结果不足、冲突或过时时，如实说明而不是补写。\n\n"
        f"{ANSWER_FORMAT}"
    )
    return [{"role": "system", "content": SYSTEM_BASE}, {"role": "user", "content": user}]


def build_judge_prompt(q: Question, answer: str, rubric: dict) -> list[dict]:
    """LLM judge：对 rubric 原子主张逐项打分，输出 JSON。answer 匿名化后调用。"""
    key_points = rubric.get("key_points", [])
    key_points_text = "\n".join(f"- {k}" for k in key_points) or "（无）"
    system = (
        "你是一名严格的医学评测审稿人。对给定回答，按评分点逐项判断 "
        "supported（回答正确且有依据）/ unsupported（回答与事实不符或依据不足）/ "
        "missing（漏掉该评分点）。再给出 1-5 分的相关性、完整性、事实性评分。"
        "只输出 JSON，不要解释。"
    )
    user = (
        f"{_question_text(q)}\n\n评分点：\n{key_points_text}\n\n"
        f"回答：\n{answer}\n\n"
        f'输出 JSON 格式：{{"verdicts": [{{"point": str, "decision": "supported|unsupported|missing"}}], '
        f'"relevance": 1-5, "completeness": 1-5, "faithfulness": 1-5, "correctness": 1-5, '
        f'"notes": str}}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
