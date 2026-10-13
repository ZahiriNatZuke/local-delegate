"""Ola A2 del renombrado: nombres en disco, interruptor y `deprecated_names` de los hooks.

Los hooks escriben solo los nombres nuevos (`local-delegate-blocks.jsonl`, `local-delegate-calls/`,
`local-delegate-health-*.json`, `~/.claude/local-delegate-block-off`) y el daemon sigue leyendo
los viejos, porque un hook de una versión anterior puede seguir instalado y escribiendo (REQ-005,
REQ-006, REQ-012). Con la telemetría encendida, cada evento dice qué nombres viejos leyó la
invocación, y `doctor` lo cuenta desde la cola del fichero (REQ-003).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from local_delegate import attribution, checks, config, deprecations, legacy_names, server
from local_delegate import install as inst
from local_delegate.resources.hooks import hook_common

OLD_SWITCH, NEW_SWITCH = hook_common.FILE_NAMES["switch_file"]


@pytest.fixture
def temp_dir(tmp_path, monkeypatch):
    """El temporal del usuario, que comparten el hook y el daemon, apuntando a `tmp_path`."""
    dest = tmp_path / "temp"
    dest.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(dest))
    return dest


@pytest.fixture
def home_env(tmp_path, monkeypatch):
    """Un HOME de prueba sin interruptor configurado y con el bloqueo encendido por variable."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    for name in (
        "LD_HOOK_READ_SWITCH_FILE",
        "LD_HOOK_READ_INTERRUPTOR",
        "LD_HOOK_READ_BLOQUEAR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1")
    hook_common.DEPRECATED_SEEN.clear()
    yield home
    hook_common.DEPRECATED_SEEN.clear()


# --- Una sola tabla ---------------------------------------------------------------------------


def test_the_file_table_is_the_same_in_the_hooks_and_in_the_package():
    """Los hooks no importan el paquete y llevan su copia: si divergen, uno escribe donde el otro
    no lee."""
    assert hook_common.FILE_NAMES == legacy_names.FILE_NAMES


def test_the_old_switch_is_in_the_registry_and_in_the_hooks_copy():
    entry = deprecations.find(OLD_SWITCH)
    assert entry is not None and entry.kind == "switch_file" and entry.new == NEW_SWITCH
    assert ("switch_file", OLD_SWITCH, NEW_SWITCH) in hook_common.DEPRECATED_HOOK_NAMES


# --- Temporales: escribe el nuevo, lee los dos ----------------------------------------------


def test_the_daemon_reads_the_block_notes_of_an_old_hook(temp_dir, tmp_path):
    """Un hook de la 0.34.0 sigue escribiendo `local-delegate-bloqueos.jsonl`: el bloqueo que
    provocó tiene que seguir contando como aceptado cuando el agente delega."""
    document = tmp_path / "informe.md"
    old = temp_dir / "local-delegate-bloqueos.jsonl"
    note = {"id": "viejo1234567", "sha": hook_common.path_digest(str(document)), "ts": time.time()}
    old.write_text(json.dumps(note) + "\n", encoding="utf-8")

    assert server._recent_block_id(str(document)) == "viejo1234567"


def test_the_hook_writes_the_notes_only_under_the_new_name_and_the_most_recent_wins(
    temp_dir, tmp_path
):
    document = tmp_path / "informe.md"
    old = temp_dir / "local-delegate-bloqueos.jsonl"
    older = {
        "id": "viejo1234567",
        "sha": hook_common.path_digest(str(document)),
        "ts": time.time() - 30,
    }
    old.write_text(json.dumps(older) + "\n", encoding="utf-8")

    hook_common.record_block("nuevo1234567", str(document))

    assert (temp_dir / "local-delegate-blocks.jsonl").is_file()
    assert old.read_text(encoding="utf-8").count("\n") == 1, "el fichero viejo no se toca"
    assert server._recent_block_id(str(document)) == "nuevo1234567"


def test_the_attribution_note_of_an_old_hook_is_still_found(temp_dir):
    old = temp_dir / "local-delegate-llamadas"
    old.mkdir()
    note = {"tool_use_id": "toolu_viejo", "ts": time.time(), "agent_type": "general-purpose"}
    (old / "toolu_viejo.json").write_text(json.dumps(note), encoding="utf-8")

    assert attribution.read_note("toolu_viejo") == note

    assert hook_common.record_call({"tool_use_id": "toolu_nuevo", "agent_type": "Explore"})
    assert (temp_dir / "local-delegate-calls" / "toolu_nuevo.json").is_file()
    assert not (old / "toolu_nuevo.json").exists()
    assert attribution.read_note("toolu_nuevo")["agent_type"] == "Explore"


def test_the_health_mark_uses_the_new_name(temp_dir, monkeypatch):
    monkeypatch.setattr(hook_common, "_probe", lambda _timeout: True)

    assert hook_common.backend_available() is True

    names = sorted(p.name for p in temp_dir.iterdir())
    assert len(names) == 1 and names[0].startswith("local-delegate-health-"), names


# --- El interruptor -------------------------------------------------------------------------


def test_the_old_switch_still_turns_off_and_is_noted(home_env):
    (home_env / ".claude" / OLD_SWITCH).write_text("", encoding="utf-8")

    assert hook_common.block_state() == "off_file"
    assert OLD_SWITCH in hook_common.DEPRECATED_SEEN


def test_the_new_switch_turns_off_without_warning(home_env):
    (home_env / ".claude" / NEW_SWITCH).write_text("", encoding="utf-8")

    assert hook_common.block_state() == "off_file"
    assert hook_common.DEPRECATED_SEEN == set()


def test_without_a_switch_the_variable_rules(home_env):
    """Control de los dos anteriores: sin ningún fichero, el bloqueo está encendido."""
    assert hook_common.block_state() == "on"
    assert hook_common.DEPRECATED_SEEN == set()


# --- `deprecated_names` en la telemetría, con el hook INSTALADO --------------------------------


def _run_installed_hook(home: Path, variables: dict[str, str]) -> subprocess.CompletedProcess:
    inst.apply(
        inst.plan_install(
            inst.Options(
                home=home,
                components={"hooks"},
                targets={"claude"},
                python_exe="python3",
                use_cli=False,
            )
        ),
        dry_run=False,
        out=lambda *_a: None,
    )
    hooks_dir = home / ".claude" / "hooks" / inst.HOOKS_SUBDIR
    to_remove = {
        "LD_HOOK_READ_BLOCK",
        "LD_HOOK_READ_BLOQUEAR",
        "LD_HOOK_READ_SWITCH_FILE",
        "LD_HOOK_READ_INTERRUPTOR",
        "LD_HOOK_TELEMETRY_LOG",
    }
    env = {k: v for k, v in os.environ.items() if k not in to_remove}
    env.update({"HOME": str(home), "USERPROFILE": str(home), **variables})
    proc = subprocess.run(
        [sys.executable, str(hooks_dir / "suggest_delegate_prompt.py")],
        input=json.dumps({"prompt": "Hola", "session_id": "s-a2"}),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc


def _last_event(log: Path) -> dict:
    return json.loads(log.read_text(encoding="utf-8").splitlines()[-1])


def test_the_event_says_which_old_names_the_hook_read(tmp_path):
    log = tmp_path / "telemetry.jsonl"
    _run_installed_hook(tmp_path, {"LD_HOOK_READ_BLOQUEAR": "1", "LD_HOOK_TELEMETRY_LOG": str(log)})

    event = _last_event(log)
    assert event["block"] == "on"
    assert event["deprecated_names"] == ["LD_HOOK_READ_BLOQUEAR"]


def test_the_old_switch_also_travels_in_the_event(tmp_path):
    log = tmp_path / "telemetry.jsonl"
    (tmp_path / ".claude").mkdir(exist_ok=True)
    (tmp_path / ".claude" / OLD_SWITCH).write_text("", encoding="utf-8")
    _run_installed_hook(tmp_path, {"LD_HOOK_READ_BLOCK": "1", "LD_HOOK_TELEMETRY_LOG": str(log)})

    event = _last_event(log)
    assert event["block"] == "off_file"
    assert event["deprecated_names"] == [OLD_SWITCH]


def test_with_new_names_the_event_does_not_carry_the_key(tmp_path):
    """Control: la clave solo aparece cuando se leyó algo viejo."""
    log = tmp_path / "telemetry.jsonl"
    _run_installed_hook(tmp_path, {"LD_HOOK_READ_BLOCK": "1", "LD_HOOK_TELEMETRY_LOG": str(log)})

    event = _last_event(log)
    assert event["block"] == "on"
    assert "deprecated_names" not in event


def test_without_telemetry_nothing_is_written(tmp_path):
    _run_installed_hook(tmp_path, {"LD_HOOK_READ_BLOQUEAR": "1"})

    assert not list(tmp_path.glob("**/*.jsonl")), "sin LD_HOOK_TELEMETRY_LOG no hay evento"


# --- `doctor` lee la cola de la telemetría ---------------------------------------------------


def _event(when: datetime, names: list[str] | None = None) -> dict:
    row: dict = {"ts": when.isoformat(), "event": "UserPromptSubmit", "block": "on"}
    if names:
        row["deprecated_names"] = names
    return row


def _write_telemetry(path: Path, rows: list[dict], padding: int = 0) -> None:
    lines = [json.dumps(f) for f in rows]
    # Relleno de eventos viejos al principio: obliga a leer por bloques desde el final.
    old = json.dumps(_event(datetime.now(UTC) - timedelta(days=60)))
    path.write_text("\n".join([old] * padding + lines) + "\n", encoding="utf-8")


def test_the_7_day_tail_gives_the_names_and_looks_no_further_back(tmp_path):
    now = datetime.now(UTC)
    log = tmp_path / "telemetry.jsonl"
    _write_telemetry(
        log,
        [
            _event(now - timedelta(days=9), ["LD_HOOK_READ_INTERRUPTOR"]),
            _event(now - timedelta(days=2), ["LD_HOOK_READ_BLOQUEAR"]),
            _event(now - timedelta(hours=1)),
            _event(now, [OLD_SWITCH]),
        ],
        padding=3000,
    )
    assert log.stat().st_size > 2 * checks._TAIL_BLOCK, "el caso tiene que cruzar bloques"

    names = checks.deprecated_names_in_hook_telemetry(log, now=now)

    assert names == {"LD_HOOK_READ_BLOQUEAR", OLD_SWITCH}


def test_doctor_warns_about_what_the_hooks_read(tmp_path, monkeypatch):
    log = tmp_path / "telemetry.jsonl"
    _write_telemetry(log, [_event(datetime.now(UTC), ["LD_HOOK_READ_BLOQUEAR"])])
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)
    for name in config.DEPRECATED_ENV_VALUES:
        monkeypatch.setitem(config.DEPRECATED_ENV_VALUES, name, None)
    ctx = checks.Context(home=tmp_path)

    result = checks._probe_deprecated_names(ctx)

    assert result.status == checks.WARN
    assert "leído por los hooks" in result.detail
    assert "LD_HOOK_READ_BLOQUEAR está obsoleto: usa LD_HOOK_READ_BLOCK" in result.detail


def test_doctor_warns_about_the_old_switch_in_claude(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", None)
    for name in config.DEPRECATED_ENV_VALUES:
        monkeypatch.setitem(config.DEPRECATED_ENV_VALUES, name, None)
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / OLD_SWITCH).write_text("", encoding="utf-8")

    result = checks._probe_deprecated_names(checks.Context(home=tmp_path))

    assert result.status == checks.WARN
    assert f"renombra {OLD_SWITCH} a {NEW_SWITCH}" in result.fix_hint
