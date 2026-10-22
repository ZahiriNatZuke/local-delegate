"""Nombres en disco y del bloqueo en los hooks (ola A2 del renombrado; retirada en la 0.38.0).

Los hooks escriben solo los nombres nuevos (`local-delegate-blocks.jsonl`, `local-delegate-calls/`,
`local-delegate-health-*.json`) y el daemon sigue leyendo los temporales viejos, porque un hook de
una versión anterior puede seguir instalado y escribiendo (REQ-007 de retire-legacy-aliases).

Desde la 0.38.0 los hooks leen **solo** `LD_HOOK_READ_BLOCK`, `LD_HOOK_READ_SWITCH_FILE` y
`~/.claude/local-delegate-block-off`: los nombres viejos ni se aplican ni se detectan, y el evento
de telemetría ya no lleva `deprecated_names` (REQ-010, REQ-011 filas 1–3). `doctor` sigue leyendo
la cola de 7 días, donde solo llegan eventos de hooks 0.35–0.37 aún sin actualizar.

Desde la 0.41.0 (SDD claude-plugin-and-mods, retire-seven-names) los tres nombres viejos salen del
registro: siguen sin efecto en los hooks y `doctor` ya no avisa de ellos.
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
from test_deprecations import SEVEN_RETIRED

from local_delegate import (
    attribution,
    checks,
    config,
    deprecation_notices,
    deprecations,
    legacy_names,
    server,
)
from local_delegate import install as inst
from local_delegate.resources.hooks import hook_common

# Los nombres viejos salen de la lista histórica de los siete: el hook ya no los nombra (REQ-010)
# y, desde la 0.41.0, el registro tampoco.
_OLD_BY_NEW = {new: old for old, new, _surface in SEVEN_RETIRED}
NEW_SWITCH = "local-delegate-block-off"
OLD_SWITCH = _OLD_BY_NEW[NEW_SWITCH]
OLD_BLOCK = _OLD_BY_NEW["LD_HOOK_READ_BLOCK"]
OLD_SWITCH_VAR = _OLD_BY_NEW["LD_HOOK_READ_SWITCH_FILE"]


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
    for name in ("LD_HOOK_READ_SWITCH_FILE", OLD_SWITCH_VAR, OLD_BLOCK):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1")
    return home


# --- Una sola tabla ---------------------------------------------------------------------------


def test_the_file_table_is_the_same_in_the_hooks_and_in_the_package():
    """Los hooks no importan el paquete y llevan su copia: si divergen, uno escribe donde el otro
    no lee."""
    assert hook_common.FILE_NAMES == legacy_names.FILE_NAMES


def test_the_hook_names_the_switch_with_its_own_constant_and_no_old_name():
    """El interruptor sale de la tabla de ficheros (ya no se lee el viejo) y el hook lo nombra con
    una constante propia, que tiene que ser el nombre nuevo (REQ-010)."""
    assert hook_common.SWITCH_FILE_NAME == NEW_SWITCH
    assert "switch_file" not in hook_common.FILE_NAMES
    assert "switch_file" not in legacy_names.FILE_NAMES


# --- Temporales: escribe el nuevo, lee los dos ----------------------------------------------


def test_the_daemon_reads_the_block_notes_of_an_old_hook(temp_dir, tmp_path):
    """Un hook de la 0.34.0 sigue escribiendo `local-delegate-bloqueos.jsonl`: el bloqueo que
    provocó tiene que seguir contando como aceptado cuando el agente delega."""
    document = tmp_path / "report.md"
    old = temp_dir / "local-delegate-bloqueos.jsonl"
    note = {"id": "viejo1234567", "sha": hook_common.path_digest(str(document)), "ts": time.time()}
    old.write_text(json.dumps(note) + "\n", encoding="utf-8")

    assert server._recent_block_id(str(document)) == "viejo1234567"


def test_the_hook_writes_the_notes_only_under_the_new_name_and_the_most_recent_wins(
    temp_dir, tmp_path
):
    document = tmp_path / "report.md"
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

    assert hook_common.record_call({"tool_use_id": "toolu_new", "agent_type": "Explore"})
    assert (temp_dir / "local-delegate-calls" / "toolu_new.json").is_file()
    assert not (old / "toolu_new.json").exists()
    assert attribution.read_note("toolu_new")["agent_type"] == "Explore"


def test_the_health_mark_uses_the_new_name(temp_dir, monkeypatch):
    monkeypatch.setattr(hook_common, "_probe", lambda _timeout: True)

    assert hook_common.backend_available() is True

    names = sorted(p.name for p in temp_dir.iterdir())
    assert len(names) == 1 and names[0].startswith("local-delegate-health-"), names


# --- El interruptor -------------------------------------------------------------------------


def test_the_old_switch_no_longer_turns_off_and_the_new_one_does(home_env):
    """REQ-011 fila 3, en proceso: el viejo no apaga; su gemelo nuevo, con los mismos datos, sí."""
    (home_env / ".claude" / OLD_SWITCH).write_text("", encoding="utf-8")
    assert hook_common.block_state() == "on"

    (home_env / ".claude" / NEW_SWITCH).write_text("", encoding="utf-8")
    assert hook_common.block_state() == "off_file"


def test_without_a_switch_the_variable_rules(home_env):
    """Control: sin ningún fichero, el bloqueo está encendido."""
    assert hook_common.block_state() == "on"


# --- Con el hook INSTALADO: solo los nombres nuevos (REQ-010, REQ-011 filas 1–3) ---------------


def _run_installed_hook(home: Path, variables: dict[str, str]) -> subprocess.CompletedProcess:
    inst.apply(
        inst.plan_install(
            inst.Options(
                home=home,
                components={"hooks"},
                targets={"claude"},
                python_exe="python3",
                use_cli=False,
                # Se prueba el hook, no la migración de `install` (que renombraría el
                # interruptor viejo desde el volteo del registro, L6).
                migrate_retired_names=False,
            )
        ),
        dry_run=False,
        out=lambda *_a: None,
    )
    hooks_dir = home / ".claude" / "hooks" / inst.HOOKS_SUBDIR
    to_remove = {
        "LD_HOOK_READ_BLOCK",
        OLD_BLOCK,
        "LD_HOOK_READ_SWITCH_FILE",
        OLD_SWITCH_VAR,
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


def _installed_event(home: Path, variables: dict[str, str]) -> dict:
    """Último evento del hook de prompt instalado, con la telemetría en el HOME simulado."""
    log = home / "telemetry.jsonl"
    log.unlink(missing_ok=True)
    _run_installed_hook(home, {"LD_HOOK_TELEMETRY_LOG": str(log), **variables})
    return _last_event(log)


def test_installed_hook_ignores_the_old_block_variable(tmp_path):
    """Fila 1: la variable vieja sola ya no enciende el bloqueo; la nueva, con el mismo valor, sí."""
    old = _installed_event(tmp_path, {OLD_BLOCK: "1"})
    assert old["block"] == "off_variable"
    assert "deprecated_names" not in old, "el hook ya no detecta nombres viejos"

    new = _installed_event(tmp_path, {"LD_HOOK_READ_BLOCK": "1"})
    assert new["block"] == "on"


def test_installed_hook_ignores_the_old_switch_file_variable(tmp_path):
    """Fila 2: la variable vieja del interruptor no apaga aunque el fichero exista; la nueva sí."""
    switch = tmp_path / "off.flag"
    switch.write_text("", encoding="utf-8")

    old = _installed_event(tmp_path, {"LD_HOOK_READ_BLOCK": "1", OLD_SWITCH_VAR: str(switch)})
    assert old["block"] == "on"
    assert "deprecated_names" not in old

    new = _installed_event(
        tmp_path, {"LD_HOOK_READ_BLOCK": "1", "LD_HOOK_READ_SWITCH_FILE": str(switch)}
    )
    assert new["block"] == "off_file"


def test_installed_hook_ignores_the_old_switch_file(tmp_path):
    """Fila 3: `~/.claude/<interruptor viejo>` ya no apaga; `~/.claude/<nuevo>` sí."""
    claude = tmp_path / ".claude"
    claude.mkdir(exist_ok=True)
    (claude / OLD_SWITCH).write_text("", encoding="utf-8")

    old = _installed_event(tmp_path, {"LD_HOOK_READ_BLOCK": "1"})
    assert old["block"] == "on"
    assert "deprecated_names" not in old

    (claude / NEW_SWITCH).write_text("", encoding="utf-8")
    new = _installed_event(tmp_path, {"LD_HOOK_READ_BLOCK": "1"})
    assert new["block"] == "off_file"


def test_without_telemetry_nothing_is_written(tmp_path):
    _run_installed_hook(tmp_path, {"LD_HOOK_READ_BLOCK": "1"})

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
            _event(now - timedelta(days=9), [OLD_SWITCH_VAR]),
            _event(now - timedelta(days=2), [OLD_BLOCK]),
            _event(now - timedelta(hours=1)),
            _event(now, [OLD_SWITCH]),
        ],
        padding=3000,
    )
    assert log.stat().st_size > 2 * checks._TAIL_BLOCK, "el caso tiene que cruzar bloques"

    names = checks.deprecated_names_in_hook_telemetry(log, now=now)

    assert names == {OLD_BLOCK, OLD_SWITCH}


def _seed_every_old_name(home: Path, monkeypatch) -> None:
    """Los siete nombres viejos por los tres sitios que mira `doctor`: la cola de telemetría de los
    hooks, el `env` de `settings.json` y el interruptor viejo en `~/.claude/`."""
    old_names = [old for old, _new, _surface in SEVEN_RETIRED]
    log = home / "telemetry.jsonl"
    _write_telemetry(log, [_event(datetime.now(UTC), old_names)])
    monkeypatch.setattr(config, "HOOK_TELEMETRY_LOG", log)
    claude = home / ".claude"
    claude.mkdir(exist_ok=True)
    env = {old: "1" for old, _new, surface in SEVEN_RETIRED if surface == "env_var"}
    (claude / "settings.json").write_text(json.dumps({"env": env}), encoding="utf-8")
    (claude / OLD_SWITCH).write_text("", encoding="utf-8")


def test_doctor_no_longer_warns_about_the_seven_names(tmp_path, monkeypatch):
    """retire-seven-names: con los siete puestos en todos los sitios, el check da `OK` y no nombra
    ninguno; ni la variable de la shell se lee ya (`DEPRECATED_ENV_VALUES` no los tiene)."""
    _seed_every_old_name(tmp_path, monkeypatch)
    old_names = [old for old, _new, _surface in SEVEN_RETIRED]
    assert not set(config.DEPRECATED_ENV_VALUES) & set(old_names)

    result = checks._probe_deprecated_names(checks.Context(home=tmp_path))

    assert result.status == checks.OK, result
    assert not [old for old in old_names if old in f"{result.detail} {result.fix_hint}"]


def test_doctor_would_warn_if_the_names_were_still_registered(tmp_path, monkeypatch):
    """Control positivo del anterior: los mismos datos con los tres del interruptor de vuelta en
    el registro dan `WARN` por la telemetría, el `env` y el fichero."""
    _seed_every_old_name(tmp_path, monkeypatch)
    entries = tuple(
        deprecations.DeprecatedName("retired", old, new, "0.38.0", "0.40.0", retired_from=surface)
        for old, new, surface in SEVEN_RETIRED
        if new in ("LD_HOOK_READ_BLOCK", "LD_HOOK_READ_SWITCH_FILE", NEW_SWITCH)
    )
    monkeypatch.setattr(deprecations, "DEPRECATED_NAMES", entries)

    result = checks._probe_deprecated_names(checks.Context(home=tmp_path))

    assert result.status == checks.WARN
    for entry in entries:
        assert deprecation_notices.warning_text(entry) in result.detail
    assert f"renombra {OLD_SWITCH} a {NEW_SWITCH}" in result.fix_hint
    # Sin el `env` ni el fichero, la telemetría sola también avisa.
    (tmp_path / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".claude" / OLD_SWITCH).unlink()
    result = checks._probe_deprecated_names(checks.Context(home=tmp_path))
    assert result.status == checks.WARN
    assert "leído por los hooks" in result.detail
