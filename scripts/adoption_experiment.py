#!/usr/bin/env python3
"""Experimento de adopción: ¿qué oferta de los hooks hace que el modelo delegue? (REQ-102)

**Cerrado el 2026-09-23 con el piloto (`--pilot`):** las variantes no se distinguieron (las 9
corridas delegaron, V0 incluida, y 7 releyeron porque el resumen local no sigue la estructura), así
que V1 y V2 se retiraron de los hooks. Hoy las tres «variantes» corren los mismos hooks: el script
queda como registro y como base para medir un resumen que respete la estructura. Resultado en
`.sdd/changes/subagente-lector-local/verification.md`.

SDD `subagente-lector-local`, spec v2 y plan v4.1, tarea 5. Corre con `claude -p`, en sesiones
nuevas, 8 tareas que exigen leer un fichero grande, bajo V0 (el texto de siempre), V1 (receta
lista) y V2 (receta + permiso en el prompt), R veces cada una, en orden intercalado con semilla.
El prompt NUNCA menciona delegar: lo que se mide es si la oferta de los hooks basta.

Reglas escritas antes de correr (plan v4.1, T5):

- **Válida**: la telemetría de la corrida trae el evento del hook de prompt con su `session_id`
  y el bloqueo encendido (hasta la retirada de V1/V2 exigía además la oferta esperada). Si no, se
  repite (2 veces como mucho; a la tercera la tanda aborta).
- **Correcta**: el hecho plantado está en la respuesta y el contenido del fichero no entró al
  contexto principal (ni `Read` completo, ni por franjas, ni volcado por Bash).
- **Supera a V0 en una tarea**: más corridas correctas que V0 en esa tarea.
- **Se elige** la variante que supera a V0 en más tareas, mínimo 3 de 8. Desempate: menor coste
  medio sobre sus corridas válidas; después la más simple (V1 < V2). Si ninguna llega, ninguna.

Guarda cada corrida al terminarla (`--resume` sigue donde se quedó) y nunca guarda rutas ni
contenido: solo ids, variante, métricas y el veredicto.

Uso:
    uv run python scripts/adoption_experiment.py --bench %TEMP%\\banco-adopcion
    uv run python scripts/adoption_experiment.py --bench ... --resume
    uv run python scripts/adoption_experiment.py --report-only results.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).parent))
import _claude_bench as bench

from local_delegate import legacy_names

ROOT = Path(__file__).parents[1]
TASKS = ROOT / "benchmarks" / "adopcion-directa" / "tareas.json"
#: Lo escriben `test_sessions.py` y `bench.anotar_ventana`; el de antes (`ventanas-excluidas.json`,
#: congelado en `benchmarks/`) solo se lee, si el nuevo no existe.
WINDOWS = ROOT / "benchmarks" / legacy_names.EXCLUDED_WINDOWS_FILE_NAMES[1]
VARIANTS = ("v0", "v1", "v2")
SIMPLICITY = {"v1": 1, "v2": 2}
MIN_TASKS = 3
REINTENTOS = 2
CONNECTORS = ("aurora", "boreal", "cierzo", "delta", "estela", "fenix", "granito", "halcon")


def load_tasks() -> list[dict]:
    """Las tareas del corpus congelado (`tareas.json`, que no se reescribe), con sus claves en el
    formato nuevo (`tasks`, `source`, `command`, `style`, `name`)."""
    data = legacy_names.normalize("adoption_tasks", json.loads(TASKS.read_text(encoding="utf-8")))
    return [legacy_names.normalize("adoption_tasks", t) for t in data["tasks"]]


# --- Ficheros con hecho plantado ------------------------------------------------------------------


def source_text(task: dict, cache: Path, sources: Path | None = None) -> str:
    """El texto base de la tarea: un fichero del repo o la salida de un comando (cacheada).

    Con `fuentes` (una carpeta de copias fijas con su `MANIFEST.json` al lado), los ficheros del
    repo se leen de esas copias: así una tanda mide el mismo documento aunque el repo cambie
    después (SDD resumen-por-secciones, N3).
    """
    source = task["source"]
    if "repo" in source:
        if sources is not None:
            manifest = legacy_names.normalize(
                "sources_manifest",
                json.loads((sources.parent / "MANIFEST.json").read_text(encoding="utf-8")),
            )
            by_origin = {
                legacy_names.normalize("sources_manifest", d)["origin"]: n
                for n, d in manifest["files"].items()
            }
            return (sources / by_origin[source["repo"]]).read_text(encoding="utf-8")
        return (ROOT / source["repo"]).read_text(encoding="utf-8")
    dest = cache / f"{task['id']}.txt"
    if not dest.is_file():
        output = subprocess.run(
            source["command"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        cache.mkdir(parents=True, exist_ok=True)
        dest.write_text(output.stdout, encoding="utf-8")
    text = dest.read_text(encoding="utf-8")
    cap = task.get("max_bytes")
    return text[:cap] if cap else text


def plant(text: str, style: str, rng: random.Random) -> tuple[str, str, str]:
    """(texto con el hecho, conector, valor). El hecho va hacia la mitad, en una frontera de línea."""
    connector = rng.choice(CONNECTORS)
    value = str(rng.randint(100, 999))
    if style == "md":
        done = (
            f"\n## Nota de mantenimiento\n\nEl umbral de reintentos del conector {connector} quedó "
            f"fijado en {value}.\n\n"
        )
    else:
        done = f"2026-09-22T10:00:00Z WARN conector {connector}: umbral de reintentos fijado en {value}\n"
    lines = text.splitlines(keepends=True)
    cut = len(lines) // 2 + rng.randint(-len(lines) // 8, len(lines) // 8)
    return "".join(lines[:cut]) + done + "".join(lines[cut:]), connector, value


def question(path: Path, style: str) -> str:
    """Una pregunta de COMPRENSIÓN: exige leer el fichero entero, o delegar su lectura.

    La primera versión preguntaba por el dato plantado («¿en cuánto quedó el umbral del conector
    X?») y en el control instalado (tarea 4) el modelo lo resolvió con `Grep` en las tres
    variantes, sin leer ni delegar: la tarea no exigía leer, que es lo que pide REQ-102, y el
    experimento no habría podido distinguir nada. Un resumen no se saca con `Grep`. El hecho
    plantado sigue sirviendo de comprobación: la pregunta pide las cifras, sin decir cuál.
    """
    subject = "este log" if style == "log" else "este documento"
    return (
        f"Tengo {subject}: {path}\nResúmelo en 5 puntos e incluye todas las cifras de configuración "
        "que aparezcan."
    )


# --- Piloto: resumen sin datos concretos, corregido por los títulos de sección -------------------
#
# En la tarea 4 la pregunta de «todas las cifras» hizo que las tres variantes delegaran y luego
# releyeran, porque el resumen local pierde cifras: el experimento no podía distinguir la oferta.
# El piloto pide un resumen que siga la estructura, sin nombrar las secciones (si las nombrase,
# un `Grep '^## '` la resolvería sin leer), y lo da por bueno si nombra casi todos los títulos.

PILOT_TASKS = ("readme", "wiki-instalacion", "wiki-daemon")
MIN_COVERAGE = 0.8


def pilot_question(path: Path) -> str:
    return (
        f"Tengo este documento: {path}\nHazme un resumen organizado siguiendo su estructura, "
        "para decidir qué partes leer con calma."
    )


def _normal(text: str) -> str:
    return " ".join(re.sub(r"[`*_\[\]()¿?¡!:]", " ", text).lower().split())


def section_titles(text: str) -> list[str]:
    return [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]


def title_coverage(response: str, headings: list[str]) -> float:
    """Fracción de los títulos `##` que aparecen, normalizados, en la respuesta."""
    if not headings:
        return 0.0
    body = _normal(response)
    return sum(_normal(t) in body for t in headings) / len(headings)


# --- Plan de corridas y veredicto (puro: se prueba sin lanzar nada) --------------------------------


def run_plan(
    ids: list[str], repetitions: int, seed: int, variants: tuple[str, ...] = VARIANTS
) -> list[tuple[str, str, int]]:
    runs = [(t, v, r) for t in ids for v in variants for r in range(repetitions)]
    random.Random(seed).shuffle(runs)
    return runs


def summary_report(rows: list[dict]) -> dict:
    """Informe de la etapa 2 del SDD resumen-por-secciones: se decide solo por correctas.

    «Correcta» ya exige que el contenido no entrara al contexto; las corridas con el contenido en
    el contexto (`content_in_context`, la misma definición que en T5) se informan aparte, con
    el desglose por tarea para no leer un total como uniforme.
    """
    valid_ones = [f for f in rows if f.get("valid")]
    per_task: dict[str, dict[str, int]] = defaultdict(
        lambda: {"runs": 0, "correct_ones": 0, "content_in_context": 0}
    )
    for f in valid_ones:
        row = per_task[f["task"]]
        row["runs"] += 1
        row["correct_ones"] += bool(f.get("correct"))
        row["content_in_context"] += bool(f.get("content_in_context"))
    correct_ones = sum(t["correct_ones"] for t in per_task.values())
    runs = len(valid_ones)
    if runs == 9:
        decision = (
            "se queda"
            if correct_ones >= 6
            else "se retira"
            if correct_ones <= 3
            else "no concluyente"
        )
    else:
        decision = f"sin decisión: el criterio es para 9 corridas válidas, hay {runs}"
    return {
        "valid_runs": runs,
        "correct_ones": correct_ones,
        "content_in_context": sum(t["content_in_context"] for t in per_task.values()),
        "per_task": dict(sorted(per_task.items())),
        "decision": decision,
    }


def verdict(rows: list[dict]) -> dict:
    """Aplica las reglas de REQ-102 a las corridas válidas. Devuelve la variante elegida o None."""
    valid_ones = [f for f in rows if f.get("valid")]
    correct_ones: dict[tuple[str, str], int] = defaultdict(int)
    tasks = sorted({f["task"] for f in valid_ones})
    for f in valid_ones:
        correct_ones[(f["task"], f["offer"])] += bool(f.get("correct"))
    beats = {
        v: [t for t in tasks if correct_ones[(t, v)] > correct_ones[(t, "v0")]]
        for v in ("v1", "v2")
    }
    cost = {
        v: mean([f["cost_usd"] for f in valid_ones if f["offer"] == v] or [float("inf")])
        for v in VARIANTS
    }
    candidates = [v for v in ("v1", "v2") if len(beats[v]) >= MIN_TASKS]
    candidates.sort(key=lambda v: (-len(beats[v]), cost[v], SIMPLICITY[v]))
    return {
        "chosen": candidates[0] if candidates else None,
        "beats_v0_in": {v: beats[v] for v in ("v1", "v2")},
        "correct_ones": {f"{t}/{v}": correct_ones[(t, v)] for t in tasks for v in VARIANTS},
        "mean_cost_usd": cost,
        "valid_runs": len(valid_ones),
        "invalid_runs": len(rows) - len(valid_ones),
    }


# --- Ejecución ------------------------------------------------------------------------------------


def execute(args: argparse.Namespace) -> int:
    tasks = load_tasks()
    if args.pilot:
        tasks = [t for t in tasks if t["id"] in PILOT_TASKS]
    ids = [t["id"] for t in tasks]
    by_id = {t["id"]: t for t in tasks}
    runs = run_plan(ids, args.repetitions, args.seed, args.variants)
    output = args.bench / "results.jsonl"
    legacy_output = args.bench / "resultados.jsonl"
    if args.resume and not output.is_file() and legacy_output.is_file():
        output = legacy_output  # una tanda empezada antes del renombrado sigue en su fichero
    done = set()
    if args.resume and output.is_file():
        for line in output.read_text(encoding="utf-8").splitlines():
            row = legacy_names.normalize("adoption_runs", json.loads(line))
            done.add((row["task"], row["offer"], row["rep"]))
    pending = [c for c in runs if c not in done]
    if not bench.confirm(len(pending), args.cost_per_run, yes=args.yes):
        print("Cancelado.")
        return 1

    args.bench.mkdir(parents=True, exist_ok=True)
    switch = args.bench / "switch-that-does-not-exist"
    switch.unlink(missing_ok=True)
    sample = args.bench / "precedence.md"
    sample.write_text((ROOT / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    if not bench.precedence_control(args.bench, sample, switch):
        print("ABORTA: con LD_HOOK_ENABLED=0 por --settings el Read siguió bloqueado o no se leyó.")
        return 2

    rng = random.Random(args.seed)
    launched: list[bench.Run] = []
    for task_id, offer, rep in pending:
        task = by_id[task_id]
        row = None
        for attempt in range(REINTENTOS + 1):
            run_dir = args.bench / f"{task_id}-{offer}-{rep}-{attempt}"
            shutil.rmtree(run_dir, ignore_errors=True)
            run_dir.mkdir(parents=True)
            source = source_text(task, args.bench / "fuentes", args.sources)
            if args.pilot:
                text, value = source, ""
            else:
                text, _connector, value = plant(source, task["style"], rng)
            file = run_dir / task["name"]
            file.write_text(text, encoding="utf-8")
            telemetry = run_dir / "telemetry.jsonl"
            settings = bench.write_settings(
                run_dir / "settings.json", bench.batch_env(telemetry, switch)
            )
            prompt = pilot_question(file) if args.pilot else question(file, task["style"])
            run = bench.run(prompt, args.bench, settings)
            launched.append(run)
            if run.error or not run.session_id:
                continue
            seen = bench.analyze(bench.read_transcript(args.bench, run.session_id), file)
            valid = seen["deferred_tools"] and bench.valid_run(
                bench.telemetry_events(telemetry), run.session_id
            )
            if not valid:
                continue
            if args.pilot:
                coverage = title_coverage(run.result, section_titles(text))
                hit = coverage >= MIN_COVERAGE
                measurement = {"title_coverage": round(coverage, 2)}
            else:
                hit = value in run.result
                measurement = {"fact_in_answer": hit}
            row = {
                "task": task_id,
                "offer": offer,
                "rep": rep,
                "session_id": run.session_id,
                "valid": True,
                "correct": hit and not seen["content_in_context"],
                **measurement,
                "cost_usd": run.cost_usd,
                **{k: v for k, v in seen.items() if k != "local_with_path"},
                "local_tools": seen["local_with_path"],
                "attempts": attempt + 1,
            }
            break
        if row is None:
            bench.note_window(WINDOWS, "experimento-adopcion (abortado)", launched)
            print(f"ABORTA: {task_id}/{offer}/{rep} no dio una corrida válida en 3 intentos.")
            return 3
        with output.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{task_id:18} {offer} #{rep}: correcta={row['correct']} coste={row['cost_usd']:.2f}")

    bench.note_window(WINDOWS, "experimento-adopcion", launched)
    return report(output)


def report(results: Path) -> int:
    # Un `resultados.jsonl` de antes del renombrado (claves en español) da el mismo informe.
    rows = [
        legacy_names.normalize("adoption_runs", json.loads(x))
        for x in results.read_text(encoding="utf-8").splitlines()
        if x
    ]
    if len({f["offer"] for f in rows}) > 1:
        print(json.dumps(verdict(rows), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(summary_report(rows), ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--bench", type=Path, help="directorio de trabajo neutro (fuera del repo)")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260922)
    parser.add_argument("--cost-per-run", type=float, default=0.45)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--pilot",
        action="store_true",
        help="3 tareas de docs, resumen sin datos concretos, corrección por títulos de sección",
    )
    parser.add_argument(
        "--variants",
        type=lambda s: tuple(v.strip() for v in s.split(",") if v.strip()),
        default=VARIANTS,
        help="etiquetas a correr, separadas por comas (por defecto v0,v1,v2); hoy son iguales",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        help="carpeta de copias fijas (con MANIFEST.json al lado) en vez de los ficheros vivos",
    )
    parser.add_argument("--yes", action="store_true", help="no preguntar antes de gastar cuota")
    parser.add_argument(
        "--report-only", type=Path, help="recalcula el veredicto de un results.jsonl"
    )
    args = parser.parse_args(argv)
    if set(args.variants) - set(VARIANTS):
        parser.error(f"--variants solo admite {', '.join(VARIANTS)}")
    if args.report_only:
        return report(args.report_only)
    if not args.bench:
        parser.error("--bench es obligatorio para correr")
    if ROOT in args.bench.resolve().parents or args.bench.resolve() == ROOT:
        parser.error("--bench tiene que estar fuera del repo (sin memoria de proyecto)")
    return execute(args)


if __name__ == "__main__":
    sys.exit(main())
