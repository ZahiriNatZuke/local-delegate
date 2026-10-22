"""El interruptor del hook de lectura en dos capas (REQ-004; plan, lote F1-hook-entry).

*Activo* (registrar y avisar) lo dice el fichero de estado `LOG_DIR/read-hook.json`, la variable
`LD_HOOK_READ_ENABLED` o el argumento `--enabled` de la entrega por settings. *Bloquea* no cambia:
`~/.claude/local-delegate-block-off` > `LD_HOOK_READ_BLOCK`, con los mismos valores de `block_state`
que van a la telemetría de la ventana P-4.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

from local_delegate import read_switch

HOOKS = Path(__file__).parents[1] / "src" / "local_delegate" / "resources" / "hooks"


def _load_hook_common():
    spec = importlib.util.spec_from_file_location("_rs_hook_common", HOOKS / "hook_common.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = _load_hook_common()


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    target = tmp_path / "data"
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(target))
    monkeypatch.delenv("LD_HOOK_READ_ENABLED", raising=False)
    monkeypatch.delenv("LD_HOOK_READ_BLOCK", raising=False)
    # El fichero que apaga el bloqueo, fuera del `~/.claude` real.
    monkeypatch.setenv("LD_HOOK_READ_SWITCH_FILE", str(tmp_path / "block-off"))
    return target


# --- Contrato del fichero (lo escribe también F1-delivery-core sin importar el módulo) ----------


def test_reads_contract_file_shape(data_dir):
    """`{"active": …, "since": …}` en `LOG_DIR/read-hook.json`: la forma que escribe delivery-core."""
    assert read_switch.path() == data_dir / "read-hook.json"
    assert read_switch.active() is False, "sin fichero, apagado"

    data_dir.mkdir(parents=True)
    read_switch.path().write_text(
        json.dumps({"active": True, "since": "2026-10-21T22:00:00+00:00"}), encoding="utf-8"
    )
    assert read_switch.active() is True

    read_switch.path().write_text(
        json.dumps({"active": False, "since": "2026-10-21T22:00:00+00:00"}), encoding="utf-8"
    )
    assert read_switch.active() is False

    # Lo que no tiene la forma del contrato no enciende nada.
    for broken in ("{", "[]", '{"active": "yes"}', '{"active": 1}', '"true"'):
        read_switch.path().write_text(broken, encoding="utf-8")
        assert read_switch.active() is False, broken


def test_write_produces_exactly_the_contract(data_dir):
    target = read_switch.write(True)
    assert target == read_switch.path()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert set(data) == {"active", "since"}
    assert data["active"] is True
    datetime.fromisoformat(data["since"])  # ISO 8601

    # `since` es desde cuándo está en ese estado: reescribir el mismo valor no lo mueve.
    since = data["since"]
    read_switch.write(True)
    assert json.loads(target.read_text(encoding="utf-8"))["since"] == since

    read_switch.write(False)
    assert read_switch.active() is False


def test_the_state_file_lives_where_the_hooks_look(tmp_path, monkeypatch):
    """Sin `LOCAL_DELEGATE_LOG_DIR`, el directorio es el de `hook_common.log_dir` (el de `config`)."""
    monkeypatch.delenv("LOCAL_DELEGATE_LOG_DIR", raising=False)
    assert read_switch.path().parent == common.log_dir()
    monkeypatch.setenv("LOCAL_DELEGATE_LOG_DIR", str(tmp_path))
    assert read_switch.path().parent == common.log_dir() == tmp_path


# --- Capa «activo» ---------------------------------------------------------------------------------


def test_active_layer_state_file_or_enabled_env(data_dir, monkeypatch):
    assert read_switch.enabled() is False, "nada dicho: apagado"

    read_switch.write(True)
    assert read_switch.enabled() is True, "el fichero de estado enciende"

    read_switch.write(False)
    assert read_switch.enabled() is False
    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "1")
    assert read_switch.enabled() is True, "la variable enciende aunque el fichero diga false"

    monkeypatch.setenv("LD_HOOK_READ_ENABLED", "0")
    assert read_switch.enabled() is False
    assert read_switch.enabled(["--enabled"]) is True, "el argumento de la entrega por settings"


# --- Capa «bloquea»: sin cambios -------------------------------------------------------------------


def test_block_layer_precedence_unchanged(data_dir, monkeypatch, tmp_path):
    """block-off > `LD_HOOK_READ_BLOCK`; el fichero de estado NO enciende el bloqueo."""
    read_switch.write(True)
    assert common.block_state() == "off_variable", "activo no es bloquea"

    monkeypatch.setenv("LD_HOOK_READ_BLOCK", "1")
    assert common.block_state() == "on"

    (tmp_path / "block-off").write_text("", encoding="utf-8")
    assert common.block_state() == "off_file", "el fichero de apagado gana a la variable"

    read_switch.write(False)
    assert common.block_state() == "off_file"


def test_block_state_values_unchanged(data_dir, monkeypatch, tmp_path):
    """Los valores que van a la telemetría de la ventana P-4 no cambian."""
    seen = set()
    for block_env, block_off, state in (
        ("0", False, True),
        ("1", False, True),
        ("1", True, False),
        ("1", False, False),
    ):
        monkeypatch.setenv("LD_HOOK_READ_BLOCK", block_env)
        switch = tmp_path / "block-off"
        if block_off:
            switch.write_text("", encoding="utf-8")
        elif switch.exists():
            switch.unlink()
        read_switch.write(state)
        seen.add(common.block_state())
    assert seen == {"on", "off_file", "off_variable"}
