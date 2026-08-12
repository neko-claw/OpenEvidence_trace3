#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""带检查点的索引构建：逐批嵌入并增量落盘，断点续跑（供 DashScope 等远程嵌入用）。

用法：
  python scripts/build_index_checkpoint.py [--emb-backend api] [--batch 20]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import load_config
from core.dataclasses import Evidence, load_jsonl
from core.embeddings import EmbeddingClient
from retrieval.index import EvidenceStore


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emb-backend", default=None, choices=["api", "local", "fallback"])
    ap.add_argument("--batch", type=int, default=20)
    args = ap.parse_args()

    cfg = load_config()
    store = EvidenceStore(cfg)
    store.load()  # include_fulltext 由 config 控制
    print(f"文档总数: {len(store.evidences)}（含全文层）")

    emb_cfg = dict(cfg["embedding"])
    if args.emb_backend:
        emb_cfg["backend"] = args.emb_backend
    emb_cfg["batch_size"] = args.batch
    emb = EmbeddingClient(emb_cfg)
    print(f"嵌入后端: {emb.backend} | 模型: {getattr(emb, '_api_model', emb.cfg.get('local_model'))}")

    docs = [{"id": e.id, "title": e.title, "text": e.text} for e in store.evidences.values()]
    texts = [d["title"] + "\n" + d["text"] for d in docs]

    # 缓存键与 EvidenceStore.build_index 一致
    cache_key = hashlib.sha1()
    cache_key.update(json.dumps(
        [(e.id, e.content_hash) for e in store.evidences.values()], sort_keys=True).encode())
    cache_key.update(json.dumps({
        "backend": emb_cfg.get("backend"),
        "model": emb_cfg.get("local_model", ""),
        "dim": emb_cfg.get("dim"),
    }, sort_keys=True).encode())
    digest = cache_key.hexdigest()[:16]
    cache_dir = cfg.path("artifacts") / "vector_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    matrix_path = cache_dir / f"matrix-{digest}.npy"
    ids_path = cache_dir / f"ids-{digest}.json"

    # 断点续跑：已有完整矩阵且 ids 一致 -> 跳过
    if matrix_path.exists() and ids_path.exists():
        cached_ids = json.loads(ids_path.read_text(encoding="utf-8"))
        current_ids = [d["id"] for d in docs]
        if cached_ids == current_ids:
            print(f"缓存命中: {matrix_path.name}（{len(cached_ids)} 条，跳过嵌入）")
            return 0
        # 部分矩阵（进度检查点）：若行数匹配已嵌入数量则继续
        try:
            partial = np.load(matrix_path, allow_pickle=False)
            done = partial.shape[0]
        except Exception:
            done = 0
        start = done
        print(f"断点续跑: 已嵌入 {done}/{len(texts)}")
        rows = list(partial[:done])
    else:
        start = 0
        rows = []

    batch = args.batch
    t0 = time.time()
    for i in range(start, len(texts), batch):
        chunk = texts[i:i + batch]
        for attempt in range(4):
            try:
                vecs = emb.embed(chunk)
                break
            except Exception as e:
                print(f"  [retry {attempt + 1}] batch {i}: {str(e)[:120]}")
                time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"batch {i} 连续失败，已保存 {len(rows)} 条进度")
        rows.extend(vecs)
        # 每 10 批落一次检查点
        if (i // batch) % 10 == 9 or i + batch >= len(texts):
            arr = np.asarray(rows, dtype=np.float32)
            np.save(matrix_path, arr)
            ids_path.write_text(json.dumps([d["id"] for d in docs][:arr.shape[0]], ensure_ascii=False), encoding="utf-8")
            rate = (i + len(chunk)) / max(1, time.time() - t0)
            print(f"  进度 {i + len(chunk)}/{len(texts)} ({rate:.1f} 条/s)")

    matrix = np.asarray(rows, dtype=np.float32)
    np.save(matrix_path, matrix)
    ids_path.write_text(json.dumps([d["id"] for d in docs], ensure_ascii=False), encoding="utf-8")
    print(f"完成: {matrix.shape} -> {matrix_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
