#!/usr/bin/env python3
"""Comprueba los mínimos de los registros de ola (`waves/<ola>.md`, plan §2.1; REQ-036 y REQ-037).

Para cada registro:

- la tabla de llamadas `local_*` tiene la fila de `local_lint_summary` (el resumen de la suite);
- la tabla de controles positivos tiene al menos una fila, y cada fila dice el assert que disparó;
- si el registro cita mappings (`waves/<…>-mapping.csv`, olas que renombran Python):
  - cada mapping existe y lleva la cabecera `# approved-by-main`;
  - las filas `rename_refactoring` de la tabla de PyCharm son tantas como las filas
    `method=pycharm` de sus mappings;
  - cada fila `search_edit` lleva su motivo;
  - todas las filas `cross_module` y `unresolved` tienen `verified` rellena; se cuentan las
    discrepancias;
  - hay al menos un `get_file_problems` o `lint_files`;
- si no cita mappings (A8b y las olas B): al menos un `search_text` o `search_regex` y un
  `get_file_problems`/`lint_files`, o una fila que diga el motivo de no tenerlos.

Escribe el informe en `evidence/conformance/wave-records.txt` (o `--out`) y sale con 1 si algún
registro no cumple.

Uso:
    python check_wave_records.py [--waves-dir DIR] [--out FICHERO] [registro.md …]
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

CHANGE_DIR = Path(__file__).resolve().parents[1]
MAPPING_RE = re.compile(r"waves/([\w.\-]+-mapping\.csv)")


@dataclass
class RecordCheck:
    record: str
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def sections(text: str) -> dict[str, list[str]]:
    """`{título de sección ##: líneas}`."""
    out: dict[str, list[str]] = {}
    current = ""
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            out[current] = []
        else:
            out.setdefault(current, []).append(line)
    return out


def table_rows(lines: list[str]) -> list[list[str]]:
    """Filas de datos de la primera tabla de la sección (sin cabecera ni separador)."""
    rows: list[list[str]] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                in_table = True  # cabecera
                continue
            if all(set(c) <= set("-: ") for c in cells):
                continue
            rows.append(cells)
        elif in_table and stripped and not stripped.startswith("<!--"):
            break
    return rows


def _section(secs: dict[str, list[str]], prefix: str) -> list[str]:
    for title, lines in secs.items():
        if title.lower().startswith(prefix.lower()):
            return lines
    return []


def read_mapping(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = path.read_text(encoding="utf-8")
    comments = [line for line in text.splitlines() if line.startswith("#")]
    body = [line for line in text.splitlines() if not line.startswith("#")]
    return comments, list(csv.DictReader(body))


def check_record(path: Path, waves_dir: Path) -> RecordCheck:
    result = RecordCheck(path.name)
    text = path.read_text(encoding="utf-8")
    secs = sections(text)

    local_rows = table_rows(_section(secs, "Llamadas `local_*`"))
    if not any("local_lint_summary" in " ".join(r) for r in local_rows):
        result.problems.append(
            "falta la fila de local_lint_summary en la tabla de llamadas local_*"
        )

    controls = table_rows(_section(secs, "Controles positivos"))
    if not controls:
        result.problems.append("la tabla de controles positivos está vacía")
    for row in controls:
        if len(row) < 3 or not row[2].strip():
            result.problems.append(f"control positivo sin el assert que disparó: {row[0]}")

    pycharm_rows = table_rows(_section(secs, "Llamadas `mcp__pycharm__*`"))
    tools = [r[1] if len(r) > 1 else "" for r in pycharm_rows]
    renames = sum("rename_refactoring" in t for t in tools)
    problems_calls = sum(("get_file_problems" in t) or ("lint_files" in t) for t in tools)
    searches = sum(("search_text" in t) or ("search_regex" in t) for t in tools)

    mappings = sorted(set(MAPPING_RE.findall(text)))
    if mappings:
        pycharm_defs = 0
        for name in mappings:
            mpath = waves_dir / name
            if not mpath.is_file():
                result.problems.append(f"no existe el mapping {name}")
                continue
            comments, rows = read_mapping(mpath)
            if not any(c.startswith("# approved-by-main") for c in comments):
                result.problems.append(f"{name} sin la cabecera «# approved-by-main»")
            pycharm_defs += sum(r.get("method") == "pycharm" for r in rows)
            for r in rows:
                if r.get("method") == "search_edit" and not (r.get("reason") or "").strip():
                    result.problems.append(f"{name}: fila search_edit sin motivo ({r.get('old')})")
                if (
                    r.get("scope") in ("cross_module", "unresolved")
                    and not (r.get("verified") or "").strip()
                ):
                    result.problems.append(
                        f"{name}: {r.get('old')} ({r.get('scope')}) sin verificar"
                    )
            discrepancies = sum((r.get("verified") or "").startswith("discrepancia") for r in rows)
            result.notes.append(f"{name}: {len(rows)} filas, {discrepancies} discrepancia(s)")
        if renames != pycharm_defs:
            result.problems.append(
                f"filas rename_refactoring ({renames}) ≠ filas method=pycharm de los mappings "
                f"({pycharm_defs})"
            )
        if not problems_calls:
            result.problems.append("ninguna llamada get_file_problems/lint_files registrada")
    else:
        has_reason = any("motivo" in " ".join(r).lower() for r in pycharm_rows)
        if not has_reason and (not searches or not problems_calls):
            result.problems.append(
                "sin mapping: hace falta al menos un search_text/search_regex y un "
                "get_file_problems/lint_files, o su motivo"
            )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("records", nargs="*", type=Path)
    parser.add_argument("--waves-dir", type=Path, default=CHANGE_DIR / "waves")
    parser.add_argument(
        "--out", type=Path, default=CHANGE_DIR / "evidence" / "conformance" / "wave-records.txt"
    )
    args = parser.parse_args(argv)

    records = args.records or sorted(args.waves_dir.glob("*.md"))
    results = [check_record(r, args.waves_dir) for r in records]
    lines = []
    for res in results:
        lines.append(f"{'OK   ' if res.ok else 'FALLA'} {res.record}")
        lines += [f"      - {p}" for p in res.problems]
        lines += [f"      · {n}" for n in res.notes]
    lines.append(
        f"{sum(r.ok for r in results)}/{len(results)} registro(s) cumplen los mínimos de §2.1"
    )
    report = "\n".join(lines) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8", newline="\n")
    sys.stdout.write(report)
    return 0 if results and all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
