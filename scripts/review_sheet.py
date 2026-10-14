#!/usr/bin/env python3
"""Hoja de revision humana a ciegas de la tanda de F2 (protocolo-f2.md §4.8).

La puntuacion automatica no decide sola, y la revision es el unico juez que ve lo que el puntuador
no. Si sabe de quien es la respuesta, puntua la expectativa: por eso la hoja sale **barajada y con
el modelo oculto**, y la correspondencia va a un fichero de clave aparte que no se abre hasta haber
puntuado.

- `generate` lee el JSONL (hace falta `--save-responses` en el runner) y escribe la hoja en Markdown
  y la clave en JSON. Entran las corridas de calidad validas: `ok`, no descartadas y sin control de
  entrada. El orden se baraja y los numeros de item se asignan DESPUES, asi que no codifican nada.
- `unblind` lee la hoja puntuada y la clave, y da la puntuacion media por modelo y caso. Un item
  sin puntuar no se ignora: el exit code es 1 y se listan, porque una media sobre la hoja a medias
  parece una medida.

Uso:
    python scripts/review_sheet.py generate --sheet hoja.md --key clave.json resultados/*.jsonl
    python scripts/review_sheet.py unblind --sheet hoja.md --key clave.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import re
import secrets
import statistics
import sys
from pathlib import Path
from typing import Any

_ITEM_RE = re.compile(r"^## Item (\d+)\s*$")
_NOTE_RE = re.compile(r"^Puntuacion \(0/1/2\):[ \t]*(\S*)[ \t]*$")


def _load_legacy_names() -> Any:
    """`src/local_delegate/legacy_names.py`, cargado por ruta: solo usa la biblioteca estandar, y
    asi este programa lee las filas viejas con la misma tabla que el paquete sin importarlo."""
    path = Path(__file__).resolve().parents[1] / "src" / "local_delegate" / "legacy_names.py"
    spec = importlib.util.spec_from_file_location("_legacy_names", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LEGACY_NAMES = _load_legacy_names()


def _records(paths: list[Path]) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(LEGACY_NAMES.normalize_benchmark_result(json.loads(line)))
    return records


def _reviewable(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen = [
        r
        for r in records
        if r.get("kind") == "quality"
        and r.get("outcome") == "ok"
        and not r.get("discarded")
        and r.get("input_variant") is None
    ]
    unanswered = sorted(
        {f"{r.get('label')}:{r.get('case')}" for r in chosen if "response" not in r}
    )
    if unanswered:
        raise ValueError(
            "corridas sin respuesta guardada (el runner necesita --save-responses): "
            + ", ".join(unanswered)
        )
    return chosen


def _fence(text: str) -> str:
    """Una valla mas larga que cualquier racha de acentos graves de la respuesta."""
    streaks = [len(m) for m in re.findall(r"`+", text)]
    return "`" * max(3, max(streaks, default=0) + 1)


def generate(
    records: list[dict[str, Any]], corpus: dict[str, dict[str, Any]] | None, seed: int
) -> tuple[str, dict[str, Any]]:
    chosen = _reviewable(records)
    random.Random(seed).shuffle(chosen)
    lines = [
        "# Revision a ciegas",
        "",
        "Puntua cada respuesta con 0 (mal), 1 (a medias) o 2 (bien) contra su fuente, sin abrir la",
        "clave. Escribe el numero detras de «Puntuacion (0/1/2):».",
        "",
    ]
    key: dict[str, Any] = {"seed": seed, "items": {}}
    for number, record in enumerate(chosen, 1):
        item = f"{number:03d}"
        case = record["case"]
        source = ((corpus or {}).get(case) or {}).get("source_file")
        response = str(record["response"])
        fence = _fence(response)
        lines += [
            f"## Item {item}",
            "",
            f"Caso: `{case}`" + (f" · fuente: `fuentes/{source}`" if source else ""),
            "",
            fence,
            response,
            fence,
            "",
            "Puntuacion (0/1/2): ",
            "",
        ]
        key["items"][item] = {
            "label": record.get("label"),
            "model": record.get("model"),
            "case": case,
            "role": record.get("role"),
            "run": record.get("run"),
            "response_sha256": record.get("response_sha256"),
        }
    return "\n".join(lines), key


def read_notes(sheet: str) -> dict[str, int | None]:
    """Lee las notas saltandose lo que va dentro de la valla.

    La respuesta la escribio el modelo: si trae una linea «Puntuacion (0/1/2): 2» o «## Item 001»,
    leerla como nota dejaria que un modelo se puntuara a si mismo.
    """
    notes: dict[str, int | None] = {}
    current: str | None = None
    fence: str | None = None
    for line in sheet.splitlines():
        if fence is not None:
            if line == fence:
                fence = None
            continue
        if re.fullmatch(r"`{3,}", line):
            fence = line
            continue
        if m := _ITEM_RE.match(line):
            current = m.group(1)
            notes[current] = None
        elif current is not None and (m := _NOTE_RE.match(line)):
            value = m.group(1)
            if value == "":
                notes[current] = None
            elif value in {"0", "1", "2"}:
                notes[current] = int(value)
            else:
                raise ValueError(f"item {current}: puntuacion {value!r} no es 0, 1 ni 2")
            current = None
    return notes


def unblind(sheet: str, key: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    notes = read_notes(sheet)
    items = key["items"]
    if set(notes) != set(items):
        raise ValueError(
            "la hoja y la clave no tienen los mismos items: ¿son de la misma generacion?"
        )
    missing = sorted(item for item, note in notes.items() if note is None)
    per_model_case: dict[tuple[str, str], list[int]] = {}
    for item, note in notes.items():
        if note is None:
            continue
        meta = items[item]
        per_model_case.setdefault((meta["label"], meta["case"]), []).append(note)
    result = {
        f"{label}|{case}": {
            "label": label,
            "case": case,
            "n": len(values),
            "media": statistics.fmean(values),
        }
        for (label, case), values in sorted(per_model_case.items())
    }
    return result, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    sub = parser.add_subparsers(dest="mode", required=True)
    gen = sub.add_parser("generate")
    gen.add_argument("--sheet", type=Path, required=True)
    gen.add_argument("--key", type=Path, required=True)
    gen.add_argument("--cases", type=Path, default=None, help="cases.json, para citar la fuente")
    gen.add_argument(
        "--seed", type=int, default=None, help="solo para pruebas; por defecto aleatoria"
    )
    gen.add_argument("jsonl", nargs="+", type=Path)
    des = sub.add_parser("unblind")
    des.add_argument("--sheet", type=Path, required=True)
    des.add_argument("--key", type=Path, required=True)
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    try:
        if args.mode == "generate":
            if args.key.exists() or args.sheet.exists():
                # Regenerar baraja otra vez: una hoja ya puntuada quedaria emparejada con otra clave.
                raise ValueError("la hoja o la clave ya existen; elige otras rutas")
            corpus = None
            if args.cases:
                data = json.loads(args.cases.read_text(encoding="utf-8"))
                corpus = {c["id"]: c for c in data["cases"]}
            seed = args.seed if args.seed is not None else secrets.randbits(32)
            sheet, key = generate(_records(args.jsonl), corpus, seed)
            args.sheet.write_text(sheet, encoding="utf-8")
            args.key.write_text(
                json.dumps(key, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(
                f"{len(key['items'])} items en {args.sheet}; la clave en {args.key} no se abre hasta puntuar"
            )
            return 0
        result, missing = unblind(
            args.sheet.read_text(encoding="utf-8"),
            json.loads(args.key.read_text(encoding="utf-8")),
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("| Modelo | Caso | Items | Media (0-2) |")
    print("| --- | --- | --- | --- |")
    for row in result.values():
        print(f"| {row['label']} | {row['case']} | {row['n']} | {row['media']:.2f} |")
    if missing:
        print(f"\nfaltan por puntuar {len(missing)} items: {', '.join(missing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
