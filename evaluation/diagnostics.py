from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Dict


def json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            if hasattr(row, "to_dict"):
                row = row.to_dict()
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=json_default))
            f.write("\n")


def config_hash(config_text: str) -> str:
    return hashlib.sha256(config_text.encode("utf-8")).hexdigest()[:16]


def retrieval_trace(run_id: str, condition: str, result: Any) -> Dict[str, Any]:
    payload = result.to_dict() if hasattr(result, "to_dict") else result
    return {
        "run_id": run_id,
        "condition": condition,
        "retrieval": payload,
    }

