#!/usr/bin/env python3
"""Control de lentitud con datos reales (SDD `daemon-reparte-el-backend`, REQ-025).

Aplica la regla exacta de la spec sobre una **copia** de `metrics.db` y el log de uso, y contesta
las tres preguntas que bloquean la implementacion de D:

(a) Sobre los eventos **de la PC**, que porcentaje marca la regla. Si pasa del 5 %, el umbral se
    revisa con el usuario antes de implementar.
(b) Control positivo de la regla: sobre las filas de Qwen3.6 de **todos** los origenes, la misma
    regla marca las filas 570, 571 y 573 (las llamadas de la Mac del 2026-09-30). Si no las marca,
    la regla esta mal; se corrige la regla, no el umbral.
(c) Mediana de generacion por tramos de entrada (`< 2k`, `2k-10k`, `> 10k` tokens): si el tramo de
    mas de 10k queda por debajo de 0,75 x el de menos de 2k, la referencia va por tramos.

La regla (REQ-025), por modelo y en orden temporal: la referencia de un evento es la mediana de
`tok_s` de los **50 ultimos eventos correctos con `tokens_out >= 8` anteriores a el**, con un minimo
de 10; el evento lleva `ritmo_rel = tok_s / referencia` y es `lento` si `ritmo_rel < umbral`.

Reglas de lectura de los datos:

- `metrics.db` no se abre en su sitio: lo usa llama-swap. `copiar_metrics` copia `metrics.db`,
  `-wal` y `-shm` a una carpeta propia y se abre la copia en solo lectura.
- Una fila de `metrics.db` es **de la PC** si su intervalo `[ts - duration, ts]` cae dentro del
  intervalo de una llamada `backend: local` de `usage-*.jsonl` (mismo modelo, 2 s de holgura). Es lo
  que ya hacia el insumo `llamaswap-grupos.md`: `metrics.db` guarda `src = ip:127.0.0.1` para todos,
  porque la Mac entra por `tailscale serve`, asi que su campo `src` no distingue el origen. El log
  de uso si: lo escribe el daemon de la PC. Las filas sin llamada de log son «no-PC» (Mac u otro
  cliente directo).
- Un evento agrupa las filas de las llamadas al backend de una misma operacion del log (troceado,
  reintentos). Su `tok_s` es Σ tokens de salida / Σ ms de generacion, como en REQ-024; los ms de
  generacion de una fila son `output_tokens / tokens_per_second`. Una fila no-PC es un evento por si
  sola.
- Entrada de un evento: el mayor `input_tokens + cache_tokens` de sus filas (la lentitud de la
  generacion depende del contexto de cada llamada, no de la suma).

Uso:
    uv run python scripts/medir_lentitud.py --copia <carpeta_de_la_copia> \\
        --origen <carpeta_con_metrics.db> --desde 2026-09-15T19:26:41
    uv run python scripts/medir_lentitud.py --copia <carpeta> --json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Eventos que forman la velocidad normal (REQ-025).
VENTANA = 50
MINIMO = 10
SALIDA_MINIMA = 8
UMBRAL = 0.5
#: Decision de REQ-025: si el tramo largo baja de esto respecto al corto, la referencia va por tramos.
RATIO_TRAMOS = 0.75
#: Tope de eventos marcados sobre los de la PC antes de parar y revisar el umbral con el usuario.
TOPE_MARCADOS = 0.05
#: Filas que el control positivo exige marcar (llamadas de la Mac del 2026-09-30).
FILAS_ESPERADAS = (570, 571, 573)
MODELO_CONTROL = "qwen36-35b-a3b"
#: Holgura al cruzar una fila de `metrics.db` con una llamada del log (s).
HOLGURA_S = 2.0
TRAMOS = ("<2k", "2k-10k", ">10k")
LIMITES_TRAMO = (2_000, 10_000)
#: Desde cuando rige el catalogo actual (ventana de P-4); antes los modelos eran otros.
DESDE_CATALOGO = "2026-09-15T19:26:41"

Evento = dict[str, Any]


# ---------------------------------------------------------------------------
# La regla
# ---------------------------------------------------------------------------


def tramo_de(tokens_entrada: float | None) -> str | None:
    """`<2k`, `2k-10k` o `>10k` segun los tokens de entrada; `None` si no se conocen."""
    if tokens_entrada is None:
        return None
    if tokens_entrada < LIMITES_TRAMO[0]:
        return TRAMOS[0]
    if tokens_entrada <= LIMITES_TRAMO[1]:
        return TRAMOS[1]
    return TRAMOS[2]


def calcular_lentitud(
    eventos: Iterable[Evento],
    *,
    ventana: int = VENTANA,
    minimo: int = MINIMO,
    umbral: float = UMBRAL,
    por_tramos: bool = False,
) -> list[Evento]:
    """Aplica la regla de REQ-025 y devuelve los eventos ordenados con su referencia.

    Cada evento de entrada es un dict con `ts` (numero; orden temporal), `modelo`, `tok_s`,
    `tokens_out`, `ok` (opcional, por defecto cierto) y, si `por_tramos`, `tokens_in`. La salida
    son copias en orden temporal con `ref`, `ritmo_rel` y `lento` **solo** cuando hay referencia
    (con menos de `minimo` muestras se omiten, nunca valen 0).

    La referencia de un evento mira solo hacia atras: por modelo (y por tramo, si se pide), la
    mediana de `tok_s` de los `ventana` ultimos eventos correctos con `tokens_out >= 8`. El propio
    evento no entra en su referencia; despues de evaluarlo, si es elegible, entra en la ventana.
    """
    ordenados = sorted((dict(e) for e in eventos), key=lambda e: e["ts"])
    ventanas: dict[tuple[str, str | None], list[float]] = defaultdict(list)
    for evento in ordenados:
        elegible = (
            evento.get("ok", True)
            and (evento.get("tokens_out") or 0) >= SALIDA_MINIMA
            and (evento.get("tok_s") or 0) > 0
        )
        clave = (evento["modelo"], tramo_de(evento.get("tokens_in")) if por_tramos else None)
        muestras = ventanas[clave]
        evento["elegible"] = bool(elegible)
        if elegible and len(muestras) >= minimo:
            ref = statistics.median(muestras[-ventana:])
            ritmo = round(evento["tok_s"] / ref, 2)
            evento["ref"] = ref
            evento["ritmo_rel"] = ritmo
            evento["lento"] = ritmo < umbral
        if elegible:
            muestras.append(float(evento["tok_s"]))
    return ordenados


def decidir_referencia(medianas: dict[str, float | None]) -> str:
    """«por tramos» si la mediana de `>10k` es menor que 0,75 x la de `<2k`; si no, «una referencia»."""
    corta, larga = medianas.get(TRAMOS[0]), medianas.get(TRAMOS[2])
    if corta is None or larga is None:
        return "una referencia"
    return "por tramos" if larga < RATIO_TRAMOS * corta else "una referencia"


# ---------------------------------------------------------------------------
# Datos reales
# ---------------------------------------------------------------------------


def copiar_metrics(origen: Path, destino: Path) -> list[Path]:
    """Copia `metrics.db` y sus `-wal`/`-shm` a `destino`. Nunca se abre el original."""
    destino.mkdir(parents=True, exist_ok=True)
    copiados = []
    for nombre in ("metrics.db", "metrics.db-wal", "metrics.db-shm"):
        fuente = origen / nombre
        if fuente.is_file():
            shutil.copy2(fuente, destino / nombre)
            copiados.append(destino / nombre)
    return copiados


def _epoch(valor: str) -> float:
    """Segundos desde epoch de un ISO; sin zona se toma como UTC."""
    momento = datetime.fromisoformat(valor)
    return (momento.replace(tzinfo=UTC) if momento.tzinfo is None else momento).timestamp()


def leer_filas(copia: Path) -> list[dict[str, Any]]:
    """Filas de `activity` de la copia, abierta en solo lectura. Solo respuestas 200 con generacion."""
    con = sqlite3.connect(f"file:{copia.as_posix()}?mode=ro", uri=True)
    try:
        cursor = con.execute(
            "select id, ts_created, model_id, input_tokens, cache_tokens, output_tokens,"
            " tokens_per_second, duration_ms from activity"
            " where resp_status_code = 200 and output_tokens > 0 and tokens_per_second > 0"
            " order by ts_created, id"
        )
        return [
            {
                "id": r[0],
                "fin": float(r[1]),
                "modelo": r[2],
                "entrada": r[3] + r[4],
                "salida": r[5],
                "tps": r[6],
                "dur": r[7] / 1000,
            }
            for r in cursor
        ]
    finally:
        con.close()


def leer_llamadas(directorio: Path) -> list[dict[str, Any]]:
    """Llamadas `backend: local` de los `usage-*.jsonl`, con su intervalo."""
    llamadas = []
    for fichero in sorted(directorio.glob("usage-*.jsonl")):
        for linea in fichero.read_text(encoding="utf-8").splitlines():
            try:
                u = json.loads(linea)
                fin = datetime.fromisoformat(u["ts"]).timestamp()
                latencia = float(u["latency_ms"]) / 1000
            except (ValueError, KeyError, TypeError):
                continue
            if u.get("backend", "local") != "local":
                continue
            llamadas.append(
                {
                    "fin": fin,
                    "ini": fin - latencia,
                    "modelo": u.get("model"),
                    "ok": bool(u.get("ok", True)),
                    "tool": u.get("tool"),
                }
            )
    return llamadas


def _llamada_de(fila: dict[str, Any], llamadas: Sequence[dict[str, Any]]) -> int | None:
    """Indice de la llamada del log que contiene la fila; si hay varias, la mas ajustada."""
    ini = fila["fin"] - fila["dur"]
    mejor, holgura_mejor = None, None
    for i, llamada in enumerate(llamadas):
        if llamada["modelo"] not in (None, fila["modelo"]):
            continue
        if llamada["ini"] - HOLGURA_S <= ini and fila["fin"] <= llamada["fin"] + HOLGURA_S:
            holgura = (ini - llamada["ini"]) + (llamada["fin"] - fila["fin"])
            if holgura_mejor is None or holgura < holgura_mejor:
                mejor, holgura_mejor = i, holgura
    return mejor


def agrupar_por_evento(
    filas: Sequence[dict[str, Any]], llamadas: Sequence[dict[str, Any]]
) -> list[Evento]:
    """Cruza las filas con el log y las agrupa por evento (una llamada del log = un evento)."""
    por_llamada: dict[int, list[dict[str, Any]]] = defaultdict(list)
    sueltas: list[dict[str, Any]] = []
    for fila in filas:
        i = _llamada_de(fila, llamadas)
        if i is None:
            sueltas.append(fila)
        else:
            por_llamada[i].append(fila)

    def _evento(grupo: list[dict[str, Any]], origen: str, ok: bool, ts: float) -> Evento:
        salida = sum(f["salida"] for f in grupo)
        ms_generacion = sum(f["salida"] / f["tps"] for f in grupo)  # segundos
        return {
            "ts": ts,
            "modelo": grupo[0]["modelo"],
            "origen": origen,
            "ok": ok,
            "tokens_out": salida,
            "tokens_in": max(f["entrada"] for f in grupo),
            "tok_s": salida / ms_generacion,
            "filas": sorted(f["id"] for f in grupo),
        }

    eventos = [
        _evento(grupo, "PC", llamadas[i]["ok"], max(f["fin"] for f in grupo))
        for i, grupo in por_llamada.items()
    ]
    eventos += [_evento([f], "no-PC", True, f["fin"]) for f in sueltas]
    return eventos


# ---------------------------------------------------------------------------
# Controles
# ---------------------------------------------------------------------------


def _mediana(valores: Sequence[float]) -> float | None:
    return round(statistics.median(valores), 1) if valores else None


def control_a(
    evaluados: Sequence[Evento], desde_ts: float, hasta_ts: float | None = None
) -> dict[str, Any]:
    """(a) Porcentaje de eventos de la PC que marca la regla, dentro de la ventana de fechas."""
    pc = [
        e
        for e in evaluados
        if e["origen"] == "PC" and e["ts"] >= desde_ts and (hasta_ts is None or e["ts"] <= hasta_ts)
    ]
    con_ref = [e for e in pc if "ritmo_rel" in e]
    marcados = [e for e in con_ref if e["lento"]]
    return {
        "eventos_pc": len(pc),
        "con_referencia": len(con_ref),
        "marcados": len(marcados),
        "pct_sobre_con_referencia": round(100 * len(marcados) / len(con_ref), 2)
        if con_ref
        else 0.0,
        "pct_sobre_eventos_pc": round(100 * len(marcados) / len(pc), 2) if pc else 0.0,
        "supera_el_tope": bool(con_ref) and len(marcados) / len(con_ref) > TOPE_MARCADOS,
        "detalle": [
            {
                "filas": e["filas"],
                "modelo": e["modelo"],
                "tok_s": round(e["tok_s"], 1),
                "ref": round(e["ref"], 1),
                "ritmo_rel": e["ritmo_rel"],
                "tokens_in": e["tokens_in"],
                "fecha": _iso(e["ts"]),
            }
            for e in marcados
        ],
    }


def control_b(evaluados: Sequence[Evento]) -> dict[str, Any]:
    """(b) La regla sobre las filas de Qwen3.6 de todos los origenes marca 570, 571 y 573."""
    marcadas: set[int] = set()
    for e in evaluados:
        if e["modelo"] == MODELO_CONTROL and e.get("lento"):
            marcadas.update(e["filas"])
    por_fila = {}
    for e in evaluados:
        if e["modelo"] == MODELO_CONTROL:
            for fila in e["filas"]:
                if fila in FILAS_ESPERADAS or fila == 574:
                    por_fila[fila] = {
                        "origen": e["origen"],
                        "tok_s": round(e["tok_s"], 1),
                        "ref": round(e["ref"], 1) if "ref" in e else None,
                        "ritmo_rel": e.get("ritmo_rel"),
                        "lento": e.get("lento"),
                    }
    return {
        "esperadas": list(FILAS_ESPERADAS),
        "marcadas_de_las_esperadas": sorted(set(FILAS_ESPERADAS) & marcadas),
        "faltan": sorted(set(FILAS_ESPERADAS) - marcadas),
        "cumple": set(FILAS_ESPERADAS) <= marcadas,
        "filas_clave": dict(sorted(por_fila.items())),
        "total_marcadas_qwen36": len(marcadas),
    }


def control_tramos(eventos: Sequence[Evento], desde_ts: float) -> dict[str, Any]:
    """(c) Mediana de generacion por tramo de entrada, en los eventos de la PC desde `desde_ts`.

    Se hace por modelo y, para decidir, con el ritmo normalizado por la mediana del modelo (cada
    modelo tiene su velocidad): mezclar tok/s de un 4B y de un 26B no compara tramos, compara modelos.
    """
    pc = [
        e
        for e in eventos
        if e["origen"] == "PC"
        and e["ts"] >= desde_ts
        and e.get("ok", True)
        and e["tokens_out"] >= SALIDA_MINIMA
    ]
    por_modelo: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for e in pc:
        por_modelo[e["modelo"]][tramo_de(e["tokens_in"]) or "?"].append(e["tok_s"])
    resumen_modelos = {}
    normalizados: dict[str, list[float]] = defaultdict(list)
    for modelo, tramos in sorted(por_modelo.items()):
        todos = [v for lista in tramos.values() for v in lista]
        mediana_modelo = statistics.median(todos)
        medianas = {t: _mediana(tramos.get(t, [])) for t in TRAMOS}
        medio, largo = medianas[TRAMOS[1]], medianas[TRAMOS[2]]
        resumen_modelos[modelo] = {
            "n": {t: len(tramos.get(t, [])) for t in TRAMOS},
            "mediana_tok_s": medianas,
            "ratio_largo_sobre_medio": round(largo / medio, 3) if largo and medio else None,
            "decision_si_solo_este_modelo": (
                decidir_referencia(medianas)
                if len(tramos.get(TRAMOS[0], [])) >= MINIMO
                and len(tramos.get(TRAMOS[2], [])) >= MINIMO
                else "sin muestras suficientes (minimo 10 por tramo)"
            ),
        }
        for t, lista in tramos.items():
            normalizados[t] += [v / mediana_modelo for v in lista]
    medianas_norm = {t: _mediana_fina(normalizados.get(t, [])) for t in TRAMOS}
    return {
        "por_modelo": resumen_modelos,
        "n_global": {t: len(normalizados.get(t, [])) for t in TRAMOS},
        "mediana_normalizada_por_modelo": medianas_norm,
        "decision": decidir_referencia(medianas_norm),
    }


def _mediana_fina(valores: Sequence[float]) -> float | None:
    return round(statistics.median(valores), 3) if valores else None


def falsos_positivos_largos(
    evaluados: Sequence[Evento], desde_ts: float, hasta_ts: float | None = None
) -> dict[str, Any]:
    """Eventos de la PC con mas de 10k tokens de entrada que la regla marca como lentos."""
    largos = [
        e
        for e in evaluados
        if e["origen"] == "PC"
        and e["ts"] >= desde_ts
        and (hasta_ts is None or e["ts"] <= hasta_ts)
        and tramo_de(e["tokens_in"]) == TRAMOS[2]
        and "ritmo_rel" in e
    ]
    marcados = [e for e in largos if e["lento"]]
    return {
        "eventos_largos_evaluados": len(largos),
        "marcados": len(marcados),
        "detalle": [
            {
                "filas": e["filas"],
                "modelo": e["modelo"],
                "tok_s": round(e["tok_s"], 1),
                "ref": round(e["ref"], 1),
                "ritmo_rel": e["ritmo_rel"],
                "tokens_in": e["tokens_in"],
                "fecha": _iso(e["ts"]),
            }
            for e in marcados
        ],
    }


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def medir(
    filas: Sequence[dict[str, Any]],
    llamadas: Sequence[dict[str, Any]],
    *,
    desde: str,
    hasta: str | None = None,
) -> dict[str, Any]:
    """Los controles (a), (b), (c) y los falsos positivos largos sobre datos ya leidos.

    El historial anterior a `desde` calienta las ventanas (el daemon siembra con el log del mes y
    el anterior), pero solo se cuentan los eventos de `desde` a `hasta`.
    """
    desde_ts = _epoch(desde)
    hasta_ts = _epoch(hasta) if hasta else None
    eventos = agrupar_por_evento(filas, llamadas)
    una = calcular_lentitud(eventos)
    tramos = control_tramos(
        [e for e in eventos if hasta_ts is None or e["ts"] <= hasta_ts], desde_ts
    )
    por_tramos = tramos["decision"] == "por tramos"
    elegida = calcular_lentitud(eventos, por_tramos=True) if por_tramos else una
    return {
        "ventana": {
            "desde": desde,
            "hasta": hasta,
            "primera_fila": _iso(min(f["fin"] for f in filas)) if filas else None,
            "ultima_fila": _iso(max(f["fin"] for f in filas)) if filas else None,
            "filas": len(filas),
            "eventos": len(eventos),
            "eventos_pc": sum(1 for e in eventos if e["origen"] == "PC"),
        },
        "a": control_a(una, desde_ts, hasta_ts),
        "b": control_b(una),
        "tramos": tramos,
        "referencia_elegida": tramos["decision"],
        "falsos_positivos_largos": {
            "una_referencia": falsos_positivos_largos(una, desde_ts, hasta_ts),
            "regla_elegida": falsos_positivos_largos(elegida, desde_ts, hasta_ts),
        },
        "a_con_regla_elegida": control_a(elegida, desde_ts, hasta_ts) if por_tramos else None,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _log_dir() -> Path:
    from local_delegate import config

    return Path(config.LOG_DIR)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--copia", type=Path, required=True, help="carpeta donde queda la copia de metrics.db"
    )
    p.add_argument(
        "--origen",
        type=Path,
        default=None,
        help="carpeta con el metrics.db real; si se omite, se usa la copia que ya haya en --copia",
    )
    p.add_argument(
        "--logs",
        type=Path,
        default=None,
        help="carpeta de usage-*.jsonl (por defecto config.LOG_DIR)",
    )
    p.add_argument("--desde", default=DESDE_CATALOGO, help="inicio UTC de la ventana medida")
    p.add_argument("--hasta", default=None, help="fin UTC de la ventana medida")
    p.add_argument("--json", action="store_true", help="salida JSON completa")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.origen is not None:
        copiar_metrics(args.origen, args.copia)
    base = args.copia / "metrics.db"
    if not base.is_file():
        print(f"No hay copia de metrics.db en {args.copia}", file=sys.stderr)
        return 2
    logs = args.logs or _log_dir()
    resultado = medir(leer_filas(base), leer_llamadas(logs), desde=args.desde, hasta=args.hasta)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    if resultado["a"]["supera_el_tope"]:
        print("PARAR: (a) marca mas del 5 %; revisar el umbral con el usuario.", file=sys.stderr)
        return 3
    if not resultado["b"]["cumple"]:
        print("PARAR: (b) no marca 570, 571 y 573; la regla esta mal.", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
