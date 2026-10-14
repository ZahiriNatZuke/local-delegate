#!/usr/bin/env python3
"""Etapa 1 del SDD `resumen-por-secciones`: ¿sigue `local_summarize` la estructura? Sin cuota.

Llama la tool por el `/mcp` del daemon (backend real) con las copias fijas de
`benchmarks/resumen-estructurado/fuentes/` y mide **en la salida de la tool**, no en la respuesta
de Claude:

- **cobertura**: títulos esperados emparejados por línea de título y en orden, **sin contar** los
  que completó el servidor (llevan «(sin resumir)»);
- **con contenido**: emparejados con al menos 5 palabras debajo;
- **fuera de orden**: títulos presentes pero fuera de su sitio;
- **palabras** del texto sin títulos ni avisos, contra `max_words`;
- `finish_reason`, `truncated_out` y latencia, del evento de uso de la llamada.

El emparejamiento es el de producción (`local_delegate.sections`): una sola fuente. Por eso los
controles de `tests/test_measure_structured_summary.py` llevan el resultado esperado escrito a
mano. El banco de T5 (`adoption_experiment.title_coverage`) no se toca: su línea base se
midió con su normalización.

Criterio (spec REQ-208, escrito antes de medir): pasa si en README, `Integration-install.md` y
`Daemon.md` la cobertura es ≥ 0,9, todos los emparejados tienen contenido y no hay fuera de orden;
el CHANGELOG, igual y sin `length`; el documento corto (4B), cobertura ≥ 0,9. Más el juicio del
usuario sobre los tres primeros, que este script no puede dar: deja las salidas en `--outputs`.

Solo guarda en el repo las métricas; las salidas (contenido) van fuera, a `%TEMP%`. El token del
daemon se lee de la variable de usuario `LOCAL_DELEGATE_WEB_TOKEN` y nunca se imprime.

Uso:
    uv run python scripts/measure_structured_summary.py --label main
    uv run python scripts/measure_structured_summary.py --label rama
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from local_delegate import legacy_names, sections

ROOT = Path(__file__).parents[1]
BENCH = ROOT / "benchmarks" / "resumen-estructurado"
SOURCES_DIR = BENCH / "fuentes"
URL = "http://127.0.0.1:9393/mcp"
MIN_CONTENT = 5
THRESHOLD = 0.9

CALLS = [
    {"id": "readme", "file": "readme.md", "max_words": 500, "judgement": True},
    {"id": "installation", "file": "integration-install.md", "max_words": 500, "judgement": True},
    {"id": "daemon", "file": "daemon.md", "max_words": 500, "judgement": True},
    {"id": "changelog", "file": "changelog.md", "max_words": 500, "no_length": True},
    {"id": "short-4b", "file": "llama-swap-blackwell.md", "max_words": 500},
    {
        "id": "daemon-focus",
        "file": "daemon.md",
        "max_words": 500,
        "focus": "puertos, variables y rutas",
        "informative": True,
    },
]

# Los recibos en las dos formas (B2a): una salida guardada puede estar en cualquiera de los dos idiomas.
_WARNING = re.compile(
    r"^\s*(\[local-delegate [^\]]*\]"
    r"|\((leído server-side|resumido de|read server-side|summarized from) .*\))\s*$"
)


# --- Métrica (pura) -------------------------------------------------------------------------------


def measure(output: str, expected: list[str], max_words: int) -> dict:
    """Las métricas de una salida frente a los títulos esperados del documento."""
    emp = sections.match_headings(output, expected, min_content=MIN_CONTENT)
    lines = output.split("\n")
    order = sorted(emp.pairs.items(), key=lambda par: par[1])
    completed = 0
    with_content = 0
    for pos, (_k, line) in enumerate(order):
        end = order[pos + 1][1] if pos + 1 < len(order) else len(lines)
        body = "\n".join(x for x in lines[line + 1 : end] if not _WARNING.match(x)).strip()
        if body in sections.NOT_SUMMARIZED_FORMS:
            completed += 1
        elif len(re.findall(r"\w+", body)) >= MIN_CONTENT:
            with_content += 1
    paired = len(emp.pairs) - completed
    headings = {line for line, _ in sections.heading_lines(output)}
    words = sum(
        len(re.findall(r"\w+", x))
        for i, x in enumerate(lines)
        if i not in headings
        and not _WARNING.match(x)
        and x.strip() not in sections.NOT_SUMMARIZED_FORMS
    )
    coverage = paired / len(expected) if expected else 0.0
    return {
        "expected": len(expected),
        "paired": paired,
        "completed_by_server": completed,
        "with_content": with_content,
        "out_of_order": len(emp.out_of_order),
        "coverage": round(coverage, 3),
        "words": words,
        "max_words": max_words,
        "passes_structure": (
            coverage >= THRESHOLD and with_content == paired and not emp.out_of_order
        ),
    }


def subsection_coverage(output: str, subtitles: list[str]) -> dict:
    """Informativa (v3): cuántas subsecciones se nombran en algún sitio de la salida.

    No decide nada: el prompt pide nombrarlas en negrita dentro de su sección, pero la métrica que
    decide sigue siendo la del nivel estructural.
    """
    body = " " + sections.normalize_heading(output) + " "
    named = sum(f" {sections.normalize_heading(t)} " in body for t in subtitles)
    return {"total": len(subtitles), "named": named}


def verdict(results: dict[str, dict]) -> dict:
    """Aplica el criterio de la spec a las métricas (sin el juicio humano, que va aparte)."""
    main_ones = [results.get(k, {}) for k in ("readme", "installation", "daemon")]
    changelog = results.get("changelog", {})
    short = results.get("short-4b", {})
    return {
        "three_documents": all(r.get("passes_structure") for r in main_ones),
        "changelog": bool(changelog.get("passes_structure"))
        and changelog.get("finish_reason") != "length",
        # Desde la v3 el modelo mecánico resume en prosa (criterio del 4B): lo que se comprueba es
        # que el documento corto NO fue por el modo estructurado.
        "short_4b_in_prose": bool(short) and short.get("log_sections") is None,
        "pending": "juicio del usuario sobre readme, instalacion y daemon",
    }


# --- Llamadas al daemon ---------------------------------------------------------------------------


def _token() -> str:
    token = os.environ.get("LOCAL_DELEGATE_WEB_TOKEN", "")
    if token or sys.platform != "win32":
        return token
    output = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "[Environment]::GetEnvironmentVariable('LOCAL_DELEGATE_WEB_TOKEN','User')",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return output.stdout.strip()


async def _call(arguments: dict) -> tuple[str, bool]:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": f"Bearer {_token()}"}
    async with (
        httpx2.AsyncClient(headers=headers, timeout=900) as client,
        streamable_http_client(URL, http_client=client) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        res = await session.call_tool("local_summarize", arguments)
        text = "".join(getattr(c, "text", "") for c in res.content)
        return text, bool(res.is_error)


def _usage_event(path: Path, since: str) -> dict:
    """El último evento de `local_summarize` para esa ruta escrito después de `desde`."""
    folder = Path(os.environ.get("LOCALAPPDATA", "")) / "local-delegate"
    events = []
    for log in sorted(folder.glob("usage-*.jsonl")):
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if (
                e.get("tool") == "local_summarize"
                and e.get("ts", "") >= since
                and Path(e.get("path") or "") == path
            ):
                events.append(e)
    return events[-1] if events else {}


def execute(label: str, outputs: Path) -> int:
    outputs.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}
    for call in CALLS:
        path = (SOURCES_DIR / call["file"]).resolve()
        document = path.read_text(encoding="utf-8")
        plan = sections.sections_for_summary(document, sections.detect(document))
        expected = [s.heading for s in plan]
        subtitles = [t for s in plan for t in s.subheadings]
        arguments = {"path": str(path), "max_words": call["max_words"]}
        if "focus" in call:
            arguments["focus"] = call["focus"]
        since = datetime.now(UTC).isoformat(timespec="seconds")
        start = time.monotonic()
        try:
            text, error = asyncio.run(_call(arguments))
        except Exception as exc:
            text, error = f"[excepción] {type(exc).__name__}: {exc}", True
        seconds = round(time.monotonic() - start, 1)
        (outputs / f"{call['id']}.md").write_text(text, encoding="utf-8")
        row = measure(text, expected, call["max_words"])
        row["subsections"] = subsection_coverage(text, subtitles)
        row["introduction"] = bool(sections.INTRODUCTION_FORMS & set(expected))
        event = _usage_event(path, since)
        row.update(
            {
                "error": error,
                "seconds": seconds,
                "finish_reason": event.get("finish_reason"),
                "truncated_out": bool(event.get("truncated_out")),
                "chunks": event.get("chunks", 1),
                "model": event.get("model"),
                "log_sections": legacy_names.read_key(event, "sections", "secciones"),
                "focus_log": bool(event.get("focus")),
            }
        )
        results[call["id"]] = row
        print(
            f"{call['id']:13} cob={row['coverage']:.2f} "
            f"({row['paired']}/{row['expected']}, completadas "
            f"{row['completed_by_server']}) contenido={row['with_content']} "
            f"orden={row['out_of_order']} palabras={row['words']}/{row['max_words']} "
            f"fin={row['finish_reason']} {seconds}s {row['model']} error={error}"
        )
    report = {
        "label": label,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "results": results,
        "verdict": verdict(results),
    }
    dest = BENCH / f"results-{label}.json"
    dest.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(report["verdict"], ensure_ascii=False, indent=2))
    print(f"Métricas en {dest.relative_to(ROOT)}; salidas para el juicio humano en {outputs}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--label", required=True, help="p. ej. main o rama")
    parser.add_argument("--outputs", type=Path, help="dónde dejar las salidas (fuera del repo)")
    args = parser.parse_args(argv)
    outputs = args.outputs or Path(tempfile.gettempdir()) / "measure-summary" / args.label
    if ROOT in outputs.resolve().parents:
        parser.error("--outputs tiene que estar fuera del repo: son contenido")
    return execute(args.label, outputs)


if __name__ == "__main__":
    sys.exit(main())
