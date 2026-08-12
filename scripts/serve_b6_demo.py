"""零依赖 B6 透明复现演示页；用于 Streamlit 不可安装时的现场兜底。"""
from __future__ import annotations

import hashlib
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "repro" / "releases" / "track3-system-v0.2.lock.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_count(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def page() -> str:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    rows = []
    passed = 0
    for item in lock["files"]:
        target = ROOT / item["path"]
        ok = target.is_file() and _sha256(target) == item["sha256"]
        passed += int(ok)
        rows.append(f"<tr><td>{html.escape(item['path'])}</td><td class=\"{'ok' if ok else 'bad'}\">{'一致' if ok else '已变更/缺失'}</td></tr>")
    formal = ROOT / lock["formal_requirements"]["formal_questions"]
    stress = ROOT / lock["formal_requirements"]["stress_questions"]
    formal_rows, stress_rows = _line_count(formal), _line_count(stress)
    formal_gold = sum(bool(json.loads(line).get("gold_source_ids")) for line in formal.read_text(encoding="utf-8").splitlines() if line.strip())
    stress_gold = sum(bool(json.loads(line).get("gold_source_ids")) for line in stress.read_text(encoding="utf-8").splitlines() if line.strip())
    checks = [
        ("正式题数量", formal_rows, 60), ("压力题数量", stress_rows, 20),
        ("正式题 gold 覆盖", formal_gold, formal_rows), ("压力题 gold 覆盖", stress_gold, stress_rows),
    ]
    readiness = "已就绪" if all(actual >= required and required > 0 for _, actual, required in checks) else "待 B1/B2 冻结"
    readiness_rows = "".join(
        f"<tr><td>{name}</td><td>{actual}</td><td>{required}</td><td class=\"{'ok' if actual >= required and required > 0 else 'bad'}\">{'通过' if actual >= required and required > 0 else '未满足'}</td></tr>"
        for name, actual, required in checks
    )
    return f"""<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\"><title>OpenEvidence · B6 透明复现</title>
<style>body{{font:15px/1.55 system-ui,-apple-system,'Microsoft YaHei',sans-serif;color:#172033;background:#f7f8fa;margin:0}}main{{max-width:980px;margin:42px auto;padding:0 22px}}h1{{margin:0;font-size:30px}}p{{color:#556070}}.tag{{display:inline-block;background:#e8eef7;color:#25466d;padding:3px 9px;border-radius:4px;font-size:13px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:24px 0}}.card,section{{background:#fff;border:1px solid #e1e5ea;border-radius:7px;padding:18px}}.num{{font-size:25px;font-weight:650}}h2{{font-size:18px;margin:0 0 10px}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:9px;border-bottom:1px solid #edf0f3}}th{{color:#667085;font-weight:600}}.ok{{color:#14704a;font-weight:600}}.bad{{color:#a13c31;font-weight:600}}code{{background:#f1f3f5;padding:3px 6px;border-radius:3px}}</style>
<main><span class=\"tag\">B6 · 离线验收</span><h1>透明复现</h1><p>冻结输入、验证版本、说明正式实验是否具备运行条件。</p>
<div class=\"grid\"><div class=card><div>冻结清单</div><div class=num>{'通过' if passed == len(rows) else '需检查'}</div></div><div class=card><div>锁定文件</div><div class=num>{passed}/{len(rows)}</div></div><div class=card><div>正式实验</div><div class=num>{readiness}</div></div></div>
<section><h2>冻结资产</h2><table><thead><tr><th>文件</th><th>SHA-256 校验</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section style=\"margin-top:14px\"><h2>正式实验前置条件</h2><table><thead><tr><th>项目</th><th>当前</th><th>要求</th><th>状态</th></tr></thead><tbody>{readiness_rows}</tbody></table><p>当前页面仅展示离线 fixture 验收状态，不将样例数据作为正式模型结论。</p></section>
<section style=\"margin-top:14px\"><h2>复跑命令</h2><code>python -m evaluation.reproduce --check</code><br><br><code>python -m evaluation.reproduce --offline-reference</code></section></main></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        payload = page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8501), Handler)
    print("B6 demo: http://127.0.0.1:8501")
    server.serve_forever()
