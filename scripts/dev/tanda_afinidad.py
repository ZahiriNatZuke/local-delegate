#!/usr/bin/env python3
"""Tanda de afinidad con modelos reales (SDD daemon-reparte-el-backend, T5).

Hace, en este orden y contra el llama-swap que indique el entorno:

1. Las huellas de cada modelo y tool de la tanda, a `huellas.json`, con `huella.huella` y la config
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

RAIZ = Path(__file__).resolve().parents[2]
CARPETA = RAIZ / "benchmarks" / "afinidad-2026-10"
CONFIG_LLAMASWAP = Path(r"D:\Projects\llms\llama-swap\config.yaml")

# Los cuatro modelos de la tanda (REQ-041), en el orden en que se corren.
MODELOS = ("gemma3-4b", "qwen35-2b", "gemma4-26b-a4b", "qwen36-35b-a3b")
MODELOS_DE_COMMIT = ("gemma4-26b-a4b", "qwen36-35b-a3b")
TECHO = "techo"
MODELO_DEL_TECHO = "gemma4-26b-a4b"
CASO_DEL_TECHO = "techo-commit-156k"
CORRIDAS_DEL_TECHO = 3
TOOL_COMMIT = "local_commit_msg"
MARCA_TECHO = "TECHO_JSON:"

# Variables con las que corre el techo (nombres comprobados en `config.py`). `LOCAL_DELEGATE_LOG_DIR`
# lo pone la tanda aparte, porque apunta a su carpeta de trabajo.
ENTORNO_DEL_TECHO = {
    "LOCAL_DELEGATE_MODEL_CODE": MODELO_DEL_TECHO,
    "LOCAL_DELEGATE_FALLBACK": "0",
    "LOCAL_DELEGATE_COOLDOWN": "0",
    "LOCAL_DELEGATE_ALLOWED_DIRS": "",
}

# Anulaciones de la sonda que solo dejan la fila sin medida de RAM o VRAM (la petición acabó antes de
# que muestreara): la respuesta vale y la corrida no se repite. La misma lista que usa
# `veredicto-afinidad` en `scripts/analizar_benchmark.py`.
MOTIVOS_SOLO_DE_RECURSOS = frozenset({"zero_vram_samples", "zero_ram_samples"})

Clave = tuple[str, str, int]
CorredorBenchmark = Callable[[str, list[str], Path, argparse.Namespace, dict[str, Any]], int]
CorredorTecho = Callable[[int, Path, argparse.Namespace], dict[str, Any]]
CalculadorHuellas = Callable[[list[dict[str, Any]], argparse.Namespace], dict[str, Any]]


def ahora_utc() -> datetime:
    return datetime.now(UTC)


def imprimir(texto: str) -> None:
    """Todo a stdout y con vaciado inmediato: el lanzador recoge una sola salida y se sondea en vivo."""
    print(texto, flush=True)


# --- Corpus y plan ----------------------------------------------------------------------------------


def cargar_casos(ruta: Path) -> list[dict[str, Any]]:
    return list(json.loads(ruta.read_text(encoding="utf-8"))["cases"])


def es_mecanico(caso: dict[str, Any]) -> bool:
    return caso["role"] == "mechanical" and caso["kind"] != "techo"


def es_de_commit(caso: dict[str, Any]) -> bool:
    return caso["tool"] == TOOL_COMMIT and caso["kind"] == "calidad"


def casos_del_modelo(casos: Sequence[dict[str, Any]], modelo: str) -> list[dict[str, Any]]:
    """Los casos que corre el modelo, en el orden del corpus: las mecánicas y, si el modelo es de
    commit, los reales y las trampas. El techo no entra: va por el camino de producción."""
    de_commit = modelo in MODELOS_DE_COMMIT
    return [c for c in casos if es_mecanico(c) or (de_commit and es_de_commit(c))]


def caso_del_techo(casos: Sequence[dict[str, Any]]) -> dict[str, Any]:
    for caso in casos:
        if caso["id"] == CASO_DEL_TECHO and caso["kind"] == "techo":
            return caso
    raise SystemExit(f"error: el corpus no tiene el caso {CASO_DEL_TECHO}")


def _leer_filas(ruta: Path) -> list[dict[str, Any]]:
    filas: list[dict[str, Any]] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        try:
            fila = json.loads(linea)
        except ValueError:
            continue  # una línea cortada por un apagón: la corrida se repite
        if isinstance(fila, dict) and {"label", "case", "run"} <= fila.keys():
            filas.append(fila)
    return filas


def corridas_hechas(carpeta: Path, *, reintentar_errores: bool = False) -> set[Clave]:
    """`(label, caso, corrida)` de las que ya tienen fila en `carpeta/*.jsonl`.

    El último intento de cada corrida manda. Una corrida cuyo último intento quedó anulado por la
    sonda no vale (el veredicto la rechaza) y se repite, salvo si el único motivo es que la sonda no
    llegó a muestrear (`MOTIVOS_SOLO_DE_RECURSOS`): la respuesta vale y repetirla daría lo mismo.
    Con `reintentar_errores`, también se repiten las que terminaron en `error` (un fallo de
    transporte, no una respuesta mala).
    """
    ultimas: dict[Clave, dict[str, Any]] = {}
    if carpeta.is_dir():
        for fichero in sorted(carpeta.glob("*.jsonl")):
            for fila in _leer_filas(fichero):
                ultimas[(str(fila["label"]), str(fila["case"]), int(fila["run"]))] = fila
    hechas: set[Clave] = set()
    for clave, fila in ultimas.items():
        if fila.get("descartada") and fila.get("descartada_motivo") not in MOTIVOS_SOLO_DE_RECURSOS:
            continue
        if reintentar_errores and fila.get("outcome") == "error":
            continue
        hechas.add(clave)
    return hechas


@dataclass
class Etapa:
    """Un modelo (o el techo) con lo que le falta."""

    modelo: str
    tipo: str  # "modelo" o "techo"
    total: int
    pendientes: list[dict[str, Any]] = field(default_factory=list)
    corridas_pendientes: list[int] = field(default_factory=list)

    @property
    def n_pendientes(self) -> int:
        return len(self.pendientes) if self.tipo == "modelo" else len(self.corridas_pendientes)


def construir_plan(
    casos: Sequence[dict[str, Any]], seleccion: Sequence[str], hechas: set[Clave]
) -> list[Etapa]:
    """Las etapas a correr, en orden: los modelos y, al final, el techo. `seleccion` vacía = todo."""
    quiere = set(seleccion) or {*MODELOS, TECHO}
    etapas: list[Etapa] = []
    for modelo in MODELOS:
        if modelo not in quiere:
            continue
        suyos = casos_del_modelo(casos, modelo)
        faltan = [c for c in suyos if (modelo, c["id"], 1) not in hechas]
        etapas.append(Etapa(modelo, "modelo", len(suyos), pendientes=faltan))
    if TECHO in quiere:
        caso_del_techo(casos)
        faltan_corridas = [
            n
            for n in range(1, CORRIDAS_DEL_TECHO + 1)
            if (MODELO_DEL_TECHO, CASO_DEL_TECHO, n) not in hechas
        ]
        etapas.append(
            Etapa(
                MODELO_DEL_TECHO,
                "techo",
                CORRIDAS_DEL_TECHO,
                corridas_pendientes=faltan_corridas,
            )
        )
    return etapas


def imprimir_plan(etapas: Sequence[Etapa]) -> None:
    total = pendientes = calentamientos = 0
    for etapa in etapas:
        hechas = etapa.total - etapa.n_pendientes
        nombre = (
            f"techo ({etapa.modelo}, camino de produccion)"
            if etapa.tipo == "techo"
            else etapa.modelo
        )
        calienta = 1 if etapa.n_pendientes else 0
        imprimir(
            f"{nombre}: {etapa.total} peticiones ({etapa.n_pendientes} pendientes, {hechas} hechas)"
            f" + {calienta} de calentamiento"
        )
        total += etapa.total
        pendientes += etapa.n_pendientes
        calentamientos += calienta
    imprimir(
        f"total: {total} peticiones ({pendientes} pendientes) + {calentamientos} de calentamiento"
    )


# --- Huellas ----------------------------------------------------------------------------------------


def prompt_de_la_tool(casos: Sequence[dict[str, Any]], tool: str) -> str:
    """El prompt de sistema de la tool tal como lo capturó el corpus.

    Si la tool tiene varios (`classify`, `extract` y `delegate` los construyen con las etiquetas, las
    claves o el formato de cada caso), la huella cubre el conjunto: los distintos, ordenados y
    unidos por un salto de línea. Cambiar uno cualquiera cambia la huella.
    """
    distintos = sorted({c["system"] for c in casos if c["tool"] == tool})
    if not distintos:
        raise SystemExit(f"error: ningun caso del corpus usa la tool {tool}")
    return "\n".join(distintos)


def tools_del_modelo(casos: Sequence[dict[str, Any]], modelo: str) -> list[str]:
    return sorted({c["tool"] for c in casos_del_modelo(casos, modelo)})


def modelos_de_la_config(ruta: Path) -> dict[str, dict[str, Any]]:
    """Las entradas de `models` de la config real que usa la tanda. Solo lectura, y solo esas: el
    resto del fichero (las `apiKeys`) no sale de esta función."""
    import yaml

    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    modelos = datos["models"]
    faltan = [m for m in MODELOS if m not in modelos]
    if faltan:
        raise SystemExit(f"error: la config no tiene los modelos {', '.join(faltan)}")
    return {m: dict(modelos[m]) for m in MODELOS}


def calcular_huellas(casos: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    """`{modelo: {tool: huella}}` con la config de ahora y los prompts del corpus de producción."""
    from local_delegate import huella

    config = modelos_de_la_config(args.config_llamaswap)
    huellas: dict[str, Any] = {}
    for modelo in MODELOS:
        huellas[modelo] = {
            tool: huella.huella(config[modelo], prompt_de_la_tool(casos, tool))
            for tool in tools_del_modelo(casos, modelo)
        }
    return huellas


def escribir_huellas(ruta: Path, calculadas: dict[str, Any], *, rehacer: bool) -> tuple[bool, str]:
    """Escribe `huellas.json`. Si ya existe y es distinta, NO la pisa: una tanda reanudada con otra
    config mezclaría dos modelos bajo el mismo nombre. Devuelve (ok, mensaje)."""
    texto = json.dumps(calculadas, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if ruta.exists() and not rehacer:
        if json.loads(ruta.read_text(encoding="utf-8")) == calculadas:
            return True, f"huellas: {ruta.name} ya existe y coincide"
        return (
            False,
            (
                f"las huellas de ahora no coinciden con {ruta.name}: la config o los prompts "
                "cambiaron desde que empezó la tanda. Si es a propósito, usa --rehacer-huellas"
            ),
        )
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(texto, encoding="utf-8", newline="\n")
    return True, f"huellas: escritas en {ruta.name}"


# --- Benchmark --------------------------------------------------------------------------------------


def _load_mode(cmd: str) -> str | None:
    coincidencia = re.search(r"--load-mode\s+(\S+)", cmd)
    return coincidencia.group(1) if coincidencia else None


def variante_del_modelo(entrada: dict[str, Any]) -> dict[str, Any]:
    """Los flags de la config real que `benchmark.py` anota en cada fila (contexto, `-ncmoe`, modo
    de carga)."""
    from local_delegate import huella

    cmd = entrada.get("cmd") or ""
    flags = huella.flags_del_cmd(cmd)
    return {
        "ctx_size": flags["ctx_size"],
        "n_cpu_moe": flags["n_cpu_moe"],
        "load_mode": _load_mode(str(cmd)),
    }


def argv_del_benchmark(
    modelo: str,
    ids: Sequence[str],
    salida: Path,
    args: argparse.Namespace,
    variante: dict[str, Any],
) -> list[str]:
    """La línea de `local-delegate benchmark` para este modelo. La key NO va aquí: la lee el
    paquete de `LOCAL_DELEGATE_API_KEY` y por argv se vería en la lista de procesos."""
    argv = [
        "benchmark",
        "--model",
        modelo,
        "--label",
        modelo,
        "--cases",
        str(args.cases),
        "--runs",
        "1",
        "--seed",
        str(args.semilla),
        "--timeout",
        str(args.timeout),
        "--save-responses",
        "--append",
        "--output",
        str(salida),
    ]
    if args.endpoint:
        argv += ["--endpoint", args.endpoint]
    if args.probe_process:
        argv += ["--probe-process", args.probe_process]
    if variante.get("ctx_size") is not None:
        argv += ["--context-size", str(variante["ctx_size"])]
    if variante.get("n_cpu_moe") is not None:
        argv += ["--n-cpu-moe", str(variante["n_cpu_moe"])]
    if variante.get("load_mode"):
        argv += ["--load-mode", str(variante["load_mode"])]
    for caso in ids:
        argv += ["--case", caso]
    return argv


def correr_benchmark(
    modelo: str,
    ids: list[str],
    salida: Path,
    args: argparse.Namespace,
    variante: dict[str, Any],
) -> int:
    from local_delegate import benchmark

    parser = argparse.ArgumentParser(prog="benchmark")
    benchmark.add_parser(parser.add_subparsers())
    ns = parser.parse_args(argv_del_benchmark(modelo, ids, salida, args, variante))
    return int(benchmark.run_benchmark(ns))


def _asegurar_salto_final(ruta: Path) -> None:
    """Si un apagón dejó la última línea sin salto, la siguiente fila se pegaría a ella."""
    if ruta.exists() and ruta.stat().st_size:
        with ruta.open("rb+") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")


def comprobar_calentamiento(ruta: Path, *, con_sonda: bool) -> str | None:
    """`None` si la llamada de calentamiento salió bien (y, con sonda, si la sonda vio el proceso);
    si no, el motivo por el que la tanda no debe seguir."""
    filas = _leer_filas(ruta) if ruta.exists() else []
    if not filas:
        return "el calentamiento no escribió ninguna fila"
    ultima = filas[-1]
    if ultima.get("outcome") != "ok":
        return f"el calentamiento terminó en {ultima.get('outcome')!r} ({ultima.get('error')})"
    if not con_sonda:
        return None
    recursos = ultima.get("resources") or {}
    if ultima.get("descartada"):
        return f"la sonda anuló el calentamiento ({ultima.get('descartada_motivo')})"
    if not recursos.get("enabled") or not recursos.get("pids"):
        return "la sonda (--probe-process) no vio ningun proceso llama-server: las filas saldrían sin RAM/VRAM"
    return None


# --- Techo ------------------------------------------------------------------------------------------


def una_corrida_de_techo(fuente: Path) -> int:
    """Modo hijo: UNA llamada a la tool de producción, con el entorno que ya fijó el padre.

    Corre en su propio proceso porque `config.py` lee el entorno al importarse: el padre ya lo
    importó con otros valores. Imprime una línea `TECHO_JSON:{...}` y nada más que ese contrato.
    """
    import time

    from local_delegate import server

    inicio = time.perf_counter()
    try:
        texto = server.local_commit_msg(path=str(fuente))
    except Exception as exc:  # una excepción también es un resultado de la corrida
        texto = f"[local-delegate error] {type(exc).__name__}: {exc}"
    ms = round((time.perf_counter() - inicio) * 1000)
    # ASCII puro: el contrato no depende de la codificación de la tubería.
    imprimir(MARCA_TECHO + json.dumps({"texto": texto, "latency_ms": ms}))
    return 0


def correr_techo(run: int, fuente: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Una corrida del techo por el camino de producción; devuelve la fila (formato de T4)."""
    carpeta_log = args.trabajo / "techo-usage"
    carpeta_log.mkdir(parents=True, exist_ok=True)
    entorno = dict(os.environ)
    entorno.pop("LOCAL_DELEGATE_LOG", None)  # un log explícito ganaría a LOG_DIR
    entorno.update(ENTORNO_DEL_TECHO)
    entorno["LOCAL_DELEGATE_LOG_DIR"] = str(carpeta_log)
    if args.endpoint:
        entorno["LOCAL_DELEGATE_BASE_URL"] = args.endpoint
    proceso = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--una-corrida-de-techo",
            "--fuente",
            str(fuente),
        ],
        env=entorno,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=args.timeout_techo,
        check=False,
    )
    resultado: dict[str, Any] | None = None
    for linea in proceso.stdout.splitlines():
        if linea.startswith(MARCA_TECHO):
            resultado = json.loads(linea[len(MARCA_TECHO) :])
        elif linea.strip() and "HTTP Request:" not in linea:
            imprimir(f"  [techo {run}] {linea}")
    if resultado is None:
        resultado = {
            "texto": f"[local-delegate error] el subproceso del techo terminó con {proceso.returncode} sin resultado",
            "latency_ms": None,
        }
    return fila_del_techo(run, fuente, resultado, carpeta_log)


def _sin_perfil(ruta: Path) -> str:
    """La ruta con la carpeta del usuario como `~`: la fila se versiona y no puede llevar su nombre."""
    try:
        return "~/" + ruta.resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return ruta.as_posix()


def fila_del_techo(
    run: int, fuente: Path, resultado: dict[str, Any], carpeta_log: Path
) -> dict[str, Any]:
    texto = str(resultado["texto"])
    fallo = texto.startswith("[local-delegate error]") or not texto.strip()
    datos = fuente.read_bytes()
    return {
        "schema_version": 2,
        "ts": ahora_utc().isoformat(),
        "label": MODELO_DEL_TECHO,
        "model": MODELO_DEL_TECHO,
        "case": CASO_DEL_TECHO,
        "role": "code",
        "kind": "techo",
        "input_variant": None,
        "run": run,
        "attempt": 1,
        "retry_reason": None,
        # El payload de producción no manda semilla (REQ-041): no se inventa una.
        "seed": None,
        "via": "produccion",
        "entorno_fijado": {**ENTORNO_DEL_TECHO, "LOCAL_DELEGATE_LOG_DIR": _sin_perfil(carpeta_log)},
        "thermal_state": None,
        "input_bytes": len(datos),
        "input_sha256": hashlib.sha256(datos).hexdigest(),
        "latency_ms": resultado["latency_ms"],
        "outcome": "error" if fallo else "ok",
        "ok": not fallo,
        "error": texto[:300] if fallo else None,
        "descartada": False,
        "descartada_motivo": None,
        "score": None,
        "response": texto,
        "response_chars": len(texto),
        "response_sha256": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
    }


def fuente_del_techo(casos: Sequence[dict[str, Any]], cases: Path) -> Path:
    caso = caso_del_techo(casos)
    ruta = cases.parent / "fuentes" / caso["source_file"]
    real = hashlib.sha256(ruta.read_bytes()).hexdigest()
    if real != caso["source_sha256"]:
        raise SystemExit(f"error: {ruta.name} no coincide con su sha256 del corpus")
    return ruta


# --- Ventana ----------------------------------------------------------------------------------------


def registrar_ventana(ruta: Path, entrada: dict[str, Any], *, cerrar: bool) -> None:
    """`ventanas-tanda.json`: una entrada por lanzamiento (las reanudaciones suman la suya)."""
    ventanas: list[dict[str, Any]] = []
    if ruta.exists():
        ventanas = json.loads(ruta.read_text(encoding="utf-8"))
    if cerrar and ventanas:
        ventanas[-1].update(entrada)
    else:
        ventanas.append(entrada)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(ventanas, indent=2) + "\n", encoding="utf-8", newline="\n")


# --- Orquestación -----------------------------------------------------------------------------------


@dataclass
class Entorno:
    """Lo que habla con el mundo real, para sustituirlo en las pruebas."""

    huellas: CalculadorHuellas = calcular_huellas
    benchmark: CorredorBenchmark = correr_benchmark
    techo: CorredorTecho = correr_techo
    variante: Callable[[str, argparse.Namespace], dict[str, Any]] | None = None


def _variante(modelo: str, args: argparse.Namespace, entorno: Entorno) -> dict[str, Any]:
    if entorno.variante is not None:
        return entorno.variante(modelo, args)
    return variante_del_modelo(modelos_de_la_config(args.config_llamaswap)[modelo])


def _calentar_con(
    modelo: str,
    caso_id: str,
    args: argparse.Namespace,
    entorno: Entorno,
    variante: dict[str, Any],
) -> str | None:
    sello = ahora_utc().strftime("%Y%m%dT%H%M%SZ")
    salida = args.trabajo / f"calentamiento-{modelo}-{sello}.jsonl"
    salida.parent.mkdir(parents=True, exist_ok=True)
    imprimir(f"[{modelo}] calentamiento (descartado): {caso_id}")
    entorno.benchmark(modelo, [caso_id], salida, args, variante)
    return comprobar_calentamiento(salida, con_sonda=bool(args.probe_process))


def ejecutar(args: argparse.Namespace, entorno: Entorno) -> int:
    casos = cargar_casos(args.cases)
    hechas = corridas_hechas(args.resultados, reintentar_errores=args.reintentar_errores)
    etapas = construir_plan(casos, args.solo or [], hechas)
    if args.seco:
        imprimir_plan(etapas)
        return 0

    inicio = ahora_utc()
    imprimir(f"VENTANA inicio_utc={inicio.isoformat()}")
    registrar_ventana(
        args.ventanas,
        {"inicio_utc": inicio.isoformat(), "fin_utc": None, "solo": list(args.solo or [])},
        cerrar=False,
    )
    codigo = 0
    try:
        imprimir_plan(etapas)
        ok, mensaje = escribir_huellas(
            args.huellas, entorno.huellas(casos, args), rehacer=args.rehacer_huellas
        )
        imprimir(mensaje)
        if not ok:
            return 4
        args.resultados.mkdir(parents=True, exist_ok=True)
        for etapa in etapas:
            if not etapa.n_pendientes:
                imprimir(f"[{etapa.modelo}] nada pendiente en {etapa.tipo}")
                continue
            variante = _variante(etapa.modelo, args, entorno)
            if etapa.tipo == "modelo":
                codigo = max(codigo, _etapa_de_modelo(etapa, args, entorno, variante))
            else:
                codigo = max(codigo, _etapa_del_techo(etapa, casos, args, entorno, variante))
            if codigo >= 3:
                return codigo
        return codigo
    finally:
        fin = ahora_utc()
        imprimir(f"VENTANA fin_utc={fin.isoformat()}")
        registrar_ventana(args.ventanas, {"fin_utc": fin.isoformat()}, cerrar=True)


def _etapa_de_modelo(
    etapa: Etapa, args: argparse.Namespace, entorno: Entorno, variante: dict[str, Any]
) -> int:
    motivo = _calentar_con(etapa.modelo, etapa.pendientes[0]["id"], args, entorno, variante)
    if motivo:
        imprimir(f"[{etapa.modelo}] ERROR: {motivo}")
        return 3
    salida = args.resultados / f"{etapa.modelo}.jsonl"
    _asegurar_salto_final(salida)
    ids = [c["id"] for c in etapa.pendientes]
    imprimir(f"[{etapa.modelo}] {len(ids)} peticiones pendientes de {etapa.total}")
    rc = entorno.benchmark(etapa.modelo, ids, salida, args, variante)
    if rc >= 2:
        imprimir(f"[{etapa.modelo}] ERROR: el benchmark salió con {rc}")
        return 3
    if rc == 1:
        imprimir(f"[{etapa.modelo}] hubo peticiones con error; quedan en el JSONL")
    return rc


def _etapa_del_techo(
    etapa: Etapa,
    casos: Sequence[dict[str, Any]],
    args: argparse.Namespace,
    entorno: Entorno,
    variante: dict[str, Any],
) -> int:
    fuente = fuente_del_techo(casos, args.cases)
    # El 26B pudo descargarse tras el último modelo: se calienta con la primera mecánica.
    primera_mecanica = next(c for c in casos if es_mecanico(c))
    motivo = _calentar_con(etapa.modelo, primera_mecanica["id"], args, entorno, variante)
    if motivo:
        imprimir(f"[techo] ERROR: {motivo}")
        return 3
    salida = args.resultados / f"techo-{etapa.modelo}.jsonl"
    _asegurar_salto_final(salida)
    codigo = 0
    for run in etapa.corridas_pendientes:
        imprimir(f"[techo] corrida {run} de {etapa.total} por el camino de produccion")
        fila = entorno.techo(run, fuente, args)
        with salida.open("a", encoding="utf-8", newline="\n") as destino:
            destino.write(json.dumps(fila, ensure_ascii=False) + "\n")
        imprimir(f"[{fila['outcome']}] {CASO_DEL_TECHO} run={run} latency={fila['latency_ms']}ms")
        if fila["outcome"] != "ok":
            codigo = 1
    return codigo


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cases", type=Path, default=CARPETA / "cases.json")
    parser.add_argument("--resultados", type=Path, default=CARPETA / "resultados")
    parser.add_argument("--huellas", type=Path, default=CARPETA / "huellas.json")
    parser.add_argument("--ventanas", type=Path, default=CARPETA / "ventanas-tanda.json")
    parser.add_argument("--config-llamaswap", type=Path, default=CONFIG_LLAMASWAP)
    parser.add_argument(
        "--trabajo",
        type=Path,
        default=Path(tempfile.gettempdir()) / "tanda-afinidad",
        help="calentamientos (se descartan) y log de uso del techo",
    )
    parser.add_argument(
        "--solo",
        action="append",
        choices=[*MODELOS, TECHO],
        help="solo este modelo, o `techo` (repetible)",
    )
    parser.add_argument("--seco", action="store_true", help="imprime el plan y no llama a nada")
    parser.add_argument("--semilla", type=int, default=42)
    parser.add_argument("--endpoint", default=None, help="BASE_URL /v1; por defecto la del entorno")
    parser.add_argument("--timeout", type=float, default=300.0, help="por petición, en segundos")
    parser.add_argument("--timeout-techo", type=float, default=3600.0, help="por corrida del techo")
    parser.add_argument("--probe-process", default="llama-server.exe")
    parser.add_argument(
        "--sin-sonda", action="store_true", help="no mide RAM/VRAM (solo para ensayos sin GPU)"
    )
    parser.add_argument("--reintentar-errores", action="store_true")
    parser.add_argument("--rehacer-huellas", action="store_true")
    parser.add_argument("--una-corrida-de-techo", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--fuente", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.sin_sonda:
        args.probe_process = None
    return args


def _salida_en_utf8() -> None:
    """Con la salida redirigida, Windows usa la página de códigos local y un `≈` de la respuesta de
    un modelo tumbaría la tanda a mitad. Nada que se imprima aquí puede ser motivo para parar."""
    for flujo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(flujo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="backslashreplace")


def main(argv: Sequence[str] | None = None, entorno: Entorno | None = None) -> int:
    args = parse_args(argv)
    _salida_en_utf8()
    if args.una_corrida_de_techo:
        return una_corrida_de_techo(args.fuente)
    return ejecutar(args, entorno or Entorno())


if __name__ == "__main__":
    sys.exit(main())
