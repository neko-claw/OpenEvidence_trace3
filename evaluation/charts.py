"""Render charts from b5_report CSV outputs.

This module intentionally consumes the canonical CSVs produced by
evaluation.b5_report instead of recomputing statistics from raw judge scores.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt


PREREGISTERED_COMPARISONS = {"B-A", "C-B", "D-C", "E-C"}
DEFAULT_PRIMARY_METRICS = (
    "rubric_keypoint_score",
    "unsupported_critical_claim_rate",
    "faithfulness",
    "citation_precision",
    "citation_coverage",
)


for _fp in [
    Path.home() / ".local/share/fonts/msyh.ttc",
    Path.home() / ".local/share/fonts/simhei.ttf",
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
]:
    if _fp.exists():
        try:
            fm.fontManager.addfont(str(_fp))
        except Exception:
            pass
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _float(value: str) -> float | None:
    try:
        if value in ("", "NA", None):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def condition_means_chart(rows: list[dict[str, str]], metric: str, out: Path) -> None:
    data = [
        (row["condition"], _float(row.get("mean", "")))
        for row in rows
        if row.get("metric") == metric
    ]
    data = [(condition, value) for condition, value in data if value is not None]
    if not data:
        return
    fig, ax = plt.subplots(figsize=(8, 4.8))
    labels, values = zip(*data)
    ax.bar(labels, values, color="#2563eb", alpha=0.85)
    ax.set_title(f"B5 condition means: {metric}")
    ax.set_xlabel("condition")
    ax.set_ylabel(metric)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def paired_deltas_chart(rows: list[dict[str, str]], metric: str, out: Path) -> None:
    data = [
        (row["comparison"], _float(row.get("mean_delta", "")))
        for row in rows
        if row.get("metric") == metric and row.get("comparison") in PREREGISTERED_COMPARISONS
    ]
    data = [(comparison, value) for comparison, value in data if value is not None]
    if not data:
        return
    fig, ax = plt.subplots(figsize=(8, 4.8))
    labels, values = zip(*data)
    colors = ["#2563eb" if value >= 0 else "#dc2626" for value in values]
    ax.barh(labels, values, color=colors, alpha=0.85)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title(f"B5 preregistered paired deltas: {metric}")
    ax.set_xlabel("right condition - left condition")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def render_from_report_dir(report_dir: Path, out_dir: Path | None = None,
                           metrics: tuple[str, ...] = DEFAULT_PRIMARY_METRICS) -> list[Path]:
    out_dir = out_dir or report_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    condition_rows = _read_csv(report_dir / "b5_condition_distribution.csv")
    delta_rows = _read_csv(report_dir / "b5_paired_deltas.csv")
    written: list[Path] = []
    for metric in metrics:
        condition_out = out_dir / f"chart_condition_means_{metric}.png"
        delta_out = out_dir / f"chart_paired_deltas_{metric}.png"
        before = condition_out.exists()
        condition_means_chart(condition_rows, metric, condition_out)
        if condition_out.exists() and (not before or condition_out.stat().st_size):
            written.append(condition_out)
        before = delta_out.exists()
        paired_deltas_chart(delta_rows, metric, delta_out)
        if delta_out.exists() and (not before or delta_out.stat().st_size):
            written.append(delta_out)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description="Render charts from b5_report CSV outputs")
    ap.add_argument("--report-dir", required=True, help="Directory containing b5_report CSV outputs")
    ap.add_argument("--out-dir", default=None, help="Chart output directory; defaults to --report-dir")
    ap.add_argument("--metrics", nargs="+", default=list(DEFAULT_PRIMARY_METRICS))
    args = ap.parse_args()

    written = render_from_report_dir(
        Path(args.report_dir),
        Path(args.out_dir) if args.out_dir else None,
        tuple(args.metrics),
    )
    for path in written:
        print(f"saved chart: {path}")


if __name__ == "__main__":
    main()
