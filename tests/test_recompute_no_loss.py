"""`recompute-cost` no pisa con menos lo que no pudo leer (SDD `recompute-cost-sin-perdida`).

El antivirus o el indexador de Windows se simulan como en la revisión del 2026-10-23: la apertura
del fichero falla con `PermissionError` las primeras N veces y luego se suelta. Todo en `tmp_path`.
"""

from __future__ import annotations

import json
import pathlib
from pathlib import Path

import pytest
from filelock import FileLock
from test_attribution import _old_backfill
from test_recompute import NOW, _delegation_with_n
from test_transcripts import log_line, subagent, write_log

from local_delegate import attribution, cli, config, i18n, json_state, recompute

MONTH = "202610"
OLD_ENTRIES = {f"k{i:02d}": {"match": "exact", "tool_use_id": f"toolu_{i:02d}"} for i in range(50)}


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    """Los reintentos no duermen en la suite."""
    monkeypatch.setattr(json_state, "_sleep", lambda _s: None, raising=False)


def _locked(monkeypatch, name: str, times: int | None) -> dict:
    """La apertura de `name` falla `times` veces (`None`: siempre). Devuelve el contador."""
    real_open = pathlib.Path.open
    seen = {"failed": 0}

    def fake_open(self, *args, **kwargs):
        if self.name == name and (times is None or seen["failed"] < times):
            seen["failed"] += 1
            raise PermissionError(13, "The process cannot access the file", str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "open", fake_open)
    return seen


def _backfill_with_50(log: Path) -> Path:
    log.mkdir(parents=True, exist_ok=True)
    attribution.write_backfill(log, MONTH, OLD_ENTRIES)
    path = attribution.backfill_path(log, MONTH)
    assert len(attribution.read_backfill(log, MONTH)) == 50  # guarda: el relleno previo está
    return path


# --- REQ-001 / REQ-002: el relleno del mes ---------------------------------------------------


def test_backfill_survives_a_transient_read_failure(tmp_path, monkeypatch):
    """Control: sin el arreglo el fichero queda solo con `toolu_new` (la evidencia de la tarjeta)."""
    path = _backfill_with_50(tmp_path)
    seen = _locked(monkeypatch, path.name, times=1)
    attribution.write_backfill(tmp_path, MONTH, {"new": {"match": "exact"}})
    monkeypatch.undo()
    assert seen["failed"] == 1, "guarda: la lectura llegó a fallar"
    assert len(attribution.read_backfill(tmp_path, MONTH)) == 51


def test_backfill_is_not_written_over_an_unreadable_file(tmp_path, monkeypatch):
    path = _backfill_with_50(tmp_path)
    before = path.read_bytes()
    seen = _locked(monkeypatch, path.name, times=None)
    with pytest.raises(json_state.UnreadableStateError):
        attribution.write_backfill(tmp_path, MONTH, {"new": {"match": "exact"}})
    monkeypatch.undo()
    assert seen["failed"] == json_state.READ_ATTEMPTS  # reintentó antes de rendirse
    assert path.read_bytes() == before


def test_an_unreadable_old_backfill_does_not_seed_a_partial_new_one(tmp_path, monkeypatch):
    """Sin el nuevo, el viejo es «lo que ya hay»: si no se lee, no se siembra el nuevo sin él."""
    old = _old_backfill(tmp_path, MONTH, OLD_ENTRIES)
    assert old == attribution.legacy_backfill_path(tmp_path, MONTH)  # guarda: el nombre viejo
    _locked(monkeypatch, old.name, times=None)
    with pytest.raises(json_state.UnreadableStateError):
        attribution.write_backfill(tmp_path, MONTH, {"new": {"match": "exact"}})
    monkeypatch.undo()
    assert not attribution.backfill_path(tmp_path, MONTH).exists()


def test_a_damaged_backfill_is_set_aside_before_being_replaced(tmp_path):
    path = attribution.backfill_path(tmp_path, MONTH)
    damaged = b'{"version": 1, "entries": {"k1": {"match": "ex'
    path.write_bytes(damaged)
    seen: list[Path] = []
    attribution.write_backfill(tmp_path, MONTH, {"new": {"match": "exact"}}, on_damaged=seen.append)
    copies = sorted(tmp_path.glob(f"{path.name}.damaged-*"))
    assert [c.read_bytes() for c in copies] == [damaged]
    assert seen == copies
    assert set(attribution.read_backfill(tmp_path, MONTH)) == {"new"}  # como hasta ahora


# --- REQ-003 / REQ-005: cost-aggregates.json en `run` ----------------------------------------


def _world(tmp_path) -> tuple[Path, Path]:
    claude, log = tmp_path / "claude", tmp_path / "log"
    _delegation_with_n(subagent(claude, "a1"), "toolu_nl", 3)
    write_log(log, [log_line(1, tool_use_id="toolu_nl")])
    return claude, log


def _aggregates_with_history(log: Path) -> bytes:
    recompute.write_aggregates(
        log,
        {
            "version": 1,
            "n_by_month": {"202608": {"claude-opus-5|main": [127]}},
            "resets": {"five_hour": "2026-10-01T00:00:00+00:00", "seven_day": None},
        },
    )
    return recompute.aggregates_path(log).read_bytes()


def test_run_survives_a_transient_aggregates_read_failure(tmp_path, monkeypatch):
    """Control: sin el arreglo se pierden el mes cerrado y el reinicio puesto a mano."""
    claude, log = _world(tmp_path)
    _aggregates_with_history(log)
    seen = _locked(monkeypatch, recompute.FILE_NAME, times=1)
    recompute.run(claude, log, now=NOW)
    monkeypatch.undo()
    assert seen["failed"] == 1, "guarda: la lectura llegó a fallar"
    aggregates = recompute.read_aggregates(log)
    assert aggregates["n_by_month"]["202608"] == {"claude-opus-5|main": [127]}
    assert aggregates["resets"]["five_hour"] == "2026-10-01T00:00:00+00:00"


def test_run_writes_nothing_if_the_aggregates_cannot_be_read(tmp_path, monkeypatch):
    claude, log = _world(tmp_path)
    before = _aggregates_with_history(log)
    _locked(monkeypatch, recompute.FILE_NAME, times=None)
    with pytest.raises(json_state.UnreadableStateError):
        recompute.run(claude, log, now=NOW)
    monkeypatch.undo()
    assert recompute.aggregates_path(log).read_bytes() == before
    assert list(log.glob("attribution-*.json")) == []  # ni el relleno


def test_a_damaged_aggregates_file_is_set_aside(tmp_path):
    claude, log = _world(tmp_path)
    log.mkdir(exist_ok=True)
    recompute.aggregates_path(log).write_bytes(b"{ esto no es JSON")
    summary = recompute.run(claude, log, now=NOW)
    copies = list(log.glob(f"{recompute.FILE_NAME}.damaged-*"))
    assert [c.read_bytes() for c in copies] == [b"{ esto no es JSON"]
    assert summary["set_aside"] == 1
    assert recompute.summary_text(summary).splitlines()[-1] == i18n.t(
        "cli.recompute_cost.summary.set_aside", n=i18n.format_number(1)
    )
    assert recompute.read_aggregates(log) is not None  # se reescribió entero, como hasta ahora


# --- REQ-004 / REQ-006: la CLI y el cerrojo --------------------------------------------------


def test_the_cli_says_it_could_not_read(tmp_path, monkeypatch, capsys):
    claude, log = _world(tmp_path)
    before = _aggregates_with_history(log)
    monkeypatch.setattr(config, "LOG_DIR", log)
    _locked(monkeypatch, recompute.FILE_NAME, times=None)
    try:
        code = cli.run(["recompute-cost", "--claude-dir", str(claude)])
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr().out
    monkeypatch.undo()
    assert code == 1
    assert recompute.FILE_NAME in out
    assert "leer" in out and "escribir" not in out
    assert str(tmp_path) not in out
    assert recompute.aggregates_path(log).read_bytes() == before


def test_a_second_run_waits_for_the_lock(tmp_path, monkeypatch, capsys):
    claude, log = _world(tmp_path)
    log.mkdir(exist_ok=True)
    monkeypatch.setattr(recompute, "LOCK_TIMEOUT_S", 0.05, raising=False)
    monkeypatch.setattr(config, "LOG_DIR", log)
    with FileLock(str(log / "recompute-cost.lock")):
        with pytest.raises(recompute.BusyError):
            recompute.run(claude, log, now=NOW)
        assert not recompute.aggregates_path(log).exists()
        try:
            code = cli.run(["recompute-cost", "--claude-dir", str(claude)])
        except SystemExit as e:
            code = e.code
        out = capsys.readouterr().out
    assert code == 1
    assert "recompute-cost" in out and "en curso" in out
    recompute.run(claude, log, now=NOW)  # suelto el cerrojo, corre
    assert recompute.aggregates_path(log).exists()


def test_a_backfill_with_the_wrong_shape_is_set_aside(tmp_path):
    """JSON válido sin la forma del relleno (una lista): dañado, igual que uno que no es JSON."""
    path = attribution.backfill_path(tmp_path, MONTH)
    path.write_text("[1, 2]", encoding="utf-8")
    attribution.write_backfill(tmp_path, MONTH, {"new": {"match": "exact"}})
    assert [c.read_text(encoding="utf-8") for c in tmp_path.glob(f"{path.name}.damaged-*")] == [
        "[1, 2]"
    ]


def test_a_failing_stat_does_not_seed_from_the_old_aggregates(tmp_path, monkeypatch):
    """Desde Python 3.13 `exists()` da `False` si `stat` falla: no por eso se siembra del viejo.

    Control: con `if not path.exists()` decidiendo, el mes cerrado del nuevo se pierde."""
    claude, log = _world(tmp_path)
    _aggregates_with_history(log)
    (log / recompute.OLD_FILE_NAME).write_text(json.dumps({"version": 1}), encoding="utf-8")
    real_exists = pathlib.Path.exists
    monkeypatch.setattr(
        pathlib.Path,
        "exists",
        lambda self, *a, **k: (
            False if self.name == recompute.FILE_NAME else real_exists(self, *a, **k)
        ),
    )
    recompute.run(claude, log, now=NOW)
    monkeypatch.undo()
    assert recompute.read_aggregates(log)["n_by_month"]["202608"] == {"claude-opus-5|main": [127]}


def test_the_lock_is_released_when_the_run_fails(tmp_path, monkeypatch):
    claude, log = _world(tmp_path)
    _aggregates_with_history(log)
    _locked(monkeypatch, recompute.FILE_NAME, times=None)
    with pytest.raises(json_state.UnreadableStateError):
        recompute.run(claude, log, now=NOW)
    monkeypatch.undo()
    monkeypatch.setattr(recompute, "LOCK_TIMEOUT_S", 0.05)
    recompute.run(claude, log, now=NOW)  # no queda el cerrojo tomado
