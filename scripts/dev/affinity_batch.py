#!/usr/bin/env python3
"""Tanda de afinidad con modelos reales (SDD daemon-reparte-el-backend, T5).

Hace, en este orden y contra el llama-swap que indique el entorno:

1. Las huellas de cada modelo y tool de la tanda, a `footprints.json`, con `footprint.footprint` y la config
   real de llama-swap SOLO leída.
2. Por cada modelo, uno detrás de otro (el grupo `swap` solo tiene uno cargado a la vez): una
   llamada de calentamiento que se descarta, los casos mecánicos y, si es modelo de commit, los 30
   casos reales y las 9 trampas. Reutiliza `local_delegate.benchmark` (una corrida por caso, con la
   semilla registrada, la temperatura de producción de cada caso y `--save-responses`).
3. El techo: 3 corridas del 26B sobre el diff de 156 000 chars, llamando a
   `server.local_commit_msg(path=...)`. Es el camino de producción (map-reduce), que `benchmark.py`
   no ejercita porque manda el diff de una vez. Cada corrida va en un subproceso con el entorno que
   fija el rol de código en el 26B, sin respaldo ni enfriamiento y con su propia carpeta de log.
4. Todo a `benchmarks/afinidad-2026-10/resultados/*.jsonl`.

Es reanudable: si ya hay una fila de un caso con su corrida (`label`, `case`, `run`), no la repite.
Si falla a mitad, se vuelve a lanzar tal cual y sigue por lo que falta con la misma semilla.

La hora de salida de cada petición es `ts - latency_ms` de su fila (el `ts` de `benchmark.py` se
escribe al terminar y `latency_ms` mide la petición).

Lo lanza `D:\\Projects\\llms\\llama-swap\\lanzar-tanda-afinidad.ps1`, que pone la key en el entorno y
corre este script bajo el cerrojo de comandos pesados. Este script no lee ni imprime nunca el entorno.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "benchmarks" / "afinidad-2026-10"
CONFIG_LLAMASWAP = Path(r"D:\Projects\llms\llama-swap\config.yaml")

# Los cuatro modelos de la tanda (REQ-041), en el orden en que se corren.
MODELS = ("gemma3-4b", "qwen35-2b", "gemma4-26b-a4b", "qwen36-35b-a3b")
COMMIT_MODELS = ("gemma4-26b-a4b", "qwen36-35b-a3b")
CEILING = "techo"
CEILING_MODEL = "gemma4-26b-a4b"
CEILING_CASE = "techo-commit-156k"
CEILING_RUNS = 3
TOOL_COMMIT = "local_commit_msg"
CEILING_MARK = "TECHO_JSON:"

# Variables con las que corre el techo (nombres comprobados en `config.py`). `LOCAL_DELEGATE_LOG_DIR`
# lo pone la tanda aparte, porque apunta a su carpeta de trabajo.
CEILING_ENV = {
    "LOCAL_DELEGATE_MODEL_CODE": CEILING_MODEL,
    "LOCAL_DELEGATE_FALLBACK": "0",
    "LOCAL_DELEGATE_COOLDOWN": "0",
    "LOCAL_DELEGATE_ALLOWED_DIRS": "",
}

# Anulaciones de la sonda que solo dejan la fila sin medida de RAM o VRAM (la petición acabó antes de
# que muestreara): la respuesta vale y la corrida no se repite. La misma lista que usa
# `veredicto-afinidad` en `scripts/analizar_benchmark.py`.
RESOURCE_ONLY_REASONS = frozenset({"zero_vram_samples", "zero_ram_samples"})

Key = tuple[str, str, int]
BenchmarkRunner = Callable[[str, list[str], Path, argparse.Namespace, dict[str, Any]], int]
CeilingRunner = Callable[[int, Path, argparse.Namespace], dict[str, Any]]
FootprintCalculator = Callable[[list[dict[str, Any]], argparse.Namespace], dict[str, Any]]


def now_utc() -> datetime:
    return datetime.now(UTC)


def print_out(text: str) -> None:
    """Todo a stdout y con vaciado inmediato: el lanzador recoge una sola salida y se sondea en vivo."""
    print(text, flush=True)


# --- Corpus y plan ----------------------------------------------------------------------------------


def load_cases(path: Path) -> list[dict[str, Any]]:
    return list(json.loads(path.read_text(encoding="utf-8"))["cases"])


def is_mechanical(case: dict[str, Any]) -> bool:
    return case["role"] == "mechanical" and case["kind"] != "techo"


def is_commit(case: dict[str, Any]) -> bool:
    return case["tool"] == TOOL_COMMIT and case["kind"] == "calidad"


def model_cases(cases: Sequence[dict[str, Any]], model: str) -> list[dict[str, Any]]:
    """Los casos que corre el modelo, en el orden del corpus: las mecánicas y, si el modelo es de
    commit, los reales y las trampas. El techo no entra: va por el camino de producción."""
    of_commit = model in COMMIT_MODELS
    return [c for c in cases if is_mechanical(c) or (of_commit and is_commit(c))]


def ceiling_case(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    for case in cases:
        if case["id"] == CEILING_CASE and case["kind"] == "techo":
            return case
    raise SystemExit(f"error: el corpus no tiene el caso {CEILING_CASE}")


def _read_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue  # una línea cortada por un apagón: la corrida se repite
        if isinstance(row, dict) and {"label", "case", "run"} <= row.keys():
            rows.append(row)
    return rows


def done_runs(folder: Path, *, retry_errors: bool = False) -> set[Key]:
    """`(label, caso, corrida)` de las que ya tienen fila en `carpeta/*.jsonl`.

    El último intento de cada corrida manda. Una corrida cuyo último intento quedó anulado por la
    sonda no vale (el veredicto la rechaza) y se repite, salvo si el único motivo es que la sonda no
    llegó a muestrear (`RESOURCE_ONLY_REASONS`): la respuesta vale y repetirla daría lo mismo.
    Con `retry_errors`, también se repiten las que terminaron en `error` (un fallo de
    transporte, no una respuesta mala).
    """
    last_ones: dict[Key, dict[str, Any]] = {}
    if folder.is_dir():
        for file in sorted(folder.glob("*.jsonl")):
            for row in _read_rows(file):
                last_ones[(str(row["label"]), str(row["case"]), int(row["run"]))] = row
    done: set[Key] = set()
    for key, row in last_ones.items():
        if row.get("descartada") and row.get("descartada_motivo") not in RESOURCE_ONLY_REASONS:
            continue
        if retry_errors and row.get("outcome") == "error":
            continue
        done.add(key)
    return done


@dataclass
class Stage:
    """Un modelo (o el techo) con lo que le falta."""

    model: str
    kind: str  # "modelo" o "techo"
    total: int
    pending_items: list[dict[str, Any]] = field(default_factory=list)
    pending_runs: list[int] = field(default_factory=list)

    @property
    def n_pending(self) -> int:
        return len(self.pending_items) if self.kind == "modelo" else len(self.pending_runs)


def build_plan(
    cases: Sequence[dict[str, Any]], selection: Sequence[str], done: set[Key]
) -> list[Stage]:
    """Las etapas a correr, en orden: los modelos y, al final, el techo. `selection` vacía = todo."""
    wants = set(selection) or {*MODELS, CEILING}
    stages: list[Stage] = []
    for model in MODELS:
        if model not in wants:
            continue
        theirs = model_cases(cases, model)
        missing = [c for c in theirs if (model, c["id"], 1) not in done]
        stages.append(Stage(model, "modelo", len(theirs), pending_items=missing))
    if CEILING in wants:
        ceiling_case(cases)
        missing_runs = [
            n for n in range(1, CEILING_RUNS + 1) if (CEILING_MODEL, CEILING_CASE, n) not in done
        ]
        stages.append(
            Stage(
                CEILING_MODEL,
                "techo",
                CEILING_RUNS,
                pending_runs=missing_runs,
            )
        )
    return stages


def print_plan(stages: Sequence[Stage]) -> None:
    total = pending_items = warmups = 0
    for stage in stages:
        done = stage.total - stage.n_pending
        name = (
            f"techo ({stage.model}, camino de produccion)" if stage.kind == "techo" else stage.model
        )
        warms = 1 if stage.n_pending else 0
        print_out(
            f"{name}: {stage.total} peticiones ({stage.n_pending} pendientes, {done} hechas)"
            f" + {warms} de calentamiento"
        )
        total += stage.total
        pending_items += stage.n_pending
        warmups += warms
    print_out(
        f"total: {total} peticiones ({pending_items} pendientes) + {warmups} de calentamiento"
    )


# --- Huellas ----------------------------------------------------------------------------------------


def tool_prompt(cases: Sequence[dict[str, Any]], tool: str) -> str:
    """El prompt de sistema de la tool tal como lo capturó el corpus.

    Si la tool tiene varios (`classify`, `extract` y `delegate` los construyen con las etiquetas, las
    claves o el formato de cada caso), la huella cubre el conjunto: los distintos, ordenados y
    unidos por un salto de línea. Cambiar uno cualquiera cambia la huella.
    """
    distinct = sorted({c["system"] for c in cases if c["tool"] == tool})
    if not distinct:
        raise SystemExit(f"error: ningun caso del corpus usa la tool {tool}")
    return "\n".join(distinct)


def model_tools(cases: Sequence[dict[str, Any]], model: str) -> list[str]:
    return sorted({c["tool"] for c in model_cases(cases, model)})


def config_models(path: Path) -> dict[str, dict[str, Any]]:
    """Las entradas de `models` de la config real que usa la tanda. Solo lectura, y solo esas: el
    resto del fichero (las `apiKeys`) no sale de esta función."""
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    models = data["models"]
    missing = [m for m in MODELS if m not in models]
    if missing:
        raise SystemExit(f"error: la config no tiene los modelos {', '.join(missing)}")
    return {m: dict(models[m]) for m in MODELS}


def compute_footprints(cases: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    """`{modelo: {tool: huella}}` con la config de ahora y los prompts del corpus de producción."""
    from local_delegate import footprint

    config = config_models(args.config_llamaswap)
    footprints: dict[str, Any] = {}
    for model in MODELS:
        footprints[model] = {
            tool: footprint.footprint(config[model], tool_prompt(cases, tool))
            for tool in model_tools(cases, model)
        }
    return footprints


def write_footprints(path: Path, computed: dict[str, Any], *, redo: bool) -> tuple[bool, str]:
    """Escribe `footprints.json`. Si ya existe y es distinta, NO la pisa: una tanda reanudada con otra
    config mezclaría dos modelos bajo el mismo nombre. Devuelve (ok, mensaje)."""
    text = json.dumps(computed, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if path.exists() and not redo:
        if json.loads(path.read_text(encoding="utf-8")) == computed:
            return True, f"huellas: {path.name} ya existe y coincide"
        return (
            False,
            (
                f"las huellas de ahora no coinciden con {path.name}: la config o los prompts "
                "cambiaron desde que empezó la tanda. Si es a propósito, usa --redo-footprints"
            ),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True, f"huellas: escritas en {path.name}"


# --- Benchmark --------------------------------------------------------------------------------------


def _load_mode(cmd: str) -> str | None:
    match = re.search(r"--load-mode\s+(\S+)", cmd)
    return match.group(1) if match else None


def model_variant(entry: dict[str, Any]) -> dict[str, Any]:
    """Los flags de la config real que `benchmark.py` anota en cada fila (contexto, `-ncmoe`, modo
    de carga)."""
    from local_delegate import footprint

    cmd = entry.get("cmd") or ""
    flags = footprint.cmd_flags(cmd)
    return {
        "ctx_size": flags["ctx_size"],
        "n_cpu_moe": flags["n_cpu_moe"],
        "load_mode": _load_mode(str(cmd)),
    }


def benchmark_argv(
    model: str,
    ids: Sequence[str],
    output: Path,
    args: argparse.Namespace,
    variant: dict[str, Any],
) -> list[str]:
    """La línea de `local-delegate benchmark` para este modelo. La key NO va aquí: la lee el
    paquete de `LOCAL_DELEGATE_API_KEY` y por argv se vería en la lista de procesos."""
    argv = [
        "benchmark",
        "--model",
        model,
        "--label",
        model,
        "--cases",
        str(args.cases),
        "--runs",
        "1",
        "--seed",
        str(args.seed),
        "--timeout",
        str(args.timeout),
        "--save-responses",
        "--append",
        "--output",
        str(output),
    ]
    if args.endpoint:
        argv += ["--endpoint", args.endpoint]
    if args.probe_process:
        argv += ["--probe-process", args.probe_process]
    if variant.get("ctx_size") is not None:
        argv += ["--context-size", str(variant["ctx_size"])]
    if variant.get("n_cpu_moe") is not None:
        argv += ["--n-cpu-moe", str(variant["n_cpu_moe"])]
    if variant.get("load_mode"):
        argv += ["--load-mode", str(variant["load_mode"])]
    for case in ids:
        argv += ["--case", case]
    return argv


def run_bench(
    model: str,
    ids: list[str],
    output: Path,
    args: argparse.Namespace,
    variant: dict[str, Any],
) -> int:
    from local_delegate import benchmark

    parser = argparse.ArgumentParser(prog="benchmark")
    benchmark.add_parser(parser.add_subparsers())
    ns = parser.parse_args(benchmark_argv(model, ids, output, args, variant))
    return int(benchmark.run_benchmark(ns))


def _ensure_final_newline(path: Path) -> None:
    """Si un apagón dejó la última línea sin salto, la siguiente fila se pegaría a ella."""
    if path.exists() and path.stat().st_size:
        with path.open("rb+") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")


def check_warmup(path: Path, *, with_probe: bool) -> str | None:
    """`None` si la llamada de calentamiento salió bien (y, con sonda, si la sonda vio el proceso);
    si no, el motivo por el que la tanda no debe seguir."""
    rows = _read_rows(path) if path.exists() else []
    if not rows:
        return "el calentamiento no escribió ninguna fila"
    last_one = rows[-1]
    if last_one.get("outcome") != "ok":
        return f"el calentamiento terminó en {last_one.get('outcome')!r} ({last_one.get('error')})"
    if not with_probe:
        return None
    resources = last_one.get("resources") or {}
    if last_one.get("descartada"):
        return f"la sonda anuló el calentamiento ({last_one.get('descartada_motivo')})"
    if not resources.get("enabled") or not resources.get("pids"):
        return "la sonda (--probe-process) no vio ningun proceso llama-server: las filas saldrían sin RAM/VRAM"
    return None


# --- Techo ------------------------------------------------------------------------------------------


def one_ceiling_run(source: Path) -> int:
    """Modo hijo: UNA llamada a la tool de producción, con el entorno que ya fijó el padre.

    Corre en su propio proceso porque `config.py` lee el entorno al importarse: el padre ya lo
    importó con otros valores. Imprime una línea `TECHO_JSON:{...}` y nada más que ese contrato.
    """
    import time

    from local_delegate import server

    start_ts = time.perf_counter()
    try:
        text = server.local_commit_msg(path=str(source))
    except Exception as exc:  # una excepción también es un resultado de la corrida
        text = f"[local-delegate error] {type(exc).__name__}: {exc}"
    ms = round((time.perf_counter() - start_ts) * 1000)
    # ASCII puro: el contrato no depende de la codificación de la tubería.
    print_out(CEILING_MARK + json.dumps({"texto": text, "latency_ms": ms}))
    return 0


def run_ceiling(run: int, source: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Una corrida del techo por el camino de producción; devuelve la fila (formato de T4)."""
    log_dir = args.work_dir / "techo-usage"
    log_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("LOCAL_DELEGATE_LOG", None)  # un log explícito ganaría a LOG_DIR
    env.update(CEILING_ENV)
    env["LOCAL_DELEGATE_LOG_DIR"] = str(log_dir)
    if args.endpoint:
        env["LOCAL_DELEGATE_BASE_URL"] = args.endpoint
    process = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--one-ceiling-run",
            "--source",
            str(source),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=args.ceiling_timeout,
        check=False,
    )
    result: dict[str, Any] | None = None
    for line in process.stdout.splitlines():
        if line.startswith(CEILING_MARK):
            result = json.loads(line[len(CEILING_MARK) :])
        elif line.strip() and "HTTP Request:" not in line:
            print_out(f"  [techo {run}] {line}")
    if result is None:
        result = {
            "texto": f"[local-delegate error] el subproceso del techo terminó con {process.returncode} sin resultado",
            "latency_ms": None,
        }
    return ceiling_row(run, source, result, log_dir)


def _no_profile(path: Path) -> str:
    """La ruta con la carpeta del usuario como `~`: la fila se versiona y no puede llevar su nombre."""
    try:
        return "~/" + path.resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def ceiling_row(run: int, source: Path, result: dict[str, Any], log_dir: Path) -> dict[str, Any]:
    text = str(result["texto"])
    failure = text.startswith("[local-delegate error]") or not text.strip()
    data = source.read_bytes()
    return {
        "schema_version": 2,
        "ts": now_utc().isoformat(),
        "label": CEILING_MODEL,
        "model": CEILING_MODEL,
        "case": CEILING_CASE,
        "role": "code",
        "kind": "techo",
        "input_variant": None,
        "run": run,
        "attempt": 1,
        "retry_reason": None,
        # El payload de producción no manda semilla (REQ-041): no se inventa una.
        "seed": None,
        "via": "produccion",
        "entorno_fijado": {**CEILING_ENV, "LOCAL_DELEGATE_LOG_DIR": _no_profile(log_dir)},
        "thermal_state": None,
        "input_bytes": len(data),
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "latency_ms": result["latency_ms"],
        "outcome": "error" if failure else "ok",
        "ok": not failure,
        "error": text[:300] if failure else None,
        "descartada": False,
        "descartada_motivo": None,
        "score": None,
        "response": text,
        "response_chars": len(text),
        "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def ceiling_source(cases_: Sequence[dict[str, Any]], cases: Path) -> Path:
    case = ceiling_case(cases_)
    path = cases.parent / "fuentes" / case["source_file"]
    real = hashlib.sha256(path.read_bytes()).hexdigest()
    if real != case["source_sha256"]:
        raise SystemExit(f"error: {path.name} no coincide con su sha256 del corpus")
    return path


# --- Ventana ----------------------------------------------------------------------------------------


def register_window(path: Path, entry: dict[str, Any], *, close: bool) -> None:
    """`ventanas-tanda.json`: una entrada por lanzamiento (las reanudaciones suman la suya)."""
    windows: list[dict[str, Any]] = []
    if path.exists():
        windows = json.loads(path.read_text(encoding="utf-8"))
    if close and windows:
        windows[-1].update(entry)
    else:
        windows.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(windows, indent=2) + "\n", encoding="utf-8", newline="\n")


# --- Orquestación -----------------------------------------------------------------------------------


@dataclass
class Environment:
    """Lo que habla con el mundo real, para sustituirlo en las pruebas."""

    footprints: FootprintCalculator = compute_footprints
    benchmark: BenchmarkRunner = run_bench
    ceiling: CeilingRunner = run_ceiling
    variant: Callable[[str, argparse.Namespace], dict[str, Any]] | None = None


def _variant(model: str, args: argparse.Namespace, env: Environment) -> dict[str, Any]:
    if env.variant is not None:
        return env.variant(model, args)
    return model_variant(config_models(args.config_llamaswap)[model])


def _warm_up_with(
    model: str,
    case_id: str,
    args: argparse.Namespace,
    env: Environment,
    variant: dict[str, Any],
) -> str | None:
    stamp = now_utc().strftime("%Y%m%dT%H%M%SZ")
    output = args.work_dir / f"calentamiento-{model}-{stamp}.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    print_out(f"[{model}] calentamiento (descartado): {case_id}")
    env.benchmark(model, [case_id], output, args, variant)
    return check_warmup(output, with_probe=bool(args.probe_process))


def execute(args: argparse.Namespace, env: Environment) -> int:
    cases = load_cases(args.cases)
    done = done_runs(args.results, retry_errors=args.retry_errors)
    stages = build_plan(cases, args.only or [], done)
    if args.dry:
        print_plan(stages)
        return 0

    start_ts = now_utc()
    print_out(f"VENTANA inicio_utc={start_ts.isoformat()}")
    register_window(
        args.windows,
        {"inicio_utc": start_ts.isoformat(), "fin_utc": None, "solo": list(args.only or [])},
        close=False,
    )
    code = 0
    try:
        print_plan(stages)
        ok, message = write_footprints(
            args.footprints, env.footprints(cases, args), redo=args.redo_footprints
        )
        print_out(message)
        if not ok:
            return 4
        args.results.mkdir(parents=True, exist_ok=True)
        for stage in stages:
            if not stage.n_pending:
                print_out(f"[{stage.model}] nada pendiente en {stage.kind}")
                continue
            variant = _variant(stage.model, args, env)
            if stage.kind == "modelo":
                code = max(code, _model_stage(stage, args, env, variant))
            else:
                code = max(code, _ceiling_stage(stage, cases, args, env, variant))
            if code >= 3:
                return code
        return code
    finally:
        end = now_utc()
        print_out(f"VENTANA fin_utc={end.isoformat()}")
        register_window(args.windows, {"fin_utc": end.isoformat()}, close=True)


def _model_stage(
    stage: Stage, args: argparse.Namespace, env: Environment, variant: dict[str, Any]
) -> int:
    reason = _warm_up_with(stage.model, stage.pending_items[0]["id"], args, env, variant)
    if reason:
        print_out(f"[{stage.model}] ERROR: {reason}")
        return 3
    output = args.results / f"{stage.model}.jsonl"
    _ensure_final_newline(output)
    ids = [c["id"] for c in stage.pending_items]
    print_out(f"[{stage.model}] {len(ids)} peticiones pendientes de {stage.total}")
    rc = env.benchmark(stage.model, ids, output, args, variant)
    if rc >= 2:
        print_out(f"[{stage.model}] ERROR: el benchmark salió con {rc}")
        return 3
    if rc == 1:
        print_out(f"[{stage.model}] hubo peticiones con error; quedan en el JSONL")
    return rc


def _ceiling_stage(
    stage: Stage,
    cases: Sequence[dict[str, Any]],
    args: argparse.Namespace,
    env: Environment,
    variant: dict[str, Any],
) -> int:
    source = ceiling_source(cases, args.cases)
    # El 26B pudo descargarse tras el último modelo: se calienta con la primera mecánica.
    first_mechanical = next(c for c in cases if is_mechanical(c))
    reason = _warm_up_with(stage.model, first_mechanical["id"], args, env, variant)
    if reason:
        print_out(f"[techo] ERROR: {reason}")
        return 3
    output = args.results / f"techo-{stage.model}.jsonl"
    _ensure_final_newline(output)
    code = 0
    for run in stage.pending_runs:
        print_out(f"[techo] corrida {run} de {stage.total} por el camino de produccion")
        row = env.ceiling(run, source, args)
        with output.open("a", encoding="utf-8", newline="\n") as target:
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
        print_out(f"[{row['outcome']}] {CEILING_CASE} run={run} latency={row['latency_ms']}ms")
        if row["outcome"] != "ok":
            code = 1
    return code


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cases", type=Path, default=FOLDER / "cases.json")
    parser.add_argument("--results", type=Path, default=FOLDER / "resultados")
    parser.add_argument("--footprints", type=Path, default=FOLDER / "huellas.json")
    parser.add_argument("--windows", type=Path, default=FOLDER / "ventanas-tanda.json")
    parser.add_argument("--config-llamaswap", type=Path, default=CONFIG_LLAMASWAP)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path(tempfile.gettempdir()) / "tanda-afinidad",
        help="calentamientos (se descartan) y log de uso del techo",
    )
    parser.add_argument(
        "--only",
        action="append",
        choices=[*MODELS, CEILING],
        help="solo este modelo, o `techo` (repetible)",
    )
    parser.add_argument("--dry", action="store_true", help="imprime el plan y no llama a nada")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--endpoint", default=None, help="BASE_URL /v1; por defecto la del entorno")
    parser.add_argument("--timeout", type=float, default=300.0, help="por petición, en segundos")
    parser.add_argument(
        "--ceiling-timeout", type=float, default=3600.0, help="por corrida del techo"
    )
    parser.add_argument("--probe-process", default="llama-server.exe")
    parser.add_argument(
        "--no-probe", action="store_true", help="no mide RAM/VRAM (solo para ensayos sin GPU)"
    )
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--redo-footprints", action="store_true")
    parser.add_argument("--one-ceiling-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.no_probe:
        args.probe_process = None
    return args


def _utf8_output() -> None:
    """Con la salida redirigida, Windows usa la página de códigos local y un `≈` de la respuesta de
    un modelo tumbaría la tanda a mitad. Nada que se imprima aquí puede ser motivo para parar."""
    for flow in (sys.stdout, sys.stderr):
        reconfigure = getattr(flow, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


def main(argv: Sequence[str] | None = None, env: Environment | None = None) -> int:
    args = parse_args(argv)
    _utf8_output()
    if args.one_ceiling_run:
        return one_ceiling_run(args.source)
    return execute(args, env or Environment())


if __name__ == "__main__":
    sys.exit(main())
