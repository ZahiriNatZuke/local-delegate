"""T7 (REQ-037), without the backend: the role each research case gets before and after the rule.

«Before» comes from the recorded research runs (`outputs/g3-extract.json`, `g4-extract.json`,
`evaluation.json`, `log-window-rows.json`): role, model, crossed keys and inference. «After» runs
the real `local_extract` of this tree against a backend double (`server._post_chat` replaced, a
closed port as `BASE_URL`, temporary log), so it gives the role, the model asked, `role_reason`
in the answer and in the log row, and nothing about values (those come from the live test).

Run from the repository root:

    PYTHONPATH=src python -I .sdd/changes/extract-cross-fill-and-routing/gate/routing_before_after.py

Writes `outputs/routing-before-after.json` and prints the Markdown table.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

CHANGE = Path(__file__).resolve().parents[1]
REPO = CHANGE.parents[2]
CASES_DIR = CHANGE / "cases"
OUTPUTS = CHANGE / "outputs"

_TMP = tempfile.mkdtemp(prefix="ld-586-routing-")
# Before importing the package: no real log, no real backend, no turn, fixed language.
os.environ.update(
    {
        "LOCAL_DELEGATE_LOG_DIR": _TMP,
        "LOCAL_DELEGATE_LOG": str(Path(_TMP) / "usage.jsonl"),
        "LOCAL_DELEGATE_BASE_URL": "http://127.0.0.1:9/v1",
        "LOCAL_DELEGATE_TURN_URL": "off",
        "LOCAL_DELEGATE_FEEDBACK": "0",
        "LOCAL_DELEGATE_LANG": "es",
    }
)
for name in ("LOCAL_DELEGATE_EXTRACT_TABLE_LONG", "LOCAL_DELEGATE_LONG_INPUT_CHARS"):
    os.environ.pop(name, None)
sys.path.insert(0, str(REPO / "src"))

from local_delegate import config, server  # noqa: E402

assert str(config.LOG_DIR) == _TMP, config.LOG_DIR


def _load(name: str) -> dict:
    return json.loads((OUTPUTS / name).read_text(encoding="utf-8"))


def _before_inference() -> dict[str, int]:
    """Inference per case of the research's `local_extract` rows, matched by file and order."""
    cases = json.loads((CASES_DIR / "cases.json").read_text(encoding="utf-8"))["cases"]
    rows = [r for r in _load("log-window-rows.json") if r.get("tool") == "local_extract"]
    result: dict[str, int] = {}
    for model, group in (
        ("gemma3-4b", [c for c in cases if not c.get("large")]),
        ("gemma4-26b-a4b", [c for c in cases if c.get("large")]),
    ):
        mine = [r for r in rows if r.get("model") == model]
        if len(mine) != len(group):
            continue
        if any(r.get("file") not in (c["file"], "<otro>") for r, c in zip(mine, group)):
            continue
        for row, case in zip(mine, group):
            if row.get("inf") is not None:
                result[case["id"]] = int(row["inf"])
    return result


def main() -> int:
    cases = json.loads((CASES_DIR / "cases.json").read_text(encoding="utf-8"))["cases"]
    g3, g4 = _load("g3-extract.json"), _load("g4-extract.json")
    runs = _load("evaluation.json")["runs"]
    inference = _before_inference()
    asked: list[str] = []

    def double(model: str, payload: dict) -> server.ChatResult:
        asked.append(model)
        return server.ChatResult(text="{}", ok=True, finish_reason="stop")

    server._post_chat = double
    table = []
    for case in cases:
        before_run = g4 if case.get("large") else g3
        run_name = "g4-extract" if case.get("large") else "g3-extract"
        verdicts = runs[run_name]["cases"].get(case["id"], {})
        crossed = sorted(k for k, v in verdicts.items() if v.get("verdict") == "crossed")
        asked.clear()
        log = Path(_TMP) / "usage.jsonl"
        log.unlink(missing_ok=True)
        data = server.local_extract(fields=case["fields"], path=str(CASES_DIR / case["file"]))
        rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        meta = data.get("_local_delegate", {})
        table.append(
            {
                "case": case["id"],
                "bytes": (CASES_DIR / case["file"]).stat().st_size,
                "has_table": case["has_table"],
                "before": {
                    "role": before_run["_run"]["role"],
                    "model": before_run["_run"]["model"],
                    "crossed": crossed,
                    "inference_ms": inference.get(case["id"]),
                },
                "after": {
                    "models_asked": list(asked),
                    "role": (meta.get("role_reason") or {}).get("role")
                    or ("long" if asked == [config.MODEL_LONG] else "mechanical"),
                    "role_reason_answer": (meta.get("role_reason") or {}).get("reason"),
                    "role_reason_log": [r.get("role_reason") for r in rows],
                },
            }
        )
    (OUTPUTS / "routing-before-after.json").write_text(
        json.dumps({"backend": "double, no network", "cases": table}, indent=1, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print("| Caso | Bytes | Tabla | Antes: rol / modelo | Antes: cruzadas | Antes: inf. (ms) "
          "| Después: rol / modelo | `role_reason` (respuesta / log) |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in table:
        b, a = row["before"], row["after"]
        print(
            f"| {row['case'][:2]} | {row['bytes']} | {'sí' if row['has_table'] else 'no'} "
            f"| {b['role']} / `{b['model']}` | {len(b['crossed'])} | {b['inference_ms'] or '—'} "
            f"| {a['role']} / `{'`, `'.join(a['models_asked'])}` "
            f"| {a['role_reason_answer'] or '—'} / {','.join(x or '—' for x in a['role_reason_log'])} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
