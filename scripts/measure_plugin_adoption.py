"""Medición fijada antes de la 0.40.0 (REQ-024 de `claude-plugin-and-mods`).

Mide el % de sesiones interactivas de Claude Code con al menos una delegación **decidida por el
modelo**, y compara la base (desde el 2026-10-08 hasta la instalación) con los 14 días siguientes.

Cuenta por `tool_use_id`, sin depender del prefijo de las tools: una fila del log de uso cuenta si
su `tool_use_id` aparece en el transcript principal de una sesión. No cuentan:

- las llamadas del mod (`toolu_plugin_…`, `attribution.is_mod_call`, REQ-015);
- las pruebas: la regla común (`attribution.test_reason`) y las ventanas de
  `local-delegate test-window`;
- los subagentes: solo se mira el transcript principal (`<proyecto>/<sesión>.jsonl`), nunca
  `<sesión>/subagents/`, ni las filas que el relleno marcó `caller_kind: subagent`;
- las sesiones `-p` y del SDK (`entrypoint` `sdk-cli`): solo son interactivas `cli` y
  `claude-desktop` (la pestaña Code de Claude Desktop);
- por defecto (`--exclude-self`), las sesiones cuyo directorio de proyecto es el propio repo
  (`hook_common.project_kind_of`), que salen en `excluded_self_sessions`. `--include-self` las
  cuenta: es la cifra comparable con los cortes anteriores.

Aparte de `pct`, que sigue saliendo solo del hilo principal, cada periodo da las otras dos
columnas: `with_subagent_delegation` (el `tool_use_id` aparece en un transcript de
`<sesión>/subagents/`) y `with_mod_delegation` (una fila del mod con la `caller_session_key` de la
sesión), y `delegations_by_caller` (`attribution.caller_column`).

La base empieza el 2026-10-08 (`BASE_START`): antes faltan los `tool_use_id`. Una sesión cae en el
periodo de su primer `timestamp`.

Criterio fijado antes (REQ-024): éxito si, a los 14 días de instalar, el después tiene ≥ 30
sesiones y sube ≥ 10 puntos sobre la base. El script lo imprime con su estado (`status`:
`no_install`, `too_early`, `too_few_sessions`, `met`, `not_met`).

Solo imprime cifras, en JSON. El contenido de los transcripts no sale del proceso, y no escribe en
ningún sitio: lee el `LOG_DIR` y `~/.claude/projects`.

Uso:  uv run python scripts/measure_plugin_adoption.py [--install 2026-10-21T20:00:00Z]
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from local_delegate import attribution, config, cost, i18n, test_windows
from local_delegate.resources.hooks import hook_common

#: Desde aquí hay `tool_use_id` en el log de uso (REQ-024).
BASE_START = datetime(2026, 10, 8, tzinfo=UTC)

#: Los únicos `entrypoint` interactivos de Claude Code.
INTERACTIVE_ENTRY_POINTS = frozenset({"cli", "claude-desktop"})

#: Criterio fijado antes de medir (REQ-024).
MIN_DELTA_POINTS = 10
MIN_SESSIONS = 30
DAYS_AFTER = 14

CLAUDE_CODE = "claude-code"
TOOLU = re.compile(r"toolu_[A-Za-z0-9_]+")
#: Cuántas líneas del principio se leen para el `entrypoint` y el primer `timestamp`.
HEAD_LINES = 30
_END_OF_TIME = datetime.max.replace(tzinfo=UTC)

#: The columns of `delegations_by_caller`, in the order of `attribution.caller_column`.
CALLER_COLUMNS = ("main", "subagent", "mod", "unknown")
#: `exclusion` reasons of a row that is still a Claude Code delegation out of the tests: the
#: mod, the subagents and the rows without `tool_use_id` count in `delegations_by_caller`.
DELEGATION_REASONS = frozenset({None, "plugin", "subagent", "no_tool_use_id"})


def load_rows(log_dir: Path) -> list[dict]:
    """Las filas de `usage-AAAAMM.jsonl`, cada una con su entrada del relleno en `_bf`."""
    rows: list[dict] = []
    for f in sorted(Path(log_dir).glob("usage-*.jsonl")):
        month = f.stem.split("-")[1]
        file_rows = []
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                file_rows.append(row)
        entries = attribution.read_backfill(Path(log_dir), month)
        for key, row in zip(attribution.file_keys(file_rows), file_rows, strict=True):
            row["_bf"] = entries.get(key)
            rows.append(row)
    return rows


def _instant(value: object) -> datetime | None:
    try:
        return test_windows.parse_instant(value)
    except (ValueError, TypeError):
        return None


def exclusion(row: dict, windows: test_windows.Windows) -> str | None:
    """Por qué la fila no es una delegación decidida por el modelo en Claude Code, o `None`."""
    bf = row.get("_bf")
    reason = attribution.test_reason(row, bf)
    if reason:
        return reason
    if windows.find(row.get("ts")):
        return "test_window"
    if str(row.get("client") or "") != CLAUDE_CODE:
        return "other_client"
    if attribution.is_mod_call(row):
        return "plugin"
    tool_use_id = row.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not tool_use_id:
        return "no_tool_use_id"
    caller = row.get("caller_kind") or (bf.get("caller_kind") if isinstance(bf, dict) else None)
    if caller == "subagent":
        return "subagent"
    return None


def model_decided_ids(
    rows: Sequence[dict], windows: test_windows.Windows, since: datetime, until: datetime
) -> tuple[set[str], collections.Counter]:
    """Los `tool_use_id` que cuentan en `[since, until)` y los motivos de las filas que no."""
    ids: set[str] = set()
    excluded: collections.Counter = collections.Counter()
    for row in rows:
        ts = _instant(row.get("ts"))
        if ts is None or not since <= ts < until:
            continue
        reason = exclusion(row, windows)
        if reason:
            excluded[reason] += 1
        else:
            ids.add(row["tool_use_id"])
    return ids, excluded


def _backfilled(row: dict, field: str) -> object:
    bf = row.get("_bf")
    return row.get(field) or (bf.get(field) if isinstance(bf, dict) else None)


def thread_marks(
    rows: Sequence[dict], windows: test_windows.Windows, since: datetime, until: datetime
) -> tuple[set[str], set[str]]:
    """What the other two columns look for in `[since, until)`: the `tool_use_id` a subagent
    transcript may hold (the model's rows, the subagent ones included) and the
    `caller_session_key` of the mod's rows."""
    subagent_ids: set[str] = set()
    mod_keys: set[str] = set()
    for row in rows:
        ts = _instant(row.get("ts"))
        if ts is None or not since <= ts < until:
            continue
        reason = exclusion(row, windows)
        if reason in (None, "subagent"):
            subagent_ids.add(row["tool_use_id"])
        elif reason == "plugin":
            key = _backfilled(row, "caller_session_key")
            if isinstance(key, str) and key:
                mod_keys.add(key)
    return subagent_ids, mod_keys


def delegations_by_caller(
    rows: Sequence[dict],
    windows: test_windows.Windows,
    since: datetime,
    until: datetime,
    *,
    include_self: bool,
) -> dict:
    """The Claude Code delegations of `[since, until)` out of the tests, by
    `attribution.caller_column` over the merged row; without the repo's own unless
    `include_self`."""
    counts: collections.Counter = collections.Counter()
    for row in rows:
        ts = _instant(row.get("ts"))
        if ts is None or not since <= ts < until:
            continue
        if exclusion(row, windows) not in DELEGATION_REASONS:
            continue
        merged = cost.merge_row(row, row.get("_bf"))
        if not include_self and attribution.project_kind(merged) == "self":
            continue
        counts[attribution.caller_column(merged)] += 1
    return {column: counts[column] for column in CALLER_COLUMNS}


def session_kind(transcript: Path, log_dir: Path) -> str:
    """`self` or `other`: the kind of the session's project directory (`LOG_DIR` gives the list)."""
    return hook_common.project_kind_of(transcript.parent.name, directory=Path(log_dir))


def _holds_any(path: Path, ids: set[str]) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return not ids.isdisjoint(TOOLU.findall(text))


def subagent_delegated(transcript: Path, ids: set[str]) -> bool:
    """Whether a transcript of `<session>/subagents/` holds one of `ids`."""
    if not ids:
        return False
    folder = transcript.parent / transcript.stem / "subagents"
    return any(_holds_any(path, ids) for path in sorted(folder.glob("*.jsonl")))


def _head(path: Path) -> tuple[str | None, datetime | None]:
    """(`entrypoint`, primer `timestamp`) de un transcript, o `None` en lo que falte."""
    entrypoint: str | None = None
    start: datetime | None = None
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for _ in range(HEAD_LINES):
                line = fh.readline()
                if not line:
                    break
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                if entrypoint is None and data.get("entrypoint"):
                    entrypoint = str(data["entrypoint"])
                if start is None and data.get("timestamp"):
                    start = _instant(data["timestamp"])
                if entrypoint and start:
                    break
    except OSError:
        # Un transcript que no se puede leer no es una sesión que se pueda medir.
        return None, None
    return entrypoint, start


def sessions(projects: Path, since: datetime, until: datetime) -> list[tuple[Path, str]]:
    """(transcript principal, entrypoint) de las sesiones interactivas que empiezan en el rango.

    Solo `<proyecto>/<sesión>.jsonl`: los de `<sesión>/subagents/` son de subagentes.
    """
    found: list[tuple[Path, str]] = []
    for path in sorted(Path(projects).glob("*/*.jsonl")):
        try:
            if path.stat().st_mtime < since.timestamp():
                continue  # nadie lo tocó después del comienzo: no puede empezar dentro
        except OSError:
            continue
        entrypoint, start = _head(path)
        if entrypoint in INTERACTIVE_ENTRY_POINTS and start is not None and since <= start < until:
            found.append((path, entrypoint))
    return found


def measure(
    log_dir: Path,
    projects: Path,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    rows: Sequence[dict] | None = None,
    include_self: bool = False,
) -> dict:
    """Las cifras de un periodo. `since` nunca baja de `BASE_START`."""
    since = max(since or BASE_START, BASE_START)
    until = until or datetime.now(UTC)
    if rows is None:
        rows = load_rows(log_dir)
    windows = test_windows.load(Path(log_dir))
    # Las delegaciones se buscan desde el comienzo y sin final: una sesión del último día puede
    # delegar después del corte, y sigue siendo una sesión de este periodo.
    ids, _ = model_decided_ids(rows, windows, since, _END_OF_TIME)
    # Las exclusiones, en cambio, son las del periodo: sin final, el periodo base contaba las filas
    # del mod de después de instalarlo (#597).
    _, excluded = model_decided_ids(rows, windows, since, until)
    # The other two columns look, like `ids`, from the start and with no end.
    subagent_ids, mod_keys = thread_marks(rows, windows, since, _END_OF_TIME)
    total = 0
    hit = 0
    subagent_hit = 0
    mod_hit = 0
    excluded_self = 0
    found_ids: set[str] = set()
    by_entrypoint: collections.Counter = collections.Counter()
    hit_by_entrypoint: collections.Counter = collections.Counter()
    for path, entrypoint in sessions(projects, since, until):
        if not include_self and session_kind(path, log_dir) == "self":
            excluded_self += 1
            continue
        total += 1
        by_entrypoint[entrypoint] += 1
        if subagent_delegated(path, subagent_ids):
            subagent_hit += 1
        if mod_keys and hook_common.session_key(path.stem) in mod_keys:
            mod_hit += 1
        if not ids:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        matched = ids.intersection(TOOLU.findall(text))
        if matched:
            hit += 1
            hit_by_entrypoint[entrypoint] += 1
            found_ids |= matched
    return {
        "since": since.isoformat(timespec="seconds"),
        "until": until.isoformat(timespec="seconds"),
        "sessions": total,
        "with_delegation": hit,
        "pct": round(hit / total * 100, 1) if total else None,
        "counted_delegations": len(found_ids),
        # Las del log que cuentan; las que no salen en ningún transcript del periodo, no suman.
        "model_decided_ids": len(ids),
        "sessions_by_entrypoint": dict(sorted(by_entrypoint.items())),
        "with_delegation_by_entrypoint": dict(sorted(hit_by_entrypoint.items())),
        "excluded_rows": dict(sorted(excluded.items())),
        "excluded_self_sessions": excluded_self,
        "with_subagent_delegation": subagent_hit,
        "with_mod_delegation": mod_hit,
        "delegations_by_caller": delegations_by_caller(
            rows, windows, since, until, include_self=include_self
        ),
    }


def criterion(base: dict, after: dict | None, install: datetime | None, now: datetime) -> dict:
    """El criterio fijado antes (REQ-024) y en qué estado está."""
    out: dict = {
        "min_delta_points": MIN_DELTA_POINTS,
        "min_sessions": MIN_SESSIONS,
        "days": DAYS_AFTER,
        "due": None,
        "delta_points": None,
        "status": "no_install",
    }
    if install is None or after is None:
        return out
    due = install + timedelta(days=DAYS_AFTER)
    out["due"] = due.isoformat(timespec="seconds")
    if base["pct"] is not None and after["pct"] is not None:
        out["delta_points"] = round(after["pct"] - base["pct"], 1)
    if now < due:
        out["status"] = "too_early"
    elif after["sessions"] < MIN_SESSIONS:
        out["status"] = "too_few_sessions"
    elif out["delta_points"] is not None and out["delta_points"] >= MIN_DELTA_POINTS:
        out["status"] = "met"
    else:
        out["status"] = "not_met"
    return out


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log-dir", type=Path, default=Path(config.LOG_DIR))
    ap.add_argument("--projects", type=Path, default=Path.home() / ".claude" / "projects")
    ap.add_argument("--install", help="install instant of 0.40.0 (ISO 8601)")
    ap.add_argument("--since", help="start of the base; never before 2026-10-08")
    ap.add_argument("--now", help="the measurement's 'now' (ISO 8601); the real one by default")
    own = ap.add_mutually_exclusive_group()
    own.add_argument(
        "--exclude-self",
        dest="include_self",
        action="store_false",
        help=i18n.t("cli.script.measure_plugin_adoption.help.exclude_self"),
    )
    own.add_argument(
        "--include-self",
        dest="include_self",
        action="store_true",
        help=i18n.t("cli.script.measure_plugin_adoption.help.include_self"),
    )
    ap.set_defaults(include_self=False)
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    now = test_windows.parse_instant(args.now) if args.now else datetime.now(UTC)
    since = test_windows.parse_instant(args.since) if args.since else BASE_START
    install = test_windows.parse_instant(args.install) if args.install else None
    rows = load_rows(args.log_dir)
    base_until = min(install, now) if install else now
    own = {"include_self": args.include_self}
    base = measure(args.log_dir, args.projects, since=since, until=base_until, rows=rows, **own)
    after = None
    if install is not None:
        after_until = min(install + timedelta(days=DAYS_AFTER), now)
        after = measure(
            args.log_dir, args.projects, since=install, until=after_until, rows=rows, **own
        )
    report = {
        "include_self": args.include_self,
        "base": base,
        "after": after,
        "criterion": criterion(base, after, install, now),
    }
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
