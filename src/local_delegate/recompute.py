"""`local-delegate recompute-cost`: relleno, agregados de `N`, cotejo real y puntos de cuota.

Lo lanza el usuario (REQ-070). Lee los transcripts de `claude_dir/projects`, el registro del
statusline (`claude_dir/quota-statusline.jsonl` y, si existe, el nombre viejo
`claude_dir/cuota-statusline.jsonl`: los dos si están los dos) y el log de uso, y escribe SOLO en
el directorio de logs (REQ-074):

- `attribution-AAAAMM.json` por mes, con `attribution.write_backfill` (REQ-004, REQ-005);
- `cost-aggregates.json`, cuyo formato lee y escribe solo este módulo (ver el plan):
  `{"version", "generated", "cleanup_days", "check", "n_by_month", "points", "discards",
  "resets", "sources"}`.

El fichero viejo, `coste-agregados.json`, no se reescribe nunca: si el nuevo aún no existe, se lee
traducido (`legacy_names.normalize_cost_aggregates`) y la primera corrida siembra el nuevo con él;
desde entonces solo se lee el nuevo (REQ-006).

Nada de lo que escribe lleva rutas, ids de sesión ni texto (REQ-072). Lanzado dos veces con los
mismos datos, deja los mismos ficheros salvo `generated` (REQ-074).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import attribution, cost, legacy_names, precios, quota, transcripts

OLD_FILE_NAME, FILE_NAME = legacy_names.COST_AGGREGATES_FILE_NAMES
VERSION = 1

#: Los agregados de `N` de un mes que terminó hace más de esto no se recalculan (REQ-071).
CLOSED_MONTH = timedelta(days=30)

_MONTH_FILE = re.compile(r"^usage-(\d{6})\.jsonl$")


# --- cost-aggregates.json -----------------------------------------------------------------------


def aggregates_path(log_dir: Path) -> Path:
    return Path(log_dir) / FILE_NAME


def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def read_aggregates(log_dir: Path) -> dict | None:
    """Los últimos agregados en el formato nuevo, o `None` si no hay o no tienen la forma.

    Se lee `cost-aggregates.json`. Solo si aún no existe, se lee `coste-agregados.json` traducido
    entero al formato nuevo, con los puntos ya con su identidad nueva (`source`, `type`, `start`,
    `end`): `run` parte de esta lectura, así que la siembra ocurre una sola vez. Un fichero nuevo
    dañado cuenta como vacío y no vuelve a sembrar (REQ-006).
    """
    path = aggregates_path(log_dir)
    data = _load(path) if path.exists() else _load(Path(log_dir) / OLD_FILE_NAME)
    return legacy_names.normalize_cost_aggregates(data) if data is not None else None


def write_aggregates(log_dir: Path, aggregates: dict) -> None:
    """Escribe el JSON de forma atómica (temporal en el mismo directorio y `os.replace`)."""
    target = aggregates_path(log_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=".", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(aggregates, stream, ensure_ascii=False, sort_keys=True, indent=1)
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            # Limpieza de mejor esfuerzo: si el temporal ya no está o no se puede borrar, se
            # ignora para que el `raise` de abajo propague el error original y no este.
            pass
        raise


# --- El log de uso --------------------------------------------------------------------------


def _log_files(log_dir: Path) -> list[tuple[Path, str]]:
    out = []
    if Path(log_dir).is_dir():
        for p in sorted(Path(log_dir).glob("usage-*.jsonl")):
            m = _MONTH_FILE.match(p.name)
            if m:
                out.append((p, m.group(1)))
    return out


def _read_log(path: Path) -> list[dict]:
    """Las filas del fichero como las lee el panel: las líneas rotas se saltan (no cambian el
    ordinal de las demás, que solo cuenta líneas con `ts` y `tool`)."""
    rows: list[dict] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def _month(ts: object) -> str | None:
    t = transcripts.parse_instant(ts)
    return f"{t:%Y%m}" if t else None


def _month_end(month: str) -> datetime:
    year, m = int(month[:4]), int(month[4:6])
    return datetime(year + (m == 12), (m % 12) + 1, 1, tzinfo=UTC)


# --- Agregados de N (REQ-042 (2), REQ-071) --------------------------------------------------


def _n_of_file(merged: list[dict]) -> dict[str, dict[str, list[int]]]:
    """`{mes: {"modelo|hilo": [N, ...]}}` de las delegaciones atribuibles con `N` del relleno que
    no están excluidas (ni clientes de pruebas ni bancos)."""
    by_month: dict[str, dict[str, list[int]]] = {}
    for f in merged:
        if f.get("ok") is False or f.get("caller_origin") == "fallback":
            continue
        n = f.get("n")
        if isinstance(n, bool) or not isinstance(n, int):
            continue
        if attribution.exclusion_reason(f, {"bench": f.get("bench")}):
            continue
        month = _month(f.get("ts"))
        model, thread = f.get("caller_model"), f.get("caller_kind")
        if not month or not model or thread not in cost.THREADS:
            continue
        by_month.setdefault(month, {}).setdefault(f"{model}|{thread}", []).append(n)
    return by_month


def _merge_n_by_month(fresh: dict, previous: dict, *, now: datetime) -> dict:
    """Un mes cerrado hace más de 30 días conserva lo guardado; los demás se recalculan."""
    out: dict = {}
    for month in sorted(set(fresh) | set(previous)):
        closed = now - _month_end(month) > CLOSED_MONTH
        if month in previous and (closed or month not in fresh):
            out[month] = previous[month]
        else:
            out[month] = {g: sorted(v) for g, v in sorted(fresh[month].items())}
    return out


# --- Cotejo (REQ-014) -----------------------------------------------------------------------

_VERDICT_VALUES = legacy_names.FORMATS["cost_aggregates_check"]["values"]["verdict"]


def _check(index: transcripts.Index, *, now: datetime) -> dict | None:
    rows = transcripts.cost_state(index)
    if not rows:
        return None
    table = precios.cargar_precios()
    results = precios.cotejar(rows, table)
    unpriced = sorted(
        {precios.normalizar_id(f["modelo"]) for f, r in zip(rows, results) if r == "sin_precio"}
    )
    return {
        "date": now.isoformat(timespec="seconds"),
        "table_version": table.get("consultado"),
        "judged": sum(1 for r in results if r is not None),
        "outside": sum(1 for r in results if r == "fuera"),
        "unpriced": unpriced,
        # `precios.veredicto` aún responde `pasa|falla`: se guarda el valor nuevo.
        "verdict": legacy_names.new_value(_VERDICT_VALUES, precios.veredicto(results)),
    }


# --- Puntos de cuota (REQ-051 a REQ-054, REQ-071) -------------------------------------------


def _point_key(p: dict) -> tuple:
    """La identidad del punto. Los puntos viejos llegan ya traducidos (`read_aggregates`)."""
    return (p.get("source"), p.get("type"), p.get("start"), p.get("end"))


def _statusline_logs(claude_dir: Path) -> list[Path]:
    """Los registros del statusline que hay, el nuevo primero. Los escribe el statusline del
    usuario, que puede seguir con el nombre viejo: si están los dos, se leen los dos (REQ-008)."""
    old, new = legacy_names.QUOTA_STATUSLINE_FILE_NAMES
    return [p for p in (Path(claude_dir) / new, Path(claude_dir) / old) if p.is_file()]


def _lines_of(paths: list[Path]) -> Iterator[str]:
    for path in paths:
        with path.open(encoding="utf-8", errors="replace") as stream:
            yield from stream


def _add_discards(target: dict[str, Counter], origin: dict[str, Counter]) -> None:
    for kind, counts in origin.items():
        target.setdefault(kind, Counter()).update(counts)


def _points(
    claude_dir: Path, index: transcripts.Index, previous: list, *, now: datetime
) -> tuple[list[dict], dict[str, dict[str, int]], bool]:
    discards = quota.empty_discards()
    if index.corrupt_lines or index.unreadable_files:
        for kind in quota.TYPES:
            discards[kind]["corrupt_line"] += index.corrupt_lines + index.unreadable_files
    requests = list(index.requests.values())
    fresh = quota.rejection_points(index.rejections, requests)

    statusline_logs = _statusline_logs(claude_dir)
    has_statusline = bool(statusline_logs)
    if has_statusline:
        try:
            by_type, sessions, d = quota.sanitize(_lines_of(statusline_logs))
        except OSError:
            by_type, sessions, d = {}, set(), quota.empty_discards()
            for kind in quota.TYPES:
                d[kind]["corrupt_line"] += 1
        _add_discards(discards, d)
        from_statusline, d = quota.statusline_points(by_type, sessions, requests)
        _add_discards(discards, d)
        fresh += from_statusline

    # Fundir con los del JSON anterior por (source, type, start, end): un punto cuyo transcript
    # ya se borró sigue ahí hasta que caduca (REQ-071).
    previous, d = quota.split_malformed(previous)
    _add_discards(discards, d)
    by_key = {_point_key(p): p for p in previous}
    for p in fresh:
        by_key[_point_key(p)] = p
    alive = [p for p in by_key.values() if quota.current_points([p], now)]
    points, d = quota.drop_overlapping(alive)
    _add_discards(discards, d)
    clean = {kind: dict(sorted(c.items())) for kind, c in discards.items()}
    return points, clean, has_statusline


# --- El comando -----------------------------------------------------------------------------


def run(
    claude_dir: Path,
    log_dir: Path,
    *,
    now: datetime | None = None,
    reset: str | None = None,
) -> dict:
    """Recalcula todo y devuelve un resumen con conteos (sin rutas)."""
    now = now or datetime.now(UTC)
    claude_dir, log_dir = Path(claude_dir), Path(log_dir)
    cleanup_days = attribution.cleanup_period_days(claude_dir)
    projects = claude_dir / "projects"
    has_transcripts = projects.is_dir()
    index = transcripts.read(projects)
    previous = read_aggregates(log_dir) or {}

    # 1. Relleno, por fichero y con las claves del fichero ENTERO (REQ-004, REQ-005).
    since = now - timedelta(days=cleanup_days)
    matches: Counter = Counter()
    lines_in_window = 0
    files = _log_files(log_dir)
    rows_by_file = []
    for path, _ym in files:
        rows = _read_log(path)
        rows_by_file.append(rows)
        if not has_transcripts:
            continue  # sin transcripts no hay nada con qué casar: no se marca nada `no_match`
        keys = attribution.file_keys(rows)
        entries = transcripts.match_lines(zip(keys, rows, strict=True), index, since=since)
        by_month: dict[str, dict[str, dict]] = {}
        for key, row in zip(keys, rows, strict=True):
            if key in entries:
                month = _month(row.get("ts"))
                if month:
                    by_month.setdefault(month, {})[key] = entries[key]
        for month, month_entries in sorted(by_month.items()):
            attribution.write_backfill(log_dir, month, month_entries)
        lines_in_window += len(entries)
        matches.update(e["match"] for e in entries.values())

    # 2. Agregados de N, sobre las filas fundidas con el relleno ya escrito.
    fresh_n: dict[str, dict[str, list[int]]] = {}
    for rows in rows_by_file:
        for month, groups in _n_of_file(cost.merge(rows, log_dir=log_dir)).items():
            target = fresh_n.setdefault(month, {})
            for group, values in groups.items():
                target.setdefault(group, []).extend(values)
    previous_n = previous.get("n_by_month") if isinstance(previous.get("n_by_month"), dict) else {}
    n_by_month = _merge_n_by_month(fresh_n, previous_n, now=now)

    # 3. Cotejo real; sin filas `cost-state`, se conserva el último.
    check = _check(index, now=now)
    if check is None and isinstance(previous.get("check"), dict):
        check = previous["check"]

    # 4. Puntos de cuota y reinicios.
    previous_points = previous.get("points") if isinstance(previous.get("points"), list) else []
    points, discards, has_statusline = _points(claude_dir, index, previous_points, now=now)
    resets = {kind: None for kind in quota.TYPES}
    if isinstance(previous.get("resets"), dict):
        resets.update({t: previous["resets"].get(t) for t in quota.TYPES})
    if reset:
        resets[reset] = now.isoformat(timespec="seconds")

    aggregates = {
        "version": VERSION,
        "generated": now.isoformat(timespec="seconds"),
        "cleanup_days": cleanup_days,
        "check": check,
        "n_by_month": n_by_month,
        "points": points,
        "discards": discards,
        "resets": resets,
        "sources": {"transcripts": has_transcripts, "statusline": has_statusline},
    }
    write_aggregates(log_dir, aggregates)

    status = quota.status(aggregates, now)
    return {
        "cleanup_days": cleanup_days,
        "transcripts": index.files,
        "corrupt_lines": index.corrupt_lines + index.unreadable_files,
        "backfilled_lines": lines_in_window,
        "matches": dict(sorted(matches.items())),
        "check": check,
        "n_cases": sum(len(v) for g in n_by_month.values() for v in g.values()),
        "points": dict(Counter(f"{p['source']}:{p['type']}" for p in points)),
        "discards": discards,
        "quota": {t: e["status"] for t, e in status.items()},
        "resets": resets,
    }


# Rótulos para la terminal: el resumen lleva valores de máquina y la prosa los dice en palabras.
#: Estado de la cuota (`quota.status`).
_STATUS_LABEL = {"calibrated": "calibrada", "uncalibrated": "sin calibrar"}
#: Veredicto del cotejo.
_VERDICT_LABEL = {"pass": "pasa", "fail": "falla"}
#: Motivos de descarte de los puntos de cuota.
_DISCARD_LABEL = {
    "corrupt_line": "línea corrupta",
    "out_of_range": "fuera de rango",
    "small_delta": "variación pequeña",
    "no_local_use": "sin uso local",
    "contaminated": "contaminado",
    "overlapping": "solapado",
    "expired": "caducado",
    "reset": "reinicio",
}


def summary_text(r: dict) -> str:
    """El resumen para la terminal: conteos, nunca rutas."""
    lines = [
        f"Plazo de borrado de los transcripts: {r['cleanup_days']} días.",
        f"Transcripts leídos: {r['transcripts']} (líneas ilegibles: {r['corrupt_lines']}).",
        f"Líneas del log rellenadas: {r['backfilled_lines']} "
        + (
            "(" + ", ".join(f"{k}: {v}" for k, v in r["matches"].items()) + ")"
            if r["matches"]
            else "(ninguna)"
        )
        + ".",
        f"Casos de N en los agregados: {r['n_cases']}.",
    ]
    c = r.get("check")
    if c:
        verdict = c.get("verdict")
        lines.append(
            f"Cotejo de precios ({c.get('table_version')}): "
            f"{_VERDICT_LABEL.get(verdict, verdict)}; "
            f"{c.get('judged')} filas juzgadas, {c.get('outside')} fuera, "
            f"sin precio: {', '.join(c.get('unpriced') or []) or 'ninguno'}."
        )
    else:
        lines.append("Cotejo de precios: sin datos de coste en los transcripts.")
    for kind in quota.TYPES:
        d = r["discards"].get(kind) or {}
        lines.append(
            f"Cuota {kind}: {_STATUS_LABEL.get(r['quota'][kind], r['quota'][kind])}; puntos: "
            f"{r['points'].get('statusline:' + kind, 0)} del statusline, "
            f"{r['points'].get('rejection:' + kind, 0)} de rechazo; descartes: "
            + (", ".join(f"{_DISCARD_LABEL.get(k, k)} {v}" for k, v in d.items()) or "ninguno")
            + "."
        )
    return "\n".join(lines)
