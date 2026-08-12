"""B6 版本冻结、完整性校验与结果包溯源工具。"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCK = ROOT / "repro" / "releases" / "track3-system-v0.2.lock.json"


def sha256_file(path: Path) -> str:
    """以流式方式计算文件哈希，避免把大语料整体读入内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit(root: Path = ROOT) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def load_lock(path: str | Path = DEFAULT_LOCK) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def verify_release_lock(path: str | Path = DEFAULT_LOCK, root: Path = ROOT) -> dict[str, Any]:
    """校验冻结清单列出的资产是否仍与提交时一致。"""
    lock_path = Path(path)
    lock = load_lock(lock_path)
    checks: list[dict[str, Any]] = []
    for item in lock.get("files", []):
        relative = item["path"]
        target = root / relative
        if not target.is_file():
            checks.append({"path": relative, "status": "missing", "expected": item["sha256"], "actual": ""})
            continue
        actual = sha256_file(target)
        checks.append({
            "path": relative,
            "status": "ok" if actual == item["sha256"] else "changed",
            "expected": item["sha256"],
            "actual": actual,
        })
    return {
        "release_id": lock.get("release_id", ""),
        "lock_path": str(lock_path.relative_to(root)) if lock_path.is_relative_to(root) else str(lock_path),
        "checks": checks,
        "passed": all(row["status"] == "ok" for row in checks),
    }


def _jsonl_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def formal_readiness(path: str | Path = DEFAULT_LOCK, root: Path = ROOT) -> dict[str, Any]:
    """判断正式实验是否具备 B1 协议要求；不足时只报告，不伪装为正式冻结。"""
    lock = load_lock(path)
    policy = lock.get("formal_requirements", {})
    formal_path = root / policy.get("formal_questions", "data/questions/formal12.jsonl")
    stress_path = root / policy.get("stress_questions", "data/questions/stress_sample.jsonl")
    formal = _jsonl_rows(formal_path) if formal_path.is_file() else []
    stress = _jsonl_rows(stress_path) if stress_path.is_file() else []
    formal_gold = sum(bool(row.get("gold_source_ids")) for row in formal)
    stress_gold = sum(bool(row.get("gold_source_ids")) for row in stress)
    checks = [
        {
            "name": "正式题数量",
            "actual": len(formal),
            "required": policy.get("formal_question_count", 60),
            "passed": len(formal) >= policy.get("formal_question_count", 60),
        },
        {
            "name": "压力题数量",
            "actual": len(stress),
            "required": policy.get("stress_question_count", 20),
            "passed": len(stress) >= policy.get("stress_question_count", 20),
        },
        {
            "name": "正式题 gold 覆盖",
            "actual": formal_gold,
            "required": len(formal),
            "passed": bool(formal) and formal_gold == len(formal),
        },
        {
            "name": "压力题 gold 覆盖",
            "actual": stress_gold,
            "required": len(stress),
            "passed": bool(stress) and stress_gold == len(stress),
        },
    ]
    return {"ready": all(item["passed"] for item in checks), "checks": checks}


def validate_run_jsonl(runs_path: Path, schema_path: Path | None = None) -> dict[str, Any]:
    """按 B1 Run schema 验证结果包内的每条 Run。"""
    import jsonschema

    schema_path = schema_path or ROOT / "evaluation" / "schemas" / "run.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors: list[dict[str, Any]] = []
    rows = _jsonl_rows(runs_path)
    for line_no, row in enumerate(rows, 1):
        try:
            jsonschema.validate(row, schema)
        except jsonschema.ValidationError as exc:
            errors.append({"line": line_no, "run_id": row.get("run_id", ""), "message": exc.message})
    return {"run_count": len(rows), "valid": not errors, "errors": errors}


def runtime_fingerprint() -> dict[str, Any]:
    packages = {}
    for name in ("PyYAML", "jsonschema", "numpy", "pandas", "scipy", "matplotlib", "streamlit", "rank-bm25"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not-installed"
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": packages,
    }


def write_integrity_manifest(bundle_dir: Path) -> dict[str, Any]:
    """写出结果包所有文件的哈希；完整性清单自身不纳入哈希列表。"""
    records = []
    for path in sorted(bundle_dir.rglob("*")):
        if path.is_file() and path.name != "integrity.json":
            records.append({"path": path.relative_to(bundle_dir).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    result = {"algorithm": "sha256", "files": records}
    (bundle_dir / "integrity.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def verify_bundle(bundle_dir: Path) -> dict[str, Any]:
    """校验结果包文件是否被删除或修改。"""
    integrity_path = bundle_dir / "integrity.json"
    if not integrity_path.is_file():
        return {"valid": False, "reason": "missing integrity.json", "checks": []}
    data = json.loads(integrity_path.read_text(encoding="utf-8"))
    checks = []
    for item in data.get("files", []):
        target = bundle_dir / item["path"]
        if not target.is_file():
            checks.append({"path": item["path"], "status": "missing"})
        elif sha256_file(target) != item["sha256"]:
            checks.append({"path": item["path"], "status": "changed"})
        else:
            checks.append({"path": item["path"], "status": "ok"})
    return {"valid": all(row["status"] == "ok" for row in checks), "checks": checks}
