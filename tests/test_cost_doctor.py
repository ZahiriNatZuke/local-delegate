"""El check `config.cost` de `doctor` (REQ-015, REQ-075).

Todo con un HOME, un log y unos agregados **sintéticos** en `tmp_path`. El probe se llama directo
con un `Context` cuyo `log_dir` apunta al log del test: los colaboradores de red no se tocan.
"""

from __future__ import annotations

import builtins
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from local_delegate import attribution, checks, recompute

TOOL = "local_summarize"


def _home(tmp_path: Path, *, projects: bool = True, cleanup: int | None = None) -> Path:
    """HOME con `~/.claude` y, si se pide, `projects/` con un transcript y `cleanupPeriodDays`."""
    home = tmp_path / "home"
    claude = home / ".claude"
    claude.mkdir(parents=True)
    if projects:
        project = claude / "projects" / "D--algo"
        project.mkdir(parents=True)
        (project / "sesion.jsonl").write_text(
            json.dumps({"type": "assistant", "message": {"model": "claude-opus-5"}}) + "\n",
            encoding="utf-8",
        )
    if cleanup is not None:
        (claude / "settings.json").write_text(
            json.dumps({"cleanupPeriodDays": cleanup}), encoding="utf-8"
        )
    return home


def _ts(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")


def _log(log_dir: Path, *days: float, client: str = "claude-code") -> list[dict]:
    """Una delegación por edad, cada una en el `usage-AAAAMM.jsonl` del mes de su `ts`."""
    log_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in days:
        ts = _ts(d)
        row = {
            "ts": ts,
            "tool": TOOL,
            "source": "path",
            "path": "notas.md",
            "client": client,
            "ok": True,
            "chars_in": 4000,
        }
        month = ts[:4] + ts[5:7]
        with (log_dir / f"usage-{month}.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")
        rows.append(row)
    return rows


def _crosscheck(log_dir: Path, verdict: str | None, *, unpriced=(), outside: int = 0) -> None:
    crosscheck = None
    if verdict is not None:
        crosscheck = {
            "date": "2026-10-06T12:00:00+00:00",
            "table_version": "2026-10-06",
            "judged": 142,
            "outside": outside,
            "unpriced": list(unpriced),
            "verdict": verdict,
        }
    recompute.write_aggregates(log_dir, {"version": 1, "cleanup_days": 30, "check": crosscheck})


def _probe(home: Path, log_dir: Path) -> checks.Result:
    return checks._probe_cost(checks.Context(home=home, log_dir=log_dir))


def test_command_never_run_and_21_days_pending(tmp_path):
    """El escenario de la spec: sin `cost-aggregates.json` y con `H` = 30, avisa a los 20 días."""
    log_dir = tmp_path / "log"
    _log(log_dir, 21)
    r = _probe(_home(tmp_path), log_dir)
    assert not recompute.aggregates_path(log_dir).exists()
    assert r.status == checks.WARN
    assert "recompute-cost" in r.detail
    assert "hace 21 días" in r.detail
    assert r.fix_hint == "local-delegate recompute-cost"

    # Con 10 días todavía hay margen: sin cotejo, `unknown`.
    short_log = tmp_path / "log-corto"
    _log(short_log, 10)
    assert _probe(tmp_path / "home", short_log).status == checks.UNKNOWN


def test_the_warning_follows_the_deadline(tmp_path):
    """`H` sale de `cleanupPeriodDays`: con 90, 21 días no avisan y 81 sí."""
    home = _home(tmp_path, cleanup=90)
    log_21 = tmp_path / "log21"
    _log(log_21, 21)
    r = _probe(home, log_21)
    assert r.status == checks.UNKNOWN

    log_81 = tmp_path / "log81"
    _log(log_81, 81)
    r = _probe(home, log_81)
    assert r.status == checks.WARN
    assert "a los 90" in r.detail


def test_both_things_at_once(tmp_path):
    """Relleno pendiente y cotejo fallido: gana el `warn` y el mensaje dice las dos cosas."""
    log_dir = tmp_path / "log"
    _log(log_dir, 21, 22)
    _crosscheck(log_dir, "fail", unpriced=["claude-opus-5"], outside=3)
    r = _probe(_home(tmp_path), log_dir)
    assert r.status == checks.WARN
    assert "2 delegación(es) pendiente(s)" in r.detail
    assert "recompute-cost" in r.detail
    assert "claude-opus-5" in r.detail
    assert "3 fila(s) fuera" in r.detail


def test_good_crosscheck_ok_and_no_crosscheck_unknown(tmp_path):
    home = _home(tmp_path)

    good = tmp_path / "bueno"
    _crosscheck(good, "pass")
    r = _probe(home, good)
    assert r.status == checks.OK
    assert "142" in r.detail

    bad = tmp_path / "malo"
    _crosscheck(bad, "fail", unpriced=["claude-opus-5"])
    r = _probe(home, bad)
    assert r.status == checks.WARN
    assert "claude-opus-5" in r.detail
    assert "pendiente" not in r.detail

    # Sin fichero, y con el fichero pero `check: null` (el comando no encontró `cost-state`).
    assert _probe(home, tmp_path / "vacio").status == checks.UNKNOWN
    null = tmp_path / "nulo"
    _crosscheck(null, None)
    r = _probe(home, null)
    assert r.status == checks.UNKNOWN
    assert r.status != checks.MISSING

    # Un HOME sin `~/.claude/projects` no tiene transcripts que rellenar: el aviso no aplica.
    without_projects = _home(tmp_path / "otra", projects=False)
    log_dir = tmp_path / "pendientes"
    _log(log_dir, 21)
    assert _probe(without_projects, log_dir).status == checks.UNKNOWN
    # Guarda: el mismo log con `projects/` sí avisa, así que lo de arriba lo decide `projects/`.
    assert _probe(home, log_dir).status == checks.WARN


def test_backfilled_and_excluded_do_not_warn(tmp_path):
    """Lee los `attribution-*.json`: una línea ya rellenada no está pendiente; Codex no cuenta."""
    home = _home(tmp_path)
    log_dir = tmp_path / "log"
    (row,) = _log(log_dir, 21)
    month = row["ts"][:4] + row["ts"][5:7]
    (key,) = attribution.file_keys([row])
    attribution.write_backfill(
        log_dir,
        month,
        {key: {"caller_model": "claude-opus-5", "caller_kind": "main", "match": "window"}},
    )
    assert _probe(home, log_dir).status == checks.UNKNOWN

    codex = tmp_path / "codex"
    _log(codex, 21, client="codex-mcp-client")
    assert _probe(home, codex).status == checks.UNKNOWN


def test_doctor_does_not_read_transcripts(tmp_path, monkeypatch):
    """REQ-073: con transcripts presentes, el probe no abre nada bajo `projects/`."""
    home = _home(tmp_path)
    log_dir = tmp_path / "log"
    _log(log_dir, 21)
    _crosscheck(log_dir, "pass")

    opened: list[Path] = []
    original = builtins.open

    def spy(file, *args, **kwargs):
        if isinstance(file, str | Path):
            opened.append(Path(file))
        return original(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    r = _probe(home, log_dir)

    projects = home / ".claude" / "projects"
    reads_in_projects = [p for p in opened if p.is_relative_to(projects)]
    # Guarda: el espía ve las lecturas del probe (el log de uso), o el assert de abajo no prueba nada.
    assert any(p.name.startswith("usage-") for p in opened)
    assert r.status == checks.WARN
    assert reads_in_projects == []
