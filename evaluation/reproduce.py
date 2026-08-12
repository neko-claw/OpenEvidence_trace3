"""B6 单一入口：校验冻结包、离线复跑并生成可审计结果包。"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from evaluation.b5_report import DEFAULT_COMPARISONS, DEFAULT_METRICS, run_b5_report
from evaluation.provenance import (
    DEFAULT_LOCK,
    ROOT,
    formal_readiness,
    git_commit,
    load_lock,
    runtime_fingerprint,
    validate_run_jsonl,
    verify_bundle,
    verify_release_lock,
    write_integrity_manifest,
)


def _jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _bundle_dir(release_id: str, output: str | None) -> Path:
    if output:
        return Path(output).resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "artifacts" / "b6" / release_id / stamp


def _copy_inputs(bundle: Path, lock: dict) -> None:
    inputs = bundle / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    for item in lock.get("files", []):
        source = ROOT / item["path"]
        target = inputs / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def offline_reference(lock_path: Path, output: str | None) -> dict:
    lock = load_lock(lock_path)
    bundle = _bundle_dir(lock["release_id"], output)
    if bundle.exists() and any(bundle.iterdir()):
        raise SystemExit(f"结果包目录非空，拒绝覆盖：{bundle}")
    bundle.mkdir(parents=True, exist_ok=True)
    _copy_inputs(bundle, lock)

    command = [
        sys.executable, "-m", "evaluation.run_conditions",
        "--retriever", "fixture", "--condition", "C,D,E", "--split", "ALL",
        "--final-k", "4", "--seed", "7", "--output-dir", str(bundle / "b4"),
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (bundle / "runner.log").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise SystemExit(f"离线运行失败，见 {bundle / 'runner.log'}")

    run_files = sorted((bundle / "b4").glob("runs-*.jsonl"))
    if len(run_files) != 1:
        raise SystemExit("未找到唯一的 B4 Run JSONL 输出")
    runs_path = run_files[0]
    shutil.copy2(runs_path, bundle / "runs.jsonl")
    validation = validate_run_jsonl(bundle / "runs.jsonl")
    (bundle / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not validation["valid"]:
        raise SystemExit("Run Schema 校验失败，结果包已保留供检查")

    questions = _jsonl(ROOT / "data" / "fixtures" / "questions.jsonl")
    summary = run_b5_report(
        runs=_jsonl(bundle / "runs.jsonl"), judge_scores=[], questions=questions,
        out_dir=bundle / "b5", runs_path=str(bundle / "runs.jsonl"), scores_path=None,
        metrics=DEFAULT_METRICS, comparisons=DEFAULT_COMPARISONS,
    )
    manifest = {
        "release_id": lock["release_id"],
        "profile": "offline-reference",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "code_commit": git_commit(),
        "command": command,
        "runtime": runtime_fingerprint(),
        "release_lock": verify_release_lock(lock_path),
        "formal_readiness": formal_readiness(lock_path),
        "run_validation": validation,
        "b5_summary": "b5/b5_summary.json",
        "run_count": validation["run_count"],
        "note": "此包为固定 fixture 的离线链路验收；不代表正式模型实验结论。",
        "b5_conditions_seen": summary["expected_conditions"]["present"],
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_integrity_manifest(bundle)
    return {"bundle": str(bundle), "run_count": validation["run_count"], "valid": validation["valid"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="B6 reproducibility and transparent release workflow")
    parser.add_argument("--lock", default=str(DEFAULT_LOCK), help="B6 release lock JSON")
    parser.add_argument("--check", action="store_true", help="只校验冻结清单与正式题前置条件")
    parser.add_argument("--offline-reference", action="store_true", help="运行固定 fixture，生成 B6 离线结果包")
    parser.add_argument("--replay", help="只校验已有结果包完整性，不调用模型")
    parser.add_argument("--output", help="离线结果包目录；默认 artifacts/b6/<release>/<time>")
    args = parser.parse_args()
    selected = sum(bool(value) for value in (args.check, args.offline_reference, args.replay))
    if selected != 1:
        parser.error("请选择且仅选择 --check、--offline-reference 或 --replay")

    lock_path = Path(args.lock).resolve()
    if args.check:
        result = {"release_lock": verify_release_lock(lock_path), "formal_readiness": formal_readiness(lock_path)}
    elif args.replay:
        result = verify_bundle(Path(args.replay).resolve())
    else:
        result = offline_reference(lock_path, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("valid", result.get("release_lock", {}).get("passed", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
