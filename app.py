"""OpenEvidence 赛道3 网页前端（Streamlit）

启动：streamlit run app.py
访问：浏览器打开 http://localhost:8501
功能：单题问答实验（A/B/C/D）、批量实验、评测统计与图表、题集/证据库浏览
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import load_config
from core.dataclasses import Question, load_jsonl
from core.llm import LLMClient
from evaluation.baseline import run_condition
from evaluation.stats import (bootstrap_ci, judge_agreement, mean_by_condition,
                              paired_deltas)
from generation.answer import AnswerGenerator
from retrieval.index import EvidenceStore

st.set_page_config(page_title="OpenEvidence 赛道3 评测台", layout="wide")

COND_META = {
    "A": "纯 LLM（无检索）",
    "B": "基础 RAG（BM25+向量+RRF）",
    "C": "Rerank RAG（特征重排+MMR）",
    "D": "完整系统（Wiki/Agent 轨迹）",
    "E": "劣化 RAG（P1）",
}
METRICS = ["relevance", "correctness", "completeness", "faithfulness",
           "claim_support_rate", "unsupported_claim_rate"]


# ---------------- 缓存资源 ----------------

@st.cache_resource(show_spinner="加载配置…")
def get_cfg():
    return load_config()


@st.cache_resource(show_spinner="构建证据索引（首次加载 embedding 模型稍慢）…")
def get_store(cfg_data: dict, emb_backend: str):
    from core.config import Config
    cfg = Config(cfg_data, Path(cfg_data.get("_root", Path.cwd())))
    store = EvidenceStore(cfg)
    store.load().build_index(emb_backend=emb_backend)
    return store


def cfg_to_dict(cfg) -> dict:
    d = {"_root": str(cfg.root), **cfg.data}
    return d


@st.cache_resource
def get_llm(cfg_data: dict):
    from core.config import Config
    cfg = Config(cfg_data, Path(cfg_data.get("_root", Path.cwd())))
    return LLMClient(cfg["llm"])


def load_questions(kind: str) -> list[Question]:
    cfg = get_cfg()
    p = cfg.path("questions_dev" if kind == "dev8" else "questions_formal")
    return [Question.from_dict(d) for d in load_jsonl(str(p))]


# ---------------- 页面 ----------------

st.sidebar.title("🩺 赛道3 评测台")
st.sidebar.caption("专用 RAG vs 通用大模型对比评估\n仅供教学研究，不用于临床诊疗")

cfg = get_cfg()
emb_backend = st.sidebar.selectbox("Embedding 后端", ["local", "fallback"],
                                   help="local 用本地 BGE 模型；fallback 免依赖但质量差")
store = get_store(cfg_to_dict(cfg), emb_backend)
llm = get_llm(cfg_to_dict(cfg))

st.sidebar.markdown("---")
st.sidebar.metric("证据库规模", f"{len(store.evidences)} 条")
st.sidebar.metric("索引版本", store.index_version)
st.sidebar.markdown(f"生成模型: `{llm.model}`")

nav = st.sidebar.radio("导航", ["🎯 单题问答", "⚡ 批量实验", "📊 评测结果", "🗂 题集与证据库"])

# =============== Tab 1: 单题问答 ===============
if nav == "🎯 单题问答":
    st.title("单题问答实验")
    st.caption("输入问题，选择条件运行，查看回答、引用与检索证据。")

    with st.form("qa_form"):
        col1, col2, col3 = st.columns([3, 1, 1])
        question = col1.text_input("医学问题", "高血压患者为什么有时需要长期服药？有哪些指南或研究依据？")
        condition = col2.selectbox("条件", list(COND_META.keys()), format_func=lambda c: f"{c} · {COND_META[c]}")
        run_btn = col3.form_submit_button("🚀 运行", use_container_width=True)

    if run_btn:
        q = Question(id="custom", topic="custom", difficulty="medium",
                     question=question, question_type="mechanism", freshness="stable")
        with st.spinner(f"运行条件 {condition}（约 5-15 秒）…"):
            run = run_condition(q, condition, cfg, store=store, llm=llm)
        st.success(f"完成 · 判定 {run.verification_decision} · {run.latency_ms}ms · "
                   f"in {run.input_tokens} tok · out {run.output_tokens} tok · ${run.estimated_cost:.5f}")
        if run.error:
            st.warning(f"校验提示: {run.error}")

        tab_ans, tab_src, tab_trace = st.tabs(["回答", "证据与引用", "工具轨迹"])

        with tab_ans:
            st.markdown(run.answer)
            st.markdown(f"**引用**: {run.citations or '无'}")

        with tab_src:
            if run.retrieved_evidence:
                for i, ev in enumerate(run.retrieved_evidence, 1):
                    with st.expander(f"[E{i}] {ev['title']} · {ev['source_type']} · {ev['evidence_level']}"):
                        st.markdown(ev["text"][:800])
                        cols = st.columns(4)
                        cols[0].caption(f"年份: {ev.get('published_at','')[:4] or '未知'}")
                        cols[1].caption(f"PMID/NCT: {ev.get('pmid') or ev.get('nct_id') or '—'}")
                        if ev.get("url"):
                            cols[2].markdown(f"[打开来源]({ev['url']})")
                        cols[3].caption(f"ID: {ev['id']}")
            else:
                st.info("本条件无检索证据（A 条件）")

        with tab_trace:
            st.json(run.tool_trace)
            st.caption(f"Agent 计划: {run.agent_plan}")

# =============== Tab 2: 批量实验 ===============
elif nav == "⚡ 批量实验":
    st.title("批量实验")
    c1, c2, c3 = st.columns([2, 2, 1])
    q_kind = c1.selectbox("题集", ["formal12", "dev8"])
    conditions = c2.multiselect("条件", list(COND_META.keys()), default=["A", "B", "C", "D"])
    limit = c3.number_input("题数限制(0=全部)", 0, 20, 0)
    if st.button("▶ 开始批量实验", type="primary"):
        questions = load_questions(q_kind)
        if limit:
            questions = questions[:limit]
        st.info(f"开始运行 {len(questions)} 题 × {len(conditions)} 条件（每条件约 6-12 秒）")
        prog = st.progress(0.0, text="准备…")
        results = []
        total = len(questions) * len(conditions)
        done = 0
        for q in questions:
            for cond in conditions:
                try:
                    run = run_condition(q, cond, cfg, store=store, llm=llm)
                except Exception as e:
                    st.error(f"{q.id} {cond}: {e}")
                    continue
                results.append(run.to_dict())
                done += 1
                prog.progress(done / total, text=f"{q.id} / {cond}")
        prog.empty()
        st.success(f"完成 {len(results)} runs")
        df = pd.DataFrame(results)[["question_id", "condition", "verification_decision",
                                    "latency_ms", "input_tokens", "output_tokens",
                                    "estimated_cost", "error"]]
        st.dataframe(df, use_container_width=True, height=400)

# =============== Tab 3: 评测结果 ===============
elif nav == "📊 评测结果":
    st.title("评测结果")
    import matplotlib.pyplot as plt
    import numpy as np

    runs_dir = cfg.path("runs_dir")
    scores_dir = cfg.path("scores_dir")
    run_files = sorted(runs_dir.glob("runs_*.jsonl"), reverse=True)
    score_files = sorted(scores_dir.glob("scores_*.jsonl"), reverse=True)

    col1, col2 = st.columns(2)
    sel_scores = col1.selectbox("评分文件", score_files, format_func=lambda p: p.name) if score_files else None
    sel_runs = col2.selectbox("运行文件（供配对检索指标）", run_files, format_func=lambda p: p.name) if run_files else None

    if not sel_scores:
        st.warning("暂无评分数据。请先在「批量实验」运行，再执行：python -m evaluation.judge --runs <runs文件>")
    else:
        scores = load_jsonl(str(sel_scores))
        questions = [q.to_dict() for q in load_questions("formal12")]
        st.caption(f"评分条数: {len(scores)}")

        t1, t2, t3, t4 = st.tabs(["均值对比", "配对差值", "按题型", "原始评分"])

        with t1:
            rows = []
            for m in METRICS:
                mm = mean_by_condition(scores, m)
                row = {"指标": m, **{c: round(v, 3) for c, v in mm.items()}}
                rows.append(row)
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

        with t2:
            metric = st.selectbox("指标", METRICS)
            c1, c2 = st.selectbox("配对", [("A", "C"), ("A", "B"), ("B", "C"), ("C", "D"), ("A", "D")])
            deltas = paired_deltas(scores, metric, c1, c2)
            if deltas:
                lo, hi = bootstrap_ci(deltas)
                st.markdown(f"**{c2} − {c1}** 均值 **{np.mean(deltas):+.3f}** "
                            f"(95% CI [{lo:+.3f}, {hi:+.3f}], n={len(deltas)})")
                fig, ax = plt.subplots(figsize=(9, max(3, len(deltas) * 0.45)))
                y = np.arange(len(deltas))
                colors = ["#2e8b57" if d > 0 else "#cd5c5c" for d in deltas]
                ax.barh(y, deltas, color=colors, alpha=0.8)
                qtext = {q["id"]: q["question"][:15] + "…" for q in questions}
                ax.set_yticks(y)
                ax.set_yticklabels([f"{deltas[i]:+.2f} {qtext.get('q%02d' % (i + 1), i)}" for i in range(len(deltas))], fontsize=8)
                ax.axvline(0, color="black", lw=0.8)
                ax.set_title(f"配对差值 {c2} - {c1}（{metric}）")
                ax.set_xlabel("差值")
                st.pyplot(fig)
            else:
                st.info("该配对暂无数据")

        with t3:
            qtype = {q["id"]: q.get("question_type", "?") for q in questions}
            agg = {}
            for s in scores:
                t = qtype.get(s["question_id"], "?")
                agg.setdefault(t, {}).setdefault(s["condition"], []).append(s.get("faithfulness"))
            rows = []
            for t, cmap in agg.items():
                rows.append({"题型": t, **{c: round(float(np.nanmean(v)), 3) for c, v in cmap.items()}})
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

        with t4:
            cols = ["question_id", "condition", "judge_id", "relevance", "correctness",
                    "completeness", "faithfulness", "claim_support_rate", "unsupported_claim_rate", "notes"]
            df = pd.DataFrame(scores)[cols]
            st.dataframe(df, use_container_width=True, height=500)

# =============== Tab 4: 题集与证据库 ===============
else:
    st.title("题集与证据库")
    t1, t2 = st.tabs(["题集", "证据库"])

    with t1:
        kind = st.selectbox("题集", ["formal12", "dev8"])
        questions = load_questions(kind)
        df = pd.DataFrame([{
            "id": q.id, "题型": q.question_type, "难度": q.difficulty,
            "时效": q.freshness, "问题": q.question, "gold数": len(q.gold_source_ids),
        } for q in questions])
        st.dataframe(df, use_container_width=True, height=500)
        st.caption(f"共 {len(questions)} 道题。gold_source_ids 为人工核验的引用金标准，当前 "
                   f"{int(df['gold数'].sum())} 条待补充。")

    with t2:
        search = st.text_input("🔍 在证据库中检索（BM25+向量+RRF）", "高血压 治疗")
        top, features = store.retrieve(search, use_rerank=True, k_final=10)
        st.caption(f"命中 {len(top)} 条（top-10）")
        for i, ev in enumerate(top, 1):
            with st.expander(f"[{i}] {ev['title']} · {ev['source_type']} · {ev['evidence_level']}"):
                st.markdown(ev["text"][:600])
                st.caption(f"ID: {ev['id']} · 年份: {ev.get('published_at','')[:4] or '未知'} · "
                           f"PMID: {ev.get('pmid','—')} · NCT: {ev.get('nct_id','—')}")
                if ev.get("url"):
                    st.markdown(f"[打开来源]({ev['url']})")

st.sidebar.markdown("---")
st.sidebar.caption("OpenEvidence 赛道3 · MVP v0.1")
