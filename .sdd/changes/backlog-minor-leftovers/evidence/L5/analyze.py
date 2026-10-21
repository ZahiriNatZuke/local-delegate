"""Summarizes `runs/results.jsonl` of the L5 measurement into Markdown tables (stdout)."""

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
rows = [
    json.loads(line)
    for line in (HERE / "runs" / "results.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
order = []
for r in rows:
    if r["config"] not in order:
        order.append(r["config"])

print("## Por configuración\n")
print(
    "| Config | Válidas | Truncadas | `finish_reason` ≠ stop | Fallos de control | "
    "Razonamiento (chars, mediana) | Latencia (s, mediana) | Latencia (s, máx) |"
)
print("| --- | --- | --- | --- | --- | --- | --- | --- |")
for cfg in order:
    rs = [r for r in rows if r["config"] == cfg]
    valid = sum(r["valid"] for r in rs)
    trunc = sum(bool(r["event"].get("truncated_out")) for r in rs)
    nostop = sum(r["event"].get("finish_reason") != "stop" for r in rs)
    ctrl = sum(r["control"] != "ok" for r in rs)
    rch = [r["event"].get("reasoning_chars") or 0 for r in rs]
    lat = [r["wall_ms"] / 1000 for r in rs]
    print(
        f"| {cfg} | {valid}/{len(rs)} | {trunc} | {nostop} | {ctrl} | "
        f"{statistics.median(rch):.0f} | {statistics.median(lat):.1f} | {max(lat):.1f} |"
    )

print("\n## Por celda (configuración × entrada, 3 repeticiones)\n")
print(
    "| Config | Entrada | Válidas | Truncadas | Controles | Razonamiento (chars) | "
    "`tokens_out` | Latencia (s) | Hashes distintos |"
)
print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
cells = defaultdict(list)
for r in rows:
    cells[(r["config"], r["id"])].append(r)
for (cfg, cid), rs in cells.items():
    print(
        f"| {cfg} | {cid} | {sum(r['valid'] for r in rs)}/{len(rs)} | "
        f"{sum(bool(r['event'].get('truncated_out')) for r in rs)} | "
        f"{', '.join(r['control'] for r in rs)} | "
        f"{', '.join(str(r['event'].get('reasoning_chars') or 0) for r in rs)} | "
        f"{', '.join(str(r['event'].get('tokens_out')) for r in rs)} | "
        f"{', '.join(format(r['wall_ms'] / 1000, '.1f') for r in rs)} | "
        f"{len({r['answer_sha256'] for r in rs})} |"
    )
models = {r["event"].get("model") for r in rows}
skipped = sum(bool(r["event"].get("reasoning_skipped")) for r in rows)
chunks = {r["event"].get("chunks") for r in rows}
print(
    f"\nModelos: {sorted(m for m in models if m)}; reasoning_skipped: {skipped}; chunks: {chunks}"
)
sys.exit(0)
