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

La regla (REQ-025, en `local_delegate.pace`), por modelo y en orden temporal: la referencia de un evento es la mediana de
`tok_s` de los **50 ultimos eventos correctos con `tokens_out >= 8` anteriores a el**, con un minimo
de 10; el evento lleva `pace_rel = tok_s / referencia` y es `slow` si `pace_rel < umbral`.

Reglas de lectura de los datos:

- `metrics.db` no se abre en su sitio: lo usa llama-swap. `copy_metrics` copia `metrics.db`,
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
    uv run python scripts/measure_slowness.py --copy <carpeta_de_la_copia> \\
        --source <carpeta_con_metrics.db> --since 2026-09-15T19:26:41
    uv run python scripts/measure_slowness.py --copy <carpeta> --json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import statistics
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# La regla vive en el paquete (una sola fuente para este control y para el daemon); se reexporta
# aqui para que el control y su test la usen con los mismos nombres de siempre.
from local_delegate.pace import (
    MINIMAL_OUTPUT,
    MINIMUM,
    SPAN_LIMITS,
    SPANS,
    THRESHOLD,
    WINDOW,
    Event,
    compute_slowness,
    span_of,
)

__all__ = [
    "MINIMAL_OUTPUT",
    "MINIMUM",
    "SPANS",
    "SPAN_LIMITS",
    "THRESHOLD",
    "WINDOW",
    "compute_slowness",
    "span_of",
]

#: Decision de REQ-025: si el tramo largo baja de esto respecto al corto, la referencia va por tramos.
SPAN_RATIO = 0.75
#: Tope de eventos marcados sobre los de la PC antes de parar y revisar el umbral con el usuario.
MARKED_CAP = 0.05
#: Filas que el control positivo exige marcar (llamadas de la Mac del 2026-09-30).
EXPECTED_ROWS = (570, 571, 573)
CONTROL_MODEL = "qwen36-35b-a3b"
#: Holgura al cruzar una fila de `metrics.db` con una llamada del log (s).
SLACK_S = 2.0
#: Desde cuando rige el catalogo actual (ventana de P-4); antes los modelos eran otros.
FROM_CATALOG = "2026-09-15T19:26:41"


# ---------------------------------------------------------------------------
# La regla
# ---------------------------------------------------------------------------


def decide_reference(medians: dict[str, float | None]) -> str:
    """«por tramos» si la mediana de `>10k` es menor que 0,75 x la de `<2k`; si no, «una referencia»."""
    short, long_one = medians.get(SPANS[0]), medians.get(SPANS[2])
    if short is None or long_one is None:
        return "una referencia"
    return "por tramos" if long_one < SPAN_RATIO * short else "una referencia"


# ---------------------------------------------------------------------------
# Datos reales
# ---------------------------------------------------------------------------


def copy_metrics(origin: Path, target: Path) -> list[Path]:
    """Copia `metrics.db` y sus `-wal`/`-shm` a `target`. Nunca se abre el original."""
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in ("metrics.db", "metrics.db-wal", "metrics.db-shm"):
        source = origin / name
        if source.is_file():
            shutil.copy2(source, target / name)
            copied.append(target / name)
    return copied


def _epoch(value: str) -> float:
    """Segundos desde epoch de un ISO; sin zona se toma como UTC."""
    moment = datetime.fromisoformat(value)
    return (moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment).timestamp()


def read_rows(copy: Path) -> list[dict[str, Any]]:
    """Filas de `activity` de la copia, abierta en solo lectura. Solo respuestas 200 con generacion."""
    with_ = sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)
    try:
        cursor = with_.execute(
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
        with_.close()


def read_calls(directory: Path) -> list[dict[str, Any]]:
    """Llamadas `backend: local` de los `usage-*.jsonl`, con su intervalo."""
    calls = []
    for file in sorted(directory.glob("usage-*.jsonl")):
        for line in file.read_text(encoding="utf-8").splitlines():
            try:
                u = json.loads(line)
                end = datetime.fromisoformat(u["ts"]).timestamp()
                latency = float(u["latency_ms"]) / 1000
            except (ValueError, KeyError, TypeError):
                continue
            if u.get("backend", "local") != "local":
                continue
            calls.append(
                {
                    "fin": end,
                    "ini": end - latency,
                    "modelo": u.get("model"),
                    "ok": bool(u.get("ok", True)),
                    "tool": u.get("tool"),
                }
            )
    return calls


def _call_of(row: dict[str, Any], calls: Sequence[dict[str, Any]]) -> int | None:
    """Indice de la llamada del log que contiene la fila; si hay varias, la mas ajustada."""
    ini = row["fin"] - row["dur"]
    best, best_slack = None, None
    for i, call in enumerate(calls):
        if call["modelo"] not in (None, row["modelo"]):
            continue
        if call["ini"] - SLACK_S <= ini and row["fin"] <= call["fin"] + SLACK_S:
            slack = (ini - call["ini"]) + (call["fin"] - row["fin"])
            if best_slack is None or slack < best_slack:
                best, best_slack = i, slack
    return best


def group_by_event(rows: Sequence[dict[str, Any]], calls: Sequence[dict[str, Any]]) -> list[Event]:
    """Cruza las filas con el log y las agrupa por evento (una llamada del log = un evento)."""
    by_call: dict[int, list[dict[str, Any]]] = defaultdict(list)
    loose_ones: list[dict[str, Any]] = []
    for row in rows:
        i = _call_of(row, calls)
        if i is None:
            loose_ones.append(row)
        else:
            by_call[i].append(row)

    def _event(group: list[dict[str, Any]], origin: str, ok: bool, ts: float) -> Event:
        output = sum(f["salida"] for f in group)
        generation_ms = sum(f["salida"] / f["tps"] for f in group)  # segundos
        return {
            "ts": ts,
            "modelo": group[0]["modelo"],
            "origen": origin,
            "ok": ok,
            "tokens_out": output,
            "tokens_in": max(f["entrada"] for f in group),
            "tok_s": output / generation_ms,
            "filas": sorted(f["id"] for f in group),
        }

    events = [
        _event(group, "PC", calls[i]["ok"], max(f["fin"] for f in group))
        for i, group in by_call.items()
    ]
    events += [_event([f], "no-PC", True, f["fin"]) for f in loose_ones]
    return events


# ---------------------------------------------------------------------------
# Controles
# ---------------------------------------------------------------------------


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def control_a(
    evaluated: Sequence[Event], since_ts: float, until_ts: float | None = None
) -> dict[str, Any]:
    """(a) Porcentaje de eventos de la PC que marca la regla, dentro de la ventana de fechas."""
    pc = [
        e
        for e in evaluated
        if e["origen"] == "PC" and e["ts"] >= since_ts and (until_ts is None or e["ts"] <= until_ts)
    ]
    with_ref = [e for e in pc if "pace_rel" in e]
    marked = [e for e in with_ref if e["slow"]]
    return {
        "eventos_pc": len(pc),
        "con_referencia": len(with_ref),
        "marcados": len(marked),
        "pct_sobre_con_referencia": round(100 * len(marked) / len(with_ref), 2)
        if with_ref
        else 0.0,
        "pct_sobre_eventos_pc": round(100 * len(marked) / len(pc), 2) if pc else 0.0,
        "supera_el_tope": bool(with_ref) and len(marked) / len(with_ref) > MARKED_CAP,
        "detalle": [
            {
                "filas": e["filas"],
                "modelo": e["modelo"],
                "tok_s": round(e["tok_s"], 1),
                "ref": round(e["ref"], 1),
                "pace_rel": e["pace_rel"],
                "tokens_in": e["tokens_in"],
                "fecha": _iso(e["ts"]),
            }
            for e in marked
        ],
    }


def control_b(evaluated: Sequence[Event]) -> dict[str, Any]:
    """(b) La regla sobre las filas de Qwen3.6 de todos los origenes marca 570, 571 y 573."""
    marked_ones: set[int] = set()
    for e in evaluated:
        if e["modelo"] == CONTROL_MODEL and e.get("slow"):
            marked_ones.update(e["filas"])
    by_row = {}
    for e in evaluated:
        if e["modelo"] == CONTROL_MODEL:
            for row in e["filas"]:
                if row in EXPECTED_ROWS or row == 574:
                    by_row[row] = {
                        "origen": e["origen"],
                        "tok_s": round(e["tok_s"], 1),
                        "ref": round(e["ref"], 1) if "ref" in e else None,
                        "pace_rel": e.get("pace_rel"),
                        "slow": e.get("slow"),
                    }
    return {
        "esperadas": list(EXPECTED_ROWS),
        "marcadas_de_las_esperadas": sorted(set(EXPECTED_ROWS) & marked_ones),
        "faltan": sorted(set(EXPECTED_ROWS) - marked_ones),
        "cumple": set(EXPECTED_ROWS) <= marked_ones,
        "filas_clave": dict(sorted(by_row.items())),
        "total_marcadas_qwen36": len(marked_ones),
    }


def control_spans(events: Sequence[Event], since_ts: float) -> dict[str, Any]:
    """(c) Mediana de generacion por tramo de entrada, en los eventos de la PC desde `since_ts`.

    Se hace por modelo y, para decidir, con el ritmo normalizado por la mediana del modelo (cada
    modelo tiene su velocidad): mezclar tok/s de un 4B y de un 26B no compara tramos, compara modelos.
    """
    pc = [
        e
        for e in events
        if e["origen"] == "PC"
        and e["ts"] >= since_ts
        and e.get("ok", True)
        and e["tokens_out"] >= MINIMAL_OUTPUT
    ]
    by_model: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for e in pc:
        by_model[e["modelo"]][span_of(e["tokens_in"]) or "?"].append(e["tok_s"])
    models_summary = {}
    normalized: dict[str, list[float]] = defaultdict(list)
    for model, spans in sorted(by_model.items()):
        all_items = [v for items in spans.values() for v in items]
        model_median = statistics.median(all_items)
        medians = {t: _median(spans.get(t, [])) for t in SPANS}
        mean, long = medians[SPANS[1]], medians[SPANS[2]]
        models_summary[model] = {
            "n": {t: len(spans.get(t, [])) for t in SPANS},
            "mediana_tok_s": medians,
            "ratio_largo_sobre_medio": round(long / mean, 3) if long and mean else None,
            "decision_si_solo_este_modelo": (
                decide_reference(medians)
                if len(spans.get(SPANS[0], [])) >= MINIMUM
                and len(spans.get(SPANS[2], [])) >= MINIMUM
                else "sin muestras suficientes (minimo 10 por tramo)"
            ),
        }
        for t, items in spans.items():
            normalized[t] += [v / model_median for v in items]
    normalized_medians = {t: _fine_median(normalized.get(t, [])) for t in SPANS}
    return {
        "por_modelo": models_summary,
        "n_global": {t: len(normalized.get(t, [])) for t in SPANS},
        "mediana_normalizada_por_modelo": normalized_medians,
        "decision": decide_reference(normalized_medians),
    }


def _fine_median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def long_false_positives(
    evaluated: Sequence[Event], since_ts: float, until_ts: float | None = None
) -> dict[str, Any]:
    """Eventos de la PC con mas de 10k tokens de entrada que la regla marca como lentos."""
    long_ones_list = [
        e
        for e in evaluated
        if e["origen"] == "PC"
        and e["ts"] >= since_ts
        and (until_ts is None or e["ts"] <= until_ts)
        and span_of(e["tokens_in"]) == SPANS[2]
        and "pace_rel" in e
    ]
    marked = [e for e in long_ones_list if e["slow"]]
    return {
        "eventos_largos_evaluados": len(long_ones_list),
        "marcados": len(marked),
        "detalle": [
            {
                "filas": e["filas"],
                "modelo": e["modelo"],
                "tok_s": round(e["tok_s"], 1),
                "ref": round(e["ref"], 1),
                "pace_rel": e["pace_rel"],
                "tokens_in": e["tokens_in"],
                "fecha": _iso(e["ts"]),
            }
            for e in marked
        ],
    }


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def measure(
    rows: Sequence[dict[str, Any]],
    calls: Sequence[dict[str, Any]],
    *,
    since: str,
    until: str | None = None,
) -> dict[str, Any]:
    """Los controles (a), (b), (c) y los falsos positivos largos sobre datos ya leidos.

    El historial anterior a `since` calienta las ventanas (el daemon siembra con el log del mes y
    el anterior), pero solo se cuentan los eventos de `since` a `until`.
    """
    since_ts = _epoch(since)
    until_ts = _epoch(until) if until else None
    events = group_by_event(rows, calls)
    one_item = compute_slowness(events)
    spans = control_spans([e for e in events if until_ts is None or e["ts"] <= until_ts], since_ts)
    by_spans = spans["decision"] == "por tramos"
    chosen = compute_slowness(events, by_spans=True) if by_spans else one_item
    return {
        "ventana": {
            "desde": since,
            "hasta": until,
            "primera_fila": _iso(min(f["fin"] for f in rows)) if rows else None,
            "ultima_fila": _iso(max(f["fin"] for f in rows)) if rows else None,
            "filas": len(rows),
            "eventos": len(events),
            "eventos_pc": sum(1 for e in events if e["origen"] == "PC"),
        },
        "a": control_a(one_item, since_ts, until_ts),
        "b": control_b(one_item),
        "tramos": spans,
        "referencia_elegida": spans["decision"],
        "falsos_positivos_largos": {
            "una_referencia": long_false_positives(one_item, since_ts, until_ts),
            "regla_elegida": long_false_positives(chosen, since_ts, until_ts),
        },
        "a_con_regla_elegida": control_a(chosen, since_ts, until_ts) if by_spans else None,
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
        "--copy", type=Path, required=True, help="carpeta donde queda la copia de metrics.db"
    )
    p.add_argument(
        "--source",
        type=Path,
        default=None,
        help="carpeta con el metrics.db real; si se omite, se usa la copia que ya haya en --copy",
    )
    p.add_argument(
        "--logs",
        type=Path,
        default=None,
        help="carpeta de usage-*.jsonl (por defecto config.LOG_DIR)",
    )
    p.add_argument("--since", default=FROM_CATALOG, help="inicio UTC de la ventana medida")
    p.add_argument("--until", default=None, help="fin UTC de la ventana medida")
    p.add_argument("--json", action="store_true", help="salida JSON completa")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.source is not None:
        copy_metrics(args.source, args.copy)
    base = args.copy / "metrics.db"
    if not base.is_file():
        print(f"No hay copia de metrics.db en {args.copy}", file=sys.stderr)
        return 2
    logs = args.logs or _log_dir()
    result = measure(read_rows(base), read_calls(logs), since=args.since, until=args.until)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if result["a"]["supera_el_tope"]:
        print("PARAR: (a) marca mas del 5 %; revisar el umbral con el usuario.", file=sys.stderr)
        return 3
    if not result["b"]["cumple"]:
        print("PARAR: (b) no marca 570, 571 y 573; la regla esta mal.", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
