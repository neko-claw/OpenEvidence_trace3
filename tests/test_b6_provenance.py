"""B6 冻结清单和结果包完整性回归测试。"""
from __future__ import annotations

import json
from pathlib import Path

from evaluation.provenance import DEFAULT_LOCK, formal_readiness, verify_bundle, verify_release_lock, write_integrity_manifest


def test_release_lock_matches_current_fixture_assets():
    result = verify_release_lock(DEFAULT_LOCK)
    assert result["passed"], result["checks"]


def test_current_sample_cannot_be_labelled_as_formal_release():
    result = formal_readiness(DEFAULT_LOCK)
    assert result["ready"] is False
    assert {item["name"] for item in result["checks"]} == {
        "正式题数量", "压力题数量", "正式题 gold 覆盖", "压力题 gold 覆盖",
    }


def test_integrity_manifest_detects_changes(tmp_path: Path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    payload = bundle / "manifest.json"
    payload.write_text(json.dumps({"release_id": "test"}), encoding="utf-8")
    write_integrity_manifest(bundle)
    assert verify_bundle(bundle)["valid"]
    payload.write_text(json.dumps({"release_id": "changed"}), encoding="utf-8")
    assert verify_bundle(bundle)["valid"] is False
