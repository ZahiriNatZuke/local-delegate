"""El check `config.coste` de `doctor` (REQ-015, REQ-075).

Todo con un HOME, un log y unos agregados **sintéticos** en `tmp_path`. El probe se llama directo
con un `Context` cuyo `log_dir` apunta al log del test: los colaboradores de red no se tocan.
"""

from __future__ import annotations

import builtins
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from local_delegate import atribucion, checks, recalcular

TOOL = "local_summarize"


def _home(tmp_path: Path, *, projects: bool = True, cleanup: int | None = None) -> Path:
    """HOME con `~/.claude` y, si se pide, `projects/` con un transcript y `cleanupPeriodDays`."""
    home = tmp_path / "home"
    claude = home / ".claude"
    claude.mkdir(parents=True)
    if projects:
        proyecto = claude / "projects" / "D--algo"
        proyecto.mkdir(parents=True)
        (proyecto / "sesion.jsonl").write_text(
            json.dumps({"type": "assistant", "message": {"model": "claude-opus-5"}}) + "\n",
            encoding="utf-8",
        )
    if cleanup is not None:
        (claude / "settings.json").write_text(
            json.dumps({"cleanupPeriodDays": cleanup}), encoding="utf-8"
        )
    return home


def _ts(dias: float) -> str:
    return (datetime.now(UTC) - timedelta(days=dias)).isoformat(timespec="seconds")


def _log(log_dir: Path, *dias: float, client: str = "claude-code") -> list[dict]:
    """Una delegación por edad, cada una en el `usage-AAAAMM.jsonl` del mes de su `ts`."""
    log_dir.mkdir(parents=True, exist_ok=True)
    filas = []
    for d in dias:
        ts = _ts(d)
        fila = {
            "ts": ts,
            "tool": TOOL,
            "source": "path",
            "path": "notas.md",
            "client": client,
            "ok": True,
            "chars_in": 4000,
        }
        mes = ts[:4] + ts[5:7]
        with (log_dir / f"usage-{mes}.jsonl").open("a", encoding="utf-8") as flujo:
            flujo.write(json.dumps(fila) + "\n")
        filas.append(fila)
    return filas


def _cotejo(log_dir: Path, veredicto: str | None, *, sin_precio=(), fuera: int = 0) -> None:
    cotejo = None
    if veredicto is not None:
        cotejo = {
            "fecha": "2026-10-06T12:00:00+00:00",
            "version_tabla": "2026-10-06",
            "juzgadas": 142,
            "fuera": fuera,
            "sin_precio": list(sin_precio),
            "veredicto": veredicto,
        }
    recalcular.escribir_agregados(log_dir, {"version": 1, "plazo_dias": 30, "cotejo": cotejo})


def _probe(home: Path, log_dir: Path) -> checks.Result:
    return checks._probe_coste(checks.Context(home=home, log_dir=log_dir))


def test_comando_nunca_lanzado_y_pendientes_de_21_dias(tmp_path):
    """El escenario de la spec: sin `coste-agregados.json` y con `H` = 30, avisa a los 20 días."""
    log_dir = tmp_path / "log"
    _log(log_dir, 21)
    r = _probe(_home(tmp_path), log_dir)
    assert not recalcular.ruta(log_dir).exists()
    assert r.status == checks.WARN
    assert "recalcular-coste" in r.detail
    assert "hace 21 días" in r.detail
    assert r.fix_hint == "local-delegate recalcular-coste"

    # Con 10 días todavía hay margen: sin cotejo, `unknown`.
    log_corto = tmp_path / "log-corto"
    _log(log_corto, 10)
    assert _probe(tmp_path / "home", log_corto).status == checks.UNKNOWN


def test_el_aviso_sigue_al_plazo(tmp_path):
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


def test_las_dos_cosas_a_la_vez(tmp_path):
    """Relleno pendiente y cotejo fallido: gana el `warn` y el mensaje dice las dos cosas."""
    log_dir = tmp_path / "log"
    _log(log_dir, 21, 22)
    _cotejo(log_dir, "falla", sin_precio=["claude-opus-5"], fuera=3)
    r = _probe(_home(tmp_path), log_dir)
    assert r.status == checks.WARN
    assert "2 delegación(es) pendiente(s)" in r.detail
    assert "recalcular-coste" in r.detail
    assert "claude-opus-5" in r.detail
    assert "3 fila(s) fuera" in r.detail


def test_cotejo_bueno_ok_y_sin_cotejo_unknown(tmp_path):
    home = _home(tmp_path)

    bueno = tmp_path / "bueno"
    _cotejo(bueno, "pasa")
    r = _probe(home, bueno)
    assert r.status == checks.OK
    assert "142" in r.detail

    malo = tmp_path / "malo"
    _cotejo(malo, "falla", sin_precio=["claude-opus-5"])
    r = _probe(home, malo)
    assert r.status == checks.WARN
    assert "claude-opus-5" in r.detail
    assert "pendiente" not in r.detail

    # Sin fichero, y con el fichero pero `cotejo: null` (el comando no encontró `cost-state`).
    assert _probe(home, tmp_path / "vacio").status == checks.UNKNOWN
    nulo = tmp_path / "nulo"
    _cotejo(nulo, None)
    r = _probe(home, nulo)
    assert r.status == checks.UNKNOWN
    assert r.status != checks.MISSING

    # Un HOME sin `~/.claude/projects` no tiene transcripts que rellenar: el aviso no aplica.
    sin_projects = _home(tmp_path / "otra", projects=False)
    log_dir = tmp_path / "pendientes"
    _log(log_dir, 21)
    assert _probe(sin_projects, log_dir).status == checks.UNKNOWN
    # Guarda: el mismo log con `projects/` sí avisa, así que lo de arriba lo decide `projects/`.
    assert _probe(home, log_dir).status == checks.WARN


def test_lo_rellenado_y_lo_excluido_no_avisan(tmp_path):
    """Lee los `atribucion-*.json`: una línea ya rellenada no está pendiente; Codex no cuenta."""
    home = _home(tmp_path)
    log_dir = tmp_path / "log"
    (fila,) = _log(log_dir, 21)
    mes = fila["ts"][:4] + fila["ts"][5:7]
    (clave,) = atribucion.claves_del_fichero([fila])
    atribucion.escribir_relleno(
        log_dir,
        mes,
        {clave: {"caller_model": "claude-opus-5", "caller_kind": "main", "cruce": "ventana"}},
    )
    assert _probe(home, log_dir).status == checks.UNKNOWN

    codex = tmp_path / "codex"
    _log(codex, 21, client="codex-mcp-client")
    assert _probe(home, codex).status == checks.UNKNOWN


def test_doctor_no_lee_transcripts(tmp_path, monkeypatch):
    """REQ-073: con transcripts presentes, el probe no abre nada bajo `projects/`."""
    home = _home(tmp_path)
    log_dir = tmp_path / "log"
    _log(log_dir, 21)
    _cotejo(log_dir, "pasa")

    abiertos: list[Path] = []
    original = builtins.open

    def espia(fichero, *args, **kwargs):
        if isinstance(fichero, str | Path):
            abiertos.append(Path(fichero))
        return original(fichero, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", espia)
    monkeypatch.setattr(io, "open", espia)
    r = _probe(home, log_dir)

    projects = home / ".claude" / "projects"
    lecturas_en_projects = [p for p in abiertos if p.is_relative_to(projects)]
    # Guarda: el espía ve las lecturas del probe (el log de uso), o el assert de abajo no prueba nada.
    assert any(p.name.startswith("usage-") for p in abiertos)
    assert r.status == checks.WARN
    assert lecturas_en_projects == []
