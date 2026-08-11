#!/usr/bin/env bash
# OpenEvidence 赛道3 一键启动脚本
# 用法: bash scripts/start.sh [dev|formal|smoke|test|data]
set -euo pipefail
cd "$(dirname "$0")/.."

PY=/home/yjk/miniconda3/envs/py310/bin/python
[ -x "$PY" ] || PY=$(command -v python3)

echo "================ OpenEvidence 赛道3 启动 ================"
echo "Python: $($PY --version)"

# 1. API key 检查
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  echo "❌ 缺少环境变量 DEEPSEEK_API_KEY"
  echo "   执行: export DEEPSEEK_API_KEY=sk-xxx"
  exit 1
fi
echo "✅ DEEPSEEK_API_KEY 已设置"

# 2. 依赖检查
$PY -c "import httpx, yaml, numpy, rank_bm25, pandas, scipy, matplotlib" 2>/dev/null || {
  echo "❌ 依赖缺失，执行安装:"
  echo "   /home/yjk/miniconda3/envs/py310/bin/pip install -r requirements.txt"
  exit 1
}
echo "✅ 依赖齐全"

# 3. 样例数据（缺则生成，不覆盖已有真实数据）
if [ ! -f data/processed/evidence.jsonl ]; then
  echo "→ 生成离线样例证据库..."
  $PY scripts/build_sample_data.py
fi
echo "✅ 证据库: data/processed/evidence.jsonl ($(wc -l < data/processed/evidence.jsonl) 条)"

MODE="${1:-dev}"
case "$MODE" in
  dev)     echo "▶ 冒烟实验: 开发题前2道 × A/B/C/D (fallback embedding)"
           exec $PY -m evaluation.experiment --questions dev8 --limit 2 --emb-backend fallback --tag startup ;;
  formal)  echo "▶ 正式实验: 12道 × A/B/C/D (约8-10分钟)"
           exec $PY -m evaluation.experiment --questions formal12 ;;
  smoke)   echo "▶ 单题冒烟: 开发题第1道"
           exec $PY -m evaluation.experiment --questions dev8 --limit 1 --emb-backend fallback --tag smoke ;;
  test)    echo "▶ 运行契约测试"
           exec $PY -m pytest tests/ -q ;;
  data)    echo "▶ 采集真实数据 (PubMed + ClinicalTrials.gov, 需要网络)"
           exec $PY scripts/collect_real.py ;;
  *)
    echo "用法: bash scripts/start.sh [dev|formal|smoke|test|data]"
    exit 1 ;;
esac
